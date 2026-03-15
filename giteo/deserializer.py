"""Deserialize domain-split JSON → DaVinci Resolve timeline.

Reads the JSON files and applies the state back to a Resolve timeline.
"""

import hashlib
import os
import time
from typing import Dict, List

from .json_writer import read_all_domain_files, read_json
from .models import (
    AudioItem,
    AudioTrack,
    ColorGrade,
    ColorNodeGrade,
    Marker,
    SpeedChange,
    TextProperties,
    TimelineMetadata,
    Transform,
    VideoItem,
    VideoTrack,
)


def _load_cuts(project_dir: str) -> List[VideoTrack]:
    """Load video tracks from cuts.json."""
    data = read_json(os.path.join(project_dir, "timeline", "cuts.json"))
    if not data:
        return []
    return [VideoTrack.from_dict(t) for t in data.get("video_tracks", [])]


def _load_audio(project_dir: str) -> List[AudioTrack]:
    """Load audio tracks from audio.json."""
    data = read_json(os.path.join(project_dir, "timeline", "audio.json"))
    if not data:
        return []
    return [AudioTrack.from_dict(t) for t in data.get("audio_tracks", [])]


def _load_color(project_dir: str) -> Dict[str, ColorGrade]:
    """Load color grades from color.json."""
    data = read_json(os.path.join(project_dir, "timeline", "color.json"))
    if not data:
        return {}
    return {k: ColorGrade.from_dict(v) for k, v in data.get("grades", {}).items()}


def _load_markers(project_dir: str) -> List[Marker]:
    """Load markers from markers.json."""
    data = read_json(os.path.join(project_dir, "timeline", "markers.json"))
    if not data:
        return []
    return [Marker.from_dict(m) for m in data.get("markers", [])]


def _load_metadata(project_dir: str) -> TimelineMetadata:
    """Load metadata from metadata.json."""
    data = read_json(os.path.join(project_dir, "timeline", "metadata.json"))
    if not data:
        return TimelineMetadata()
    return TimelineMetadata.from_dict(data)


def _load_manifest(project_dir: str) -> dict:
    """Load asset manifest."""
    return read_json(os.path.join(project_dir, "assets", "manifest.json"))


def _snapshot_relative_files(project_dir: str, relative_dir: str) -> dict:
    """Capture file content hashes for a project subdirectory."""
    root = os.path.join(project_dir, relative_dir)
    if not os.path.isdir(root):
        return {}

    snapshot = {}
    for dirpath, _, filenames in os.walk(root):
        for filename in sorted(filenames):
            filepath = os.path.join(dirpath, filename)
            relpath = os.path.relpath(filepath, project_dir)
            with open(filepath, "rb") as f:
                snapshot[relpath] = hashlib.sha1(f.read()).hexdigest()
    return snapshot


def capture_restore_state(project_dir: str) -> dict:
    """Capture merge restore inputs that affect whether a full rebuild is needed."""
    return {
        "domains": read_all_domain_files(project_dir),
        "generators": _snapshot_relative_files(
            project_dir, os.path.join("timeline", "generators")
        ),
    }


def should_restore_overlays_only(before_state: dict, after_state: dict) -> bool:
    """Return True only when a merge changed color/markers and nothing else.

    Title/generator restores depend on both `cuts.json` and sidecar `.comp`
    files under `timeline/generators/`, so generator changes must force a
    full timeline rebuild even if the structural JSON domains are unchanged.
    """
    non_overlay_domains = ("cuts", "audio", "effects", "metadata", "manifest")
    before_domains = before_state.get("domains", {})
    after_domains = after_state.get("domains", {})

    domains_unchanged = all(
        before_domains.get(domain, {}) == after_domains.get(domain, {})
        for domain in non_overlay_domains
    )
    generators_unchanged = (
        before_state.get("generators", {}) == after_state.get("generators", {})
    )
    return domains_unchanged and generators_unchanged


def _apply_metadata(timeline, project, metadata: TimelineMetadata) -> None:
    """Apply metadata settings to a Resolve timeline."""
    timeline.SetSetting("timelineFrameRate", str(metadata.frame_rate))
    timeline.SetSetting("timelineResolutionWidth", str(metadata.width))
    timeline.SetSetting("timelineResolutionHeight", str(metadata.height))
    timeline.SetStartTimecode(metadata.start_timecode)


def _find_media_pool_item(media_pool, manifest: dict, media_ref: str):
    """Find or import a media pool item by its asset reference.

    Checks the existing media pool first (the clip may already be imported,
    even if the source file is offline/moved). Only attempts disk import
    as a fallback.
    """
    asset_info = manifest.get("assets", {}).get(media_ref)
    if not asset_info:
        return None

    original_path = asset_info.get("original_path", "")
    if not original_path:
        return None

    root_folder = media_pool.GetRootFolder()
    clips = root_folder.GetClipList()

    if clips:
        for clip in clips:
            clip_path = clip.GetClipProperty("File Path") or ""
            if clip_path == original_path:
                return clip

    if not os.path.exists(original_path):
        return None

    imported = media_pool.ImportMedia([original_path])
    if imported and len(imported) > 0:
        return imported[0]

    return None


def _wait_for_current_timeline(project, expected_timeline, max_retries: int = 10,
                                delay: float = 0.3) -> bool:
    """Wait until Resolve's GetCurrentTimeline() returns the expected timeline.

    Resolve's SetCurrentTimeline() is asynchronous — AppendToTimeline() targets
    whatever Resolve internally considers "current", which may still be the OLD
    timeline if we don't wait. This is the same pattern as SetCurrentTimecode()
    needing retries + sleep in the serializer.

    Returns True if the switch was confirmed, False if it timed out.
    """
    import time

    for attempt in range(max_retries):
        try:
            current = project.GetCurrentTimeline()
            if current is expected_timeline:
                return True
            # Also check by name as a fallback — object identity may not
            # work if Resolve returns wrapper objects
            if (current and expected_timeline and
                    current.GetName() == expected_timeline.GetName()):
                return True
        except (AttributeError, TypeError):
            pass

        if attempt == 0:
            # First retry: also re-issue SetCurrentTimeline in case it was dropped
            try:
                project.SetCurrentTimeline(expected_timeline)
            except (AttributeError, TypeError):
                pass

        time.sleep(delay)

    return False


def _create_fresh_timeline(project, media_pool, old_timeline):
    """Create a fresh empty timeline and set it as current.

    IMPORTANT: This function does NOT rename any timelines. Renaming is
    deferred until after clips are populated, because calling SetName()
    on the old timeline can cause Resolve to re-focus on it, which makes
    AppendToTimeline() target the old (non-empty) timeline instead of
    the new empty one.

    NOTE: For the main deserialization flow, prefer _create_timeline_with_clips()
    which uses CreateTimelineFromClips for atomic creation, avoiding the
    SetCurrentTimeline race condition entirely.

    Returns (new_timeline, old_name) or (old_timeline, None) on failure.
    """
    import time

    old_name = old_timeline.GetName() or "Timeline"
    timestamp = int(time.time())

    temp_name = f"giteo_temp_{timestamp}"
    new_timeline = media_pool.CreateEmptyTimeline(temp_name)

    if not new_timeline:
        for i in range(1, 10):
            new_timeline = media_pool.CreateEmptyTimeline(f"giteo_temp_{timestamp}_{i}")
            if new_timeline:
                break

    if not new_timeline:
        print("  Warning: Could not create fresh timeline — restoring in-place.")
        return old_timeline, None

    project.SetCurrentTimeline(new_timeline)
    switched = _wait_for_current_timeline(project, new_timeline)

    if not switched:
        print("  Warning: Resolve did not confirm timeline switch — "
              "clips may be placed on wrong timeline.")

    return new_timeline, old_name


def _reimport_media(media_pool, manifest: dict, media_ref: str):
    """Re-import a media file to get a distinct MediaPoolItem.

    When multiple clips on a timeline come from the same source file (e.g. a
    clip was split), both CreateTimelineFromClips and AppendToTimeline silently
    deduplicate entries that share the same mediaPoolItem. Re-importing the
    file creates a new pool item that Resolve treats as a separate clip.
    """
    asset_info = manifest.get("assets", {}).get(media_ref)
    if not asset_info:
        return None
    original_path = asset_info.get("original_path", "")
    if not original_path or not os.path.exists(original_path):
        return None

    imported = media_pool.ImportMedia([original_path])
    if imported and len(imported) > 0:
        return imported[0]
    return None


def _collect_video_clip_infos(media_pool, video_tracks: List[VideoTrack],
                              manifest: dict) -> List[dict]:
    """Collect clip info dicts for CreateTimelineFromClips.

    Skips generator items (Text+, etc.) — those are handled separately
    via InsertFusionGeneratorIntoTimeline after media clips are placed.

    Uses only the documented clip info keys (mediaPoolItem, startFrame,
    endFrame) to avoid undefined behavior from undocumented parameters.
    When multiple clips share the same source file (split clips), each
    additional clip gets a freshly-imported mediaPoolItem. Without this,
    Resolve silently deduplicates and only places the first clip.
    """
    clip_infos = []
    seen_refs = set()
    for track in video_tracks:
        for item in track.items:
            if item.is_generator:
                continue
            if item.media_ref in seen_refs:
                # Split clip — re-import to get a unique pool item
                pool_item = _reimport_media(media_pool, manifest, item.media_ref)
                if not pool_item:
                    # Fallback: try the shared item (may be deduped)
                    pool_item = _find_media_pool_item(media_pool, manifest, item.media_ref)
            else:
                pool_item = _find_media_pool_item(media_pool, manifest, item.media_ref)
                seen_refs.add(item.media_ref)

            if not pool_item:
                print(f"  Warning: Could not find media for '{item.name}' ({item.media_ref})")
                continue
            clip_infos.append({
                "mediaPoolItem": pool_item,
                "startFrame": item.source_start_frame,
                "endFrame": item.source_end_frame,
            })
    return clip_infos


def _create_timeline_with_clips(media_pool, clip_infos: List[dict],
                                timestamp: int):
    """Create a new timeline pre-populated with the FIRST video clip.

    Uses CreateTimelineFromClips with only the first clip — this is an atomic
    operation that avoids the SetCurrentTimeline race condition that caused
    clip duplication with the old CreateEmptyTimeline + AppendToTimeline flow.

    Remaining clips (index 1+) must be added afterwards via AppendToTimeline
    by the caller, because CreateTimelineFromClips silently drops all but the
    first clip when multiple clip_infos are passed.

    Returns (new_timeline, created_with_first_clip, remaining_clip_infos).
    """
    temp_name = f"giteo_temp_{timestamp}"
    new_timeline = None
    created_with_first = False
    first_only = [clip_infos[0]] if clip_infos else []
    remaining = clip_infos[1:] if len(clip_infos) > 1 else []

    if first_only:
        try:
            new_timeline = media_pool.CreateTimelineFromClips(temp_name, first_only)
            if new_timeline:
                created_with_first = True
        except (AttributeError, TypeError):
            pass

    if not new_timeline:
        new_timeline = media_pool.CreateEmptyTimeline(temp_name)
        remaining = clip_infos  # All clips need AppendToTimeline

    if not new_timeline:
        for i in range(1, 5):
            alt_name = f"giteo_temp_{timestamp}_{i}"
            if first_only:
                try:
                    new_timeline = media_pool.CreateTimelineFromClips(alt_name, first_only)
                    if new_timeline:
                        created_with_first = True
                        remaining = clip_infos[1:]
                except (AttributeError, TypeError):
                    pass
            if not new_timeline:
                new_timeline = media_pool.CreateEmptyTimeline(alt_name)
                remaining = clip_infos
            if new_timeline:
                break

    return new_timeline, created_with_first, remaining


def _clear_markers(timeline) -> None:
    """Remove all timeline markers when the API supports it."""
    try:
        markers = timeline.GetMarkers()
        if markers:
            for frame in list(markers.keys()):
                timeline.DeleteMarkerAtFrame(frame)
    except (AttributeError, TypeError):
        pass


def _apply_video_tracks(timeline, media_pool, video_tracks: List[VideoTrack], manifest: dict) -> None:
    """Apply video track items to the Resolve timeline via AppendToTimeline.

    Skips generator items — those are handled by _apply_generators.

    This is the FALLBACK path used only when CreateTimelineFromClips fails.
    The caller must ensure the timeline is confirmed as current before calling.

    All clips for a track are batched into a SINGLE AppendToTimeline call.
    Calling AppendToTimeline once-per-clip with the same mediaPoolItem causes
    Resolve to silently ignore the second call (deduplication). Batching all
    clips into one call tells Resolve to place multiple subclips from the same
    source media sequentially.
    """
    for track in video_tracks:
        while timeline.GetTrackCount("video") < track.index:
            timeline.AddTrack("video")

        clip_infos = []
        for item in track.items:
            if item.is_generator:
                continue
            pool_item = _find_media_pool_item(media_pool, manifest, item.media_ref)
            if not pool_item:
                print(f"  Warning: Could not find media for '{item.name}' ({item.media_ref})")
                continue

            clip_infos.append({
                "mediaPoolItem": pool_item,
                "startFrame": item.source_start_frame,
                "endFrame": item.source_end_frame,
            })

        if clip_infos:
            media_pool.AppendToTimeline(clip_infos)


def _apply_audio_properties_only(timeline, audio_tracks: List[AudioTrack]) -> None:
    """Apply volume/pan to linked audio clips that already exist on the timeline.

    When CreateTimelineFromClips adds a video+audio file, Resolve automatically
    creates linked audio clips. Calling AppendToTimeline again for the same
    media would create DUPLICATE video clips. This function only sets audio
    properties on the clips that are already there.
    """
    for track in audio_tracks:
        audio_count = timeline.GetTrackCount("audio") or 0
        if audio_count < track.index:
            continue

        clips = timeline.GetItemListInTrack("audio", track.index)
        if not clips:
            continue

        for i, item in enumerate(track.items):
            if i >= len(clips):
                break
            try:
                clips[i].SetProperty("Volume", item.volume)
                clips[i].SetProperty("Pan", item.pan)
            except (AttributeError, TypeError):
                pass


def _apply_audio_tracks(timeline, media_pool, audio_tracks: List[AudioTrack],
                        manifest: dict, skip_media_refs: set = None) -> None:
    """Apply audio track items to the Resolve timeline.

    Args:
        skip_media_refs: Set of media_ref strings to skip (already on timeline
            as linked audio from CreateTimelineFromClips). Prevents duplicate
            video clips from being created when AppendToTimeline is called
            with a video+audio media pool item.
    """
    skip_media_refs = skip_media_refs or set()

    for track in audio_tracks:
        while timeline.GetTrackCount("audio") < track.index:
            timeline.AddTrack("audio")

        for item in track.items:
            if item.media_ref in skip_media_refs:
                continue

            pool_item = _find_media_pool_item(media_pool, manifest, item.media_ref)
            if not pool_item:
                print(f"  Warning: Could not find media for audio '{item.id}' ({item.media_ref})")
                continue

            clip_info = {
                "mediaPoolItem": pool_item,
                "startFrame": item.start_frame,
                "endFrame": item.end_frame,
            }
            media_pool.AppendToTimeline([clip_info])

            clips = timeline.GetItemListInTrack("audio", track.index)
            if clips:
                placed_clip = clips[-1]
                try:
                    placed_clip.SetProperty("Volume", item.volume)
                    placed_clip.SetProperty("Pan", item.pan)
                except (AttributeError, TypeError):
                    pass


def _insert_fusion_item(timeline, item):
    """Insert a Fusion title or generator into the timeline.

    Resolve has separate APIs:
      - InsertFusionTitleIntoTimeline — for Titles (Text+, Text, Scroll)
      - InsertFusionGeneratorIntoTimeline — for Generators (Solid Color)
      - InsertOFXGeneratorIntoTimeline — for OFX-based generators

    Tries the most likely API first based on item_type, then falls back.
    Returns the inserted TimelineItem, or None on failure.

    NOTE: All three APIs insert on V1 at the playhead position regardless
    of the original track. There is no API to control target track.
    """
    name = item.generator_name or "Text+"

    if item.is_title:
        apis = [
            "InsertFusionTitleIntoTimeline",
            "InsertFusionGeneratorIntoTimeline",
            "InsertOFXGeneratorIntoTimeline",
        ]
    else:
        apis = [
            "InsertFusionGeneratorIntoTimeline",
            "InsertFusionTitleIntoTimeline",
            "InsertOFXGeneratorIntoTimeline",
        ]

    for api_name in apis:
        fn = getattr(timeline, api_name, None)
        if not callable(fn):
            continue
        try:
            result = fn(name)
            if result:
                print(f"  Inserted '{name}' via {api_name}")
                # These APIs return a TimelineItem in Resolve 18+.
                # Older versions may return True. In that case, fall
                # through to the caller's search logic.
                if result is True:
                    return True
                return result
        except (AttributeError, TypeError):
            continue

    return None


def _set_playhead(timeline, frame: int) -> None:
    """Move the playhead to a specific frame before inserting a generator."""
    try:
        fps = float(timeline.GetSetting("timelineFrameRate") or 24)
        start_frame = timeline.GetStartFrame()
        start_tc = timeline.GetStartTimecode() or "01:00:00:00"
        tc = _frame_to_tc(frame, start_frame, start_tc, fps)
        timeline.SetCurrentTimecode(tc)
        time.sleep(0.15)
        for _ in range(3):
            if timeline.GetCurrentTimecode() == tc:
                break
            timeline.SetCurrentTimecode(tc)
            time.sleep(0.15)
    except (AttributeError, TypeError, ValueError):
        pass


def _restore_text_via_fusion(clip, text_props) -> bool:
    """Set text properties on an inserted clip via its Fusion composition.

    Fallback for when ImportFusionComp doesn't work. Tries to find
    any text-related tool (TextPlus, Text3D, etc.) and set properties.
    """
    if not text_props:
        return False
    try:
        comp_count = clip.GetFusionCompCount()
        if not comp_count or comp_count < 1:
            return False
        comp = clip.GetFusionCompByIndex(1)
        if not comp:
            return False

        tools = comp.GetToolList() or {}
        text_tool = None
        if isinstance(tools, dict):
            for tool in tools.values():
                try:
                    reg_id = (tool.GetAttrs() or {}).get("TOOLS_RegID", "")
                    if reg_id in ("TextPlus", "Text3D", "StyledText"):
                        text_tool = tool
                        break
                except (AttributeError, TypeError):
                    continue
            if not text_tool:
                text_tool = list(tools.values())[0] if tools else None

        if not text_tool:
            return False

        if text_props.styled_text:
            text_tool.SetInput("StyledText", text_props.styled_text)
        if text_props.font:
            text_tool.SetInput("Font", text_props.font)
        if text_props.size > 0:
            text_tool.SetInput("Size", text_props.size)
        if text_props.bold:
            text_tool.SetInput("Bold", 1)
        if text_props.italic:
            text_tool.SetInput("Italic", 1)
        if text_props.color:
            text_tool.SetInput("Red1", text_props.color.get("r", 1.0))
            text_tool.SetInput("Green1", text_props.color.get("g", 1.0))
            text_tool.SetInput("Blue1", text_props.color.get("b", 1.0))

        print(f"  Set text properties via Fusion comp: "
              f"'{text_props.styled_text[:30]}'")
        return True
    except (AttributeError, TypeError) as e:
        print(f"  Warning: Could not set text via Fusion: {e}")
        return False


def _make_transparent_png() -> bytes:
    """Generate a minimal 1x1 transparent RGBA PNG (no dependencies)."""
    import struct
    import zlib

    def _chunk(ctype, data):
        c = ctype + data
        crc = struct.pack('>I', zlib.crc32(c) & 0xFFFFFFFF)
        return struct.pack('>I', len(data)) + c + crc

    sig = b'\x89PNG\r\n\x1a\n'
    ihdr = _chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0))
    idat = _chunk(b'IDAT', zlib.compress(b'\x00\x00\x00\x00\x00'))
    iend = _chunk(b'IEND', b'')
    return sig + ihdr + idat + iend


def _try_v2_placement(timeline, media_pool, item, project_dir,
                       generators_dir) -> "TimelineItem | None":
    """Place a generator on V2+ using a transparent image + AppendToTimeline.

    InsertFusionTitleIntoTimeline always targets V1. The only way to get
    a clip on V2 is via AppendToTimeline with trackIndex, which requires
    a media pool item. We create a 1x1 transparent PNG, import it, place
    it on the target track, then ImportFusionComp to add the text overlay.

    Uses recordFrame to position the clip at the correct timecode. The
    previous clip shrinkage was caused by a source/timeline FPS mismatch
    in the serializer, not by recordFrame.

    Returns the placed TimelineItem, or None if any step fails.
    """
    target_track = item.track_index
    if target_track < 1:
        target_track = 1

    temp_dir = os.path.join(project_dir, ".giteo", "temp")
    os.makedirs(temp_dir, exist_ok=True)
    png_path = os.path.join(temp_dir, f"placeholder_{item.id}.png")

    try:
        with open(png_path, 'wb') as f:
            f.write(_make_transparent_png())
    except OSError:
        return None

    pool_items = None
    try:
        pool_items = media_pool.ImportMedia([png_path])
    except (AttributeError, TypeError):
        pass

    if not pool_items:
        return None

    pool_item = pool_items[0]

    while timeline.GetTrackCount("video") < target_track:
        timeline.AddTrack("video")

    duration = max(item.record_end_frame - item.record_start_frame, 1)

    appended = None
    try:
        appended = media_pool.AppendToTimeline([{
            "mediaPoolItem": pool_item,
            "startFrame": 0,
            "endFrame": duration,
            "trackIndex": target_track,
            "recordFrame": item.record_start_frame,
        }])
    except (AttributeError, TypeError):
        pass

    if not appended:
        return None

    clip = appended[0] if isinstance(appended, list) else appended
    if not clip:
        return None

    time.sleep(0.3)

    comp_imported = False
    if item.fusion_comp_file:
        comp_path = os.path.join(generators_dir, item.fusion_comp_file)
        if os.path.exists(comp_path):
            try:
                imported_comp = clip.ImportFusionComp(comp_path)
                if imported_comp:
                    comp_imported = True
                    try:
                        comp_names = clip.GetFusionCompNameList() or []
                        if len(comp_names) > 1:
                            clip.LoadFusionCompByName(comp_names[-1])
                    except (AttributeError, TypeError):
                        pass
                    print(f"  Placed '{item.generator_name}' on V{target_track} "
                          f"with Fusion comp")
            except (AttributeError, TypeError):
                pass

    if not comp_imported and item.text_properties:
        _restore_text_via_fusion(clip, item.text_properties)

    return clip


def _find_inserted_clip(timeline, result):
    """Resolve the TimelineItem from an insert API's return value.

    InsertFusionTitleIntoTimeline returns a TimelineItem in Resolve 18+
    but may return True in older versions. When we only get True, scan
    V1 (titles always land on V1) for the last clip.
    """
    if result and result is not True:
        return result

    try:
        clips = timeline.GetItemListInTrack("video", 1)
        if clips:
            return clips[-1]
    except (AttributeError, TypeError):
        pass
    return None


def _get_v1_end_frame(timeline) -> int:
    """Find the frame after the last clip on V1.

    Falls back to timeline start frame if V1 is empty.
    """
    end = 0
    try:
        clips = timeline.GetItemListInTrack("video", 1)
        if clips:
            for c in clips:
                clip_end = c.GetEnd() or 0
                if clip_end > end:
                    end = clip_end
    except (AttributeError, TypeError):
        pass
    if end == 0:
        try:
            end = timeline.GetStartFrame() or 0
        except (AttributeError, TypeError):
            pass
    return end


def _apply_generators(timeline, video_tracks: List[VideoTrack],
                      project_dir: str, media_pool=None) -> None:
    """Insert generator/text clips and restore their Fusion compositions.

    Strategy for track placement:
    - V2+ items: Use transparent PNG + AppendToTimeline(trackIndex=N)
      to place directly on the correct track as an overlay.
    - V1 items (or V2 fallback): Insert at end of V1 to avoid pushing
      existing clips, with manual drag instructions.

    For each generator/title item:
    1. Try V2+ placement via transparent image if target track > 1
    2. Fall back to end-of-V1 insertion if that fails
    3. Import Fusion comp / set text properties
    4. Apply transform
    """
    generators_dir = os.path.join(project_dir, "timeline", "generators")

    generators = [(track, item)
                   for track in video_tracks
                   for item in track.items
                   if item.is_generator]

    # For items from old saves that lack fusion_comp_file, try to find
    # a .comp file by item ID (it may have been committed separately).
    for _track, item in generators:
        if not item.fusion_comp_file:
            candidate = f"{item.id}.comp"
            if os.path.exists(os.path.join(generators_dir, candidate)):
                item.fusion_comp_file = candidate

    if not generators:
        return

    print(f"  Restoring {len(generators)} generator/title clip(s)...")

    fps = float(timeline.GetSetting("timelineFrameRate") or 24)
    start_frame = timeline.GetStartFrame() or 0
    start_tc = timeline.GetStartTimecode() or "01:00:00:00"

    manual_steps = []

    for track, item in generators:
        inserted_clip = None
        needs_manual_move = False

        # Strategy 1: V2+ placement via transparent PNG + AppendToTimeline
        # with recordFrame to position at the correct timecode.
        if track.index > 1 and media_pool:
            inserted_clip = _try_v2_placement(
                timeline, media_pool, item, project_dir, generators_dir)

        # Strategy 2: Fall back to V1 insertion at end of timeline
        if not inserted_clip:
            end_frame = _get_v1_end_frame(timeline)
            _set_playhead(timeline, end_frame)

            result = _insert_fusion_item(timeline, item)
            if not result:
                print(f"  WARNING: Could not insert '{item.generator_name}' "
                      f"for {item.id} — tried all available APIs")
                continue

            time.sleep(0.3)

            inserted_clip = _find_inserted_clip(timeline, result)
            if not inserted_clip:
                print(f"  WARNING: Insert returned success but could not "
                      f"locate clip for {item.id}")
                continue

            comp_imported = False
            if item.fusion_comp_file:
                comp_path = os.path.join(generators_dir, item.fusion_comp_file)
                if os.path.exists(comp_path):
                    try:
                        import_result = inserted_clip.ImportFusionComp(comp_path)
                        if import_result:
                            comp_imported = True
                    except (AttributeError, TypeError):
                        pass

            if not comp_imported and item.text_properties:
                _restore_text_via_fusion(inserted_clip, item.text_properties)

            needs_manual_move = True
            target_tc = _frame_to_tc(item.record_start_frame, start_frame,
                                     start_tc, fps)
            text_label = ""
            if item.text_properties and item.text_properties.styled_text:
                text_label = item.text_properties.styled_text[:40].replace("\n", " ")

            manual_steps.append({
                "name": item.generator_name,
                "text": text_label,
                "target_track": track.index,
                "target_tc": target_tc,
            })

        # Apply transform
        t = item.transform
        try:
            inserted_clip.SetProperty("Pan", t.pan)
            inserted_clip.SetProperty("Tilt", t.tilt)
            inserted_clip.SetProperty("ZoomX", t.zoom_x)
            inserted_clip.SetProperty("ZoomY", t.zoom_y)
            inserted_clip.SetProperty("Opacity", t.opacity)
        except (AttributeError, TypeError):
            pass

    if manual_steps:
        print("")
        print("  ┌─────────────────────────────────────────────────┐")
        print("  │  ACTION NEEDED: Move text overlay(s) into place │")
        print("  └─────────────────────────────────────────────────┘")
        print("  Resolve places text on the correct track but can't")
        print("  position it at the exact timecode via the API.")
        print("  Drag these clips to the right position:")
        print("")
        for step in manual_steps:
            label = f"'{step['text']}'" if step["text"] else step["name"]
            print(f"    -> {label}  ->  V{step['target_track']} "
                  f"at {step['target_tc']}")
        print("")


def _apply_speed(clip, speed: SpeedChange, item_id: str) -> None:
    """Apply speed/retime properties to a Resolve timeline item."""
    if not speed.is_retimed and speed.retime_process == 0 and speed.motion_estimation == 0:
        return

    if speed.retime_process != 0:
        try:
            clip.SetProperty("RetimeProcess", speed.retime_process)
        except (AttributeError, TypeError):
            pass

    if speed.motion_estimation != 0:
        try:
            clip.SetProperty("MotionEstimation", speed.motion_estimation)
        except (AttributeError, TypeError):
            pass

    if speed.is_retimed:
        try:
            result = clip.SetProperty("Speed", speed.speed_percent)
            if not result:
                print(f"  Warning: SetProperty('Speed') returned False for {item_id}")
        except (AttributeError, TypeError) as e:
            print(f"  Warning: Could not set speed for {item_id}: {e}")


def _apply_video_speed(timeline, video_tracks: List[VideoTrack]) -> None:
    """Apply speed changes to video clips already on the timeline.

    Skips generator items — they don't go through the same clip index mapping.
    """
    track_count = timeline.GetTrackCount("video")
    for track in video_tracks:
        if track.index > track_count:
            continue
        clips = timeline.GetItemListInTrack("video", track.index)
        if not clips:
            continue
        clip_idx = 0
        for item in track.items:
            if item.is_generator:
                continue
            if clip_idx >= len(clips):
                break
            _apply_speed(clips[clip_idx], item.speed, item.id)
            clip_idx += 1


def _apply_audio_speed(timeline, audio_tracks: List[AudioTrack]) -> None:
    """Apply speed changes to audio clips already on the timeline."""
    audio_count = timeline.GetTrackCount("audio") or 0
    for track in audio_tracks:
        if track.index > audio_count:
            continue
        clips = timeline.GetItemListInTrack("audio", track.index)
        if not clips:
            continue
        for i, item in enumerate(track.items):
            if i >= len(clips):
                break
            _apply_speed(clips[i], item.speed, item.id)


def _apply_extended_video_properties(timeline, video_tracks: List[VideoTrack]) -> None:
    """Apply extended properties: transform details, composite mode, clip enabled, etc.

    Skips generator items — they get properties applied in _apply_generators.
    """
    track_count = timeline.GetTrackCount("video")
    for track in video_tracks:
        if track.index > track_count:
            continue
        clips = timeline.GetItemListInTrack("video", track.index)
        if not clips:
            continue
        clip_idx = 0
        for item in track.items:
            if item.is_generator:
                continue
            if clip_idx >= len(clips):
                break
            clip = clips[clip_idx]
            clip_idx += 1
            t = item.transform

            _set_prop = clip.SetProperty
            try:
                _set_prop("Pan", t.pan)
                _set_prop("Tilt", t.tilt)
                _set_prop("ZoomX", t.zoom_x)
                _set_prop("ZoomY", t.zoom_y)
                _set_prop("Opacity", t.opacity)
            except (AttributeError, TypeError):
                pass

            for prop, val, default in [
                ("RotationAngle", t.rotation_angle, 0.0),
                ("AnchorPointX", t.anchor_x, 0.0),
                ("AnchorPointY", t.anchor_y, 0.0),
                ("Pitch", t.pitch, 0.0),
                ("Yaw", t.yaw, 0.0),
                ("CropLeft", t.crop_left, 0.0),
                ("CropRight", t.crop_right, 0.0),
                ("CropTop", t.crop_top, 0.0),
                ("CropBottom", t.crop_bottom, 0.0),
                ("CropSoftness", t.crop_softness, 0.0),
                ("Distortion", t.distortion, 0.0),
            ]:
                if val != default:
                    try:
                        _set_prop(prop, val)
                    except (AttributeError, TypeError):
                        pass

            for bool_prop, val in [
                ("FlipX", t.flip_x),
                ("FlipY", t.flip_y),
                ("CropRetain", t.crop_retain),
            ]:
                if val:
                    try:
                        _set_prop(bool_prop, val)
                    except (AttributeError, TypeError):
                        pass

            if item.composite_mode != 0:
                try:
                    _set_prop("CompositeMode", item.composite_mode)
                except (AttributeError, TypeError):
                    pass

            if item.dynamic_zoom_ease != 0:
                try:
                    _set_prop("DynamicZoomEase", item.dynamic_zoom_ease)
                except (AttributeError, TypeError):
                    pass

            if not item.clip_enabled:
                try:
                    clip.SetClipEnabled(False)
                except (AttributeError, TypeError):
                    pass


def _apply_grade_from_drx(timeline, clip, drx_path: str, item_id: str) -> bool:
    """Apply a DRX grade using whichever Resolve API is actually available."""
    timeline_apply = getattr(timeline, "ApplyGradeFromDRX", None)
    if callable(timeline_apply):
        for args in ((drx_path, 0, [clip]), (drx_path, 0, clip)):
            try:
                result = timeline_apply(*args)
                if isinstance(result, bool):
                    return result
            except TypeError:
                continue
            except Exception as e:
                print(f"  Warning: Timeline DRX apply failed for {item_id}: {e}")
                break

    get_node_graph = getattr(clip, "GetNodeGraph", None)
    if callable(get_node_graph):
        try:
            node_graph = get_node_graph()
        except Exception as e:
            print(f"  Warning: Could not access node graph for {item_id}: {e}")
            node_graph = None

        graph_apply = getattr(node_graph, "ApplyGradeFromDRX", None) if node_graph else None
        if callable(graph_apply):
            try:
                result = graph_apply(drx_path, 0)
                if isinstance(result, bool):
                    return result
            except Exception as e:
                print(f"  Warning: Node graph DRX apply failed for {item_id}: {e}")

    print(f"  Warning: DRX restore API unavailable for {item_id}")
    return False


def _frame_to_tc(frame: int, start_frame: int, start_tc: str, fps: float) -> str:
    """Convert an absolute timeline frame to timecode."""
    parts = start_tc.split(":")
    hh, mm, ss, ff = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
    ifps = int(round(fps))
    start_total = ((hh * 3600 + mm * 60 + ss) * ifps) + ff

    total = start_total + (frame - start_frame)
    if total < 0:
        total = 0

    out_ff = total % ifps
    total_secs = total // ifps
    out_ss = total_secs % 60
    total_mins = total_secs // 60
    out_mm = total_mins % 60
    out_hh = total_mins // 60
    return f"{out_hh:02d}:{out_mm:02d}:{out_ss:02d}:{out_ff:02d}"


def _focus_clip_for_color_page(timeline, clip):
    """Move the playhead to the clip so Color page APIs act on the right item."""
    try:
        fps = float(timeline.GetSetting("timelineFrameRate") or 24)
        start_frame = int(timeline.GetStartFrame())
        start_tc = timeline.GetStartTimecode() or "01:00:00:00"
        clip_start = int(clip.GetStart())
    except (AttributeError, TypeError, ValueError):
        return clip

    tc = _frame_to_tc(clip_start + 1, start_frame, start_tc, fps)
    try:
        timeline.SetCurrentTimecode(tc)
        time.sleep(0.15)
        for _ in range(3):
            current = timeline.GetCurrentTimecode()
            if current == tc:
                break
            timeline.SetCurrentTimecode(tc)
            time.sleep(0.15)
    except (AttributeError, TypeError):
        return clip

    try:
        current_clip = timeline.GetCurrentVideoItem()
        if current_clip:
            return current_clip
    except (AttributeError, TypeError):
        pass

    return clip


def _apply_cdl(clip, node: ColorNodeGrade) -> bool:
    """Apply CDL values to a clip node via SetCDL(). Returns True on success."""
    if not (node.slope or node.offset or node.power or node.saturation is not None):
        return False
    cdl = {}
    if node.slope:
        cdl["NodeIndex"] = str(node.index)
        cdl["Slope"] = " ".join(str(v) for v in node.slope)
    if node.offset:
        cdl["Offset"] = " ".join(str(v) for v in node.offset)
    if node.power:
        cdl["Power"] = " ".join(str(v) for v in node.power)
    if node.saturation is not None:
        cdl["Saturation"] = str(node.saturation)
    if not cdl:
        return False
    try:
        return bool(clip.SetCDL(cdl))
    except (AttributeError, TypeError) as e:
        print(f"  Warning: SetCDL failed: {e}")
        return False


def _apply_clip_adjustments(clip, node: ColorNodeGrade) -> None:
    """Apply clip-level color adjustments via SetProperty()."""
    props = {
        "Contrast": node.contrast,
        "Saturation": node.saturation,
        "Hue": node.hue,
        "Pivot": node.pivot,
        "ColorBoost": node.color_boost,
    }
    for prop_name, value in props.items():
        if value is not None:
            try:
                clip.SetProperty(prop_name, value)
            except (AttributeError, TypeError):
                pass


def _apply_color(timeline, color_grades: Dict[str, ColorGrade],
                 project_dir: str = "", resolve_app=None) -> None:
    """Apply color grading data to clips on the timeline.

    Restore priority:
    1. DRX grade stills (complete grade including curves, qualifiers, etc.)
    2. CDL values via SetCDL() (if present in JSON)
    3. Clip-level adjustments via SetProperty() (contrast, saturation, etc.)
    4. LUT paths via SetLUT()
    """
    grades_dir = os.path.join(project_dir, "timeline", "grades") if project_dir else ""
    saved_page = None

    if resolve_app:
        try:
            saved_page = resolve_app.GetCurrentPage()
            if saved_page != "color":
                resolve_app.OpenPage("color")
                time.sleep(0.3)
        except (AttributeError, TypeError):
            saved_page = None

    try:
        track_count = timeline.GetTrackCount("video")
        for track_idx in range(1, track_count + 1):
            clips = timeline.GetItemListInTrack("video", track_idx)
            if not clips:
                continue

            for i, clip in enumerate(clips):
                item_id = f"item_{track_idx:03d}_{i:03d}"
                grade = color_grades.get(item_id)
                if not grade:
                    continue

                # Priority 1: DRX grade restore (complete node-based grade)
                if grade.drx_file and grades_dir:
                    drx_path = os.path.join(grades_dir, grade.drx_file)
                    if os.path.exists(drx_path):
                        target_clip = _focus_clip_for_color_page(timeline, clip)
                        if _apply_grade_from_drx(timeline, target_clip, drx_path, item_id):
                            time.sleep(0.1)
                            continue
                    else:
                        print(f"  Warning: Missing DRX file for {item_id}: {drx_path}")

                # Priority 2: CDL values per node
                cdl_applied = False
                for node in grade.nodes:
                    if _apply_cdl(clip, node):
                        cdl_applied = True

                # Priority 3: Clip-level adjustments (contrast, saturation, etc.)
                if grade.nodes:
                    _apply_clip_adjustments(clip, grade.nodes[0])

                # Priority 4: LUT paths per node
                if not cdl_applied:
                    for node in grade.nodes:
                        if node.lut:
                            try:
                                clip.SetLUT(node.index, node.lut)
                            except (AttributeError, TypeError):
                                pass
    finally:
        if saved_page and resolve_app and saved_page != "color":
            try:
                resolve_app.OpenPage(saved_page)
            except (AttributeError, TypeError):
                pass


def _apply_markers(timeline, markers: List[Marker]) -> None:
    """Apply markers to the timeline."""
    for marker in markers:
        timeline.AddMarker(
            marker.frame,
            marker.color,
            marker.name,
            marker.note,
            marker.duration,
        )


def _timeline_has_clips(timeline) -> bool:
    """Check if a timeline has any clips on it."""
    try:
        for track_type in ("video", "audio"):
            count = timeline.GetTrackCount(track_type)
            for idx in range(1, (count or 0) + 1):
                clips = timeline.GetItemListInTrack(track_type, idx)
                if clips:
                    return True
    except (AttributeError, TypeError):
        pass
    return False


def deserialize_timeline(timeline, project, project_dir: str, resolve_app=None) -> None:
    """Deserialize domain-split JSON files back into a Resolve timeline.

    Flow:
    1. Collect video clip infos from JSON
    2. Create a new timeline atomically with video clips via
       CreateTimelineFromClips (avoids SetCurrentTimeline race condition)
    3. Set new timeline as current, verify the switch
    4. Apply audio, color, markers
    5. Rename old and new timelines (AFTER all population)

    Previous versions used CreateEmptyTimeline + SetCurrentTimeline +
    AppendToTimeline, but SetCurrentTimeline is async and AppendToTimeline
    targets whatever Resolve internally considers "current". When the switch
    didn't take effect in time, clips were appended to the OLD timeline,
    causing duplication.

    Args:
        timeline: Resolve Timeline object (current, will be replaced)
        project: Resolve Project object
        project_dir: Path to the giteo project directory
    """
    import time

    metadata = _load_metadata(project_dir)
    video_tracks = _load_cuts(project_dir)
    audio_tracks = _load_audio(project_dir)
    color_grades = _load_color(project_dir)
    markers = _load_markers(project_dir)
    manifest = _load_manifest(project_dir)

    media_pool = project.GetMediaPool()
    old_name = timeline.GetName() or "Timeline"
    timestamp = int(time.time())

    video_clip_infos = _collect_video_clip_infos(media_pool, video_tracks, manifest)

    # Phase 2: Create new timeline with FIRST video clip only.
    # CreateTimelineFromClips only reliably handles one clip per call.
    # Remaining clips are added via AppendToTimeline after the switch.
    new_timeline, created_with_first, remaining_clip_infos = \
        _create_timeline_with_clips(media_pool, video_clip_infos, timestamp)

    if not new_timeline:
        print("  ERROR: Could not create new timeline. Aborting to prevent duplication.")
        print("  Please manually create a new empty timeline and run Switch Branch again.")
        return

    # Phase 3: Set new timeline as current (needed for AppendToTimeline)
    project.SetCurrentTimeline(new_timeline)
    switched = _wait_for_current_timeline(project, new_timeline)

    # Phase 4: Apply metadata, remaining video clips, audio, color, markers
    _apply_metadata(new_timeline, project, metadata)

    # If CreateTimelineFromClips didn't work, fall back to AppendToTimeline
    # but ONLY if we confirmed the timeline switch
    if video_clip_infos and not created_with_first:
        if switched:
            _apply_video_tracks(new_timeline, media_pool, video_tracks, manifest)
        else:
            print("  ERROR: Could not confirm timeline switch. "
                  "Skipping video clips to prevent duplication.")

    # If the first clip was created atomically, append the remaining ones.
    if created_with_first and remaining_clip_infos and switched:
        for clip_info in remaining_clip_infos:
            media_pool.AppendToTimeline([clip_info])
    elif created_with_first and remaining_clip_infos:
        print("  ERROR: Could not confirm timeline switch. "
              "Skipping remaining video clips to prevent duplication.")

    # Audio handling: When video+audio media is added (via CreateTimelineFromClips
    # OR AppendToTimeline), Resolve auto-creates linked audio clips. Calling
    # AppendToTimeline again with the SAME media creates duplicate video clips.
    # So in BOTH paths:
    #   - Apply volume/pan to linked audio that already exists
    #   - Only AppendToTimeline for standalone audio (media not in video tracks)
    video_refs = {
        item.media_ref
        for track in video_tracks
        for item in track.items
        if not item.is_generator
    }
    if audio_tracks:
        if video_clip_infos:
            # Video clips were added (either atomically or via fallback) —
            # linked audio already exists for shared media refs
            _apply_audio_properties_only(new_timeline, audio_tracks)
            if switched:
                _apply_audio_tracks(
                    new_timeline, media_pool, audio_tracks, manifest,
                    skip_media_refs=video_refs,
                )
        elif switched:
            _apply_audio_tracks(new_timeline, media_pool, audio_tracks, manifest)
        else:
            print("  Warning: Skipping audio tracks — could not confirm timeline switch.")

    _apply_generators(new_timeline, video_tracks, project_dir, media_pool)
    _apply_video_speed(new_timeline, video_tracks)
    _apply_audio_speed(new_timeline, audio_tracks)
    _apply_extended_video_properties(new_timeline, video_tracks)
    _apply_color(new_timeline, color_grades, project_dir, resolve_app=resolve_app)
    _apply_markers(new_timeline, markers)

    # Phase 5: Rename (AFTER all population is done)
    try:
        timeline.SetName(f"{old_name}.giteo-old.{timestamp}")
    except (AttributeError, TypeError):
        pass
    try:
        new_timeline.SetName(old_name)
    except (AttributeError, TypeError):
        pass

    print(f"  Restored timeline '{metadata.timeline_name}' from giteo snapshot")


def restore_timeline_overlays(timeline, project_dir: str, resolve_app=None) -> None:
    """Apply color grades and markers onto the current timeline without rebuilding clips."""
    color_grades = _load_color(project_dir)
    markers = _load_markers(project_dir)

    _apply_color(timeline, color_grades, project_dir, resolve_app=resolve_app)
    _clear_markers(timeline)
    _apply_markers(timeline, markers)

    print("  Restored timeline overlays from giteo snapshot")
