"""Deserialize domain-split JSON → DaVinci Resolve timeline.

Reads the JSON files and applies the state back to a Resolve timeline.
"""

import os
import time
from typing import Dict, List

from .json_writer import read_json
from .models import (
    AudioItem,
    AudioTrack,
    ColorGrade,
    ColorNodeGrade,
    Marker,
    SpeedChange,
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


def _collect_video_clip_infos(media_pool, video_tracks: List[VideoTrack],
                              manifest: dict) -> List[dict]:
    """Collect clip info dicts for CreateTimelineFromClips.

    Uses only the documented clip info keys (mediaPoolItem, startFrame,
    endFrame) to avoid undefined behavior from undocumented parameters.
    """
    clip_infos = []
    for track in video_tracks:
        for item in track.items:
            pool_item = _find_media_pool_item(media_pool, manifest, item.media_ref)
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
    """Create a new timeline, optionally pre-populated with video clips.

    Uses CreateTimelineFromClips when clips are available — this is an atomic
    operation that avoids the SetCurrentTimeline race condition that caused
    clip duplication with the old CreateEmptyTimeline + AppendToTimeline flow.

    Falls back to CreateEmptyTimeline if CreateTimelineFromClips fails or
    there are no clips to add.
    """
    temp_name = f"giteo_temp_{timestamp}"
    new_timeline = None
    created_with_clips = False

    if clip_infos:
        try:
            new_timeline = media_pool.CreateTimelineFromClips(temp_name, clip_infos)
            if new_timeline:
                created_with_clips = True
        except (AttributeError, TypeError):
            pass

    if not new_timeline:
        new_timeline = media_pool.CreateEmptyTimeline(temp_name)

    if not new_timeline:
        for i in range(1, 5):
            alt_name = f"giteo_temp_{timestamp}_{i}"
            if clip_infos:
                try:
                    new_timeline = media_pool.CreateTimelineFromClips(alt_name, clip_infos)
                    if new_timeline:
                        created_with_clips = True
                except (AttributeError, TypeError):
                    pass
            if not new_timeline:
                new_timeline = media_pool.CreateEmptyTimeline(alt_name)
            if new_timeline:
                break

    return new_timeline, created_with_clips


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

    This is the FALLBACK path used only when CreateTimelineFromClips fails.
    The caller must ensure the timeline is confirmed as current before calling.
    """
    for track in video_tracks:
        while timeline.GetTrackCount("video") < track.index:
            timeline.AddTrack("video")

        for item in track.items:
            pool_item = _find_media_pool_item(media_pool, manifest, item.media_ref)
            if not pool_item:
                print(f"  Warning: Could not find media for '{item.name}' ({item.media_ref})")
                continue

            clip_info = {
                "mediaPoolItem": pool_item,
                "startFrame": item.source_start_frame,
                "endFrame": item.source_end_frame,
            }
            media_pool.AppendToTimeline([clip_info])


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
    """Apply speed changes to video clips already on the timeline."""
    track_count = timeline.GetTrackCount("video")
    for track in video_tracks:
        if track.index > track_count:
            continue
        clips = timeline.GetItemListInTrack("video", track.index)
        if not clips:
            continue
        for i, item in enumerate(track.items):
            if i >= len(clips):
                break
            _apply_speed(clips[i], item.speed, item.id)


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

    # Phase 1: Collect video clip infos for atomic timeline creation
    video_clip_infos = _collect_video_clip_infos(media_pool, video_tracks, manifest)

    # Phase 2: Create new timeline atomically with video clips.
    # CreateTimelineFromClips bypasses the async SetCurrentTimeline race
    # that caused clip duplication with the old approach.
    new_timeline, created_with_clips = _create_timeline_with_clips(
        media_pool, video_clip_infos, timestamp)

    if not new_timeline:
        print("  ERROR: Could not create new timeline. Aborting to prevent duplication.")
        print("  Please manually create a new empty timeline and run Switch Branch again.")
        return

    # Phase 3: Set new timeline as current (needed for audio AppendToTimeline)
    project.SetCurrentTimeline(new_timeline)
    switched = _wait_for_current_timeline(project, new_timeline)

    # Phase 4: Apply metadata, video fallback, audio, color, markers
    _apply_metadata(new_timeline, project, metadata)

    # If CreateTimelineFromClips didn't work, fall back to AppendToTimeline
    # but ONLY if we confirmed the timeline switch
    if video_clip_infos and not created_with_clips:
        if switched:
            _apply_video_tracks(new_timeline, media_pool, video_tracks, manifest)
        else:
            print("  ERROR: Could not confirm timeline switch. "
                  "Skipping video clips to prevent duplication.")

    # Audio handling depends on how video clips were added.
    # When CreateTimelineFromClips adds a video+audio file, Resolve auto-creates
    # linked audio clips. Calling AppendToTimeline again with the SAME media
    # creates duplicate video clips. So:
    #   - Apply volume/pan to linked audio that already exists
    #   - Only AppendToTimeline for standalone audio (media not in video tracks)
    if audio_tracks:
        if created_with_clips:
            _apply_audio_properties_only(new_timeline, audio_tracks)
            video_refs = {
                item.media_ref for track in video_tracks for item in track.items
            }
            if switched:
                _apply_audio_tracks(
                    new_timeline, media_pool, audio_tracks, manifest,
                    skip_media_refs=video_refs,
                )
        elif switched:
            _apply_audio_tracks(new_timeline, media_pool, audio_tracks, manifest)
        else:
            print("  Warning: Skipping audio tracks — could not confirm timeline switch.")

    _apply_video_speed(new_timeline, video_tracks)
    _apply_audio_speed(new_timeline, audio_tracks)
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
