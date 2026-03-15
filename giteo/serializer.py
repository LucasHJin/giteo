"""Serialize DaVinci Resolve timeline → domain-split JSON.

Uses the Resolve Python API. The `resolve` object is injected by DaVinci Resolve
when scripts run from Workspace > Scripts menu.
"""

import hashlib
import os
import time
from typing import Dict, List, Optional, Tuple

from .json_writer import write_timeline
from .models import (
    Asset,
    AudioItem,
    AudioTrack,
    ColorGrade,
    ColorNodeGrade,
    Marker,
    SpeedChange,
    TextProperties,
    Timeline,
    TimelineMetadata,
    Transform,
    VideoItem,
    VideoTrack,
)


def _compute_media_hash(filepath: str) -> str:
    """Compute SHA-256 hash of a media file for the asset manifest."""
    sha = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha.update(chunk)
        return f"sha256:{sha.hexdigest()[:12]}"
    except (OSError, IOError):
        # File may not be accessible — use path-based fallback
        return f"sha256:{hashlib.sha256(filepath.encode()).hexdigest()[:12]}"


def _safe_float(clip, prop: str, default: float = 0.0) -> float:
    try:
        val = clip.GetProperty(prop)
        return float(val) if val is not None else default
    except (AttributeError, TypeError, ValueError):
        return default


def _safe_bool(clip, prop: str, default: bool = False) -> bool:
    try:
        val = clip.GetProperty(prop)
        return bool(val) if val is not None else default
    except (AttributeError, TypeError, ValueError):
        return default


def _safe_int(clip, prop: str, default: int = 0) -> int:
    try:
        val = clip.GetProperty(prop)
        return int(val) if val is not None else default
    except (AttributeError, TypeError, ValueError):
        return default


def _get_clip_transform(clip) -> Transform:
    """Extract transform properties from a Resolve timeline item."""
    try:
        return Transform(
            pan=_safe_float(clip, "Pan", 0.0),
            tilt=_safe_float(clip, "Tilt", 0.0),
            zoom_x=_safe_float(clip, "ZoomX", 1.0),
            zoom_y=_safe_float(clip, "ZoomY", 1.0),
            opacity=_safe_float(clip, "Opacity", 100.0),
            rotation_angle=_safe_float(clip, "RotationAngle", 0.0),
            anchor_x=_safe_float(clip, "AnchorPointX", 0.0),
            anchor_y=_safe_float(clip, "AnchorPointY", 0.0),
            pitch=_safe_float(clip, "Pitch", 0.0),
            yaw=_safe_float(clip, "Yaw", 0.0),
            flip_x=_safe_bool(clip, "FlipX", False),
            flip_y=_safe_bool(clip, "FlipY", False),
            crop_left=_safe_float(clip, "CropLeft", 0.0),
            crop_right=_safe_float(clip, "CropRight", 0.0),
            crop_top=_safe_float(clip, "CropTop", 0.0),
            crop_bottom=_safe_float(clip, "CropBottom", 0.0),
            crop_softness=_safe_float(clip, "CropSoftness", 0.0),
            crop_retain=_safe_bool(clip, "CropRetain", False),
            distortion=_safe_float(clip, "Distortion", 0.0),
        )
    except (AttributeError, TypeError):
        return Transform()


def _get_clip_speed(clip) -> SpeedChange:
    """Extract speed/retime properties from a Resolve timeline item.

    Resolve exposes constant speed via GetProperty("Speed") as a percentage
    (100.0 = normal). Variable speed ramps are NOT accessible via the API.
    """
    speed_pct = 100.0
    retime_process = 0
    motion_est = 0

    try:
        val = clip.GetProperty("Speed")
        if val is not None:
            speed_pct = float(val)
    except (AttributeError, TypeError, ValueError):
        pass

    try:
        val = clip.GetProperty("RetimeProcess")
        if val is not None:
            retime_process = int(val)
    except (AttributeError, TypeError, ValueError):
        pass

    try:
        val = clip.GetProperty("MotionEstimation")
        if val is not None:
            motion_est = int(val)
    except (AttributeError, TypeError, ValueError):
        pass

    return SpeedChange(
        speed_percent=speed_pct,
        retime_process=retime_process,
        motion_estimation=motion_est,
    )


def _get_clip_enabled(clip) -> bool:
    """Read clip enabled state (v20+). Falls back to True for older versions."""
    try:
        val = clip.GetClipEnabled()
        return bool(val) if val is not None else True
    except (AttributeError, TypeError):
        return True


def _is_generator_clip(clip) -> bool:
    """Detect whether a Resolve timeline item is a generator/title (Text+, etc.).

    Generators have no backing media file — GetMediaPoolItem() returns None
    or the pool item has no File Path. They also have Fusion compositions.
    """
    pool_item = clip.GetMediaPoolItem()
    if pool_item is None:
        return True
    try:
        file_path = pool_item.GetClipProperty("File Path") or ""
        if not file_path:
            return True
    except (AttributeError, TypeError):
        return True
    return False


def _detect_generator_type(clip) -> str:
    """Determine the generator name (e.g. 'Text+', 'Solid Color').

    Uses the clip name as the generator identifier, which Resolve sets
    to the generator type by default.
    """
    name = clip.GetName() or ""
    # Common Resolve generator/title names
    title_names = {"Text+", "Text", "Text3D", "Scroll", "Fusion Title"}
    if name in title_names or "text" in name.lower():
        return name or "Text+"
    return name or "Text+"


def _detect_item_type(clip) -> str:
    """Classify a generator clip as 'title' or 'generator'."""
    name = (clip.GetName() or "").lower()
    title_keywords = {"text", "title", "scroll", "subtitle", "lower third"}
    if any(kw in name for kw in title_keywords):
        return "title"
    return "generator"


def _extract_text_properties(clip) -> Optional[TextProperties]:
    """Read text properties from a generator clip's Fusion composition."""
    try:
        comp_count = clip.GetFusionCompCount()
        if not comp_count or comp_count < 1:
            return None
        comp = clip.GetFusionCompByIndex(1)
        if not comp:
            return None

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
            return None

        styled_text = ""
        font = ""
        size = 0.0
        bold = False
        italic = False
        color = None

        try:
            styled_text = str(text_tool.GetInput("StyledText") or "")
        except (AttributeError, TypeError):
            pass
        try:
            font = str(text_tool.GetInput("Font") or "")
        except (AttributeError, TypeError):
            pass
        try:
            val = text_tool.GetInput("Size")
            if val is not None:
                size = float(val)
        except (AttributeError, TypeError, ValueError):
            pass
        try:
            bold = bool(text_tool.GetInput("Bold"))
        except (AttributeError, TypeError):
            pass
        try:
            italic = bool(text_tool.GetInput("Italic"))
        except (AttributeError, TypeError):
            pass
        try:
            r = float(text_tool.GetInput("Red1") or 1.0)
            g = float(text_tool.GetInput("Green1") or 1.0)
            b = float(text_tool.GetInput("Blue1") or 1.0)
            if not (r == 1.0 and g == 1.0 and b == 1.0):
                color = {"r": round(r, 4), "g": round(g, 4), "b": round(b, 4)}
        except (AttributeError, TypeError, ValueError):
            pass

        if styled_text or font or size > 0:
            return TextProperties(
                styled_text=styled_text,
                font=font,
                size=size,
                bold=bold,
                italic=italic,
                color=color,
            )
    except (AttributeError, TypeError):
        pass
    return None


def _export_fusion_comp(clip, item_id: str, project_dir: str) -> str:
    """Export the Fusion composition for a generator clip.

    Returns the comp filename (relative to timeline/generators/), or ""
    if export failed.
    """
    generators_dir = os.path.join(project_dir, "timeline", "generators")
    os.makedirs(generators_dir, exist_ok=True)
    comp_filename = f"{item_id}.comp"
    comp_path = os.path.join(generators_dir, comp_filename)

    try:
        comp_count = clip.GetFusionCompCount()
        if not comp_count or comp_count < 1:
            return ""
        comp = clip.GetFusionCompByIndex(1)
        if not comp:
            return ""
        # ExportFusionComp writes the comp to disk
        result = clip.ExportFusionComp(comp_path, 1)
        if result:
            return comp_filename
    except (AttributeError, TypeError):
        pass
    return ""


def _serialize_video_tracks(timeline, project_dir: str = "") -> Tuple[List[VideoTrack], Dict[str, Asset]]:
    """Extract video tracks and build asset manifest."""
    video_tracks = []
    assets = {}
    track_count = timeline.GetTrackCount("video")

    for track_idx in range(1, track_count + 1):
        items = []
        clips = timeline.GetItemListInTrack("video", track_idx)
        if not clips:
            video_tracks.append(VideoTrack(index=track_idx))
            continue

        for i, clip in enumerate(clips):
            item_id = f"item_{track_idx:03d}_{i:03d}"
            clip_name = clip.GetName() or f"clip_{track_idx}_{i}"

            if _is_generator_clip(clip):
                # Generator/title clip (Text+, Solid Color, etc.)
                item_type = _detect_item_type(clip)
                generator_name = _detect_generator_type(clip)
                media_ref = f"generator:{item_id}"
                text_props = _extract_text_properties(clip)
                fusion_comp_file = _export_fusion_comp(
                    clip, item_id, project_dir
                ) if project_dir else ""

                video_item = VideoItem(
                    id=item_id,
                    name=clip_name,
                    media_ref=media_ref,
                    record_start_frame=int(clip.GetStart()),
                    record_end_frame=int(clip.GetEnd()),
                    source_start_frame=int(clip.GetLeftOffset()),
                    source_end_frame=int(clip.GetLeftOffset()) + int(clip.GetDuration()),
                    track_index=track_idx,
                    transform=_get_clip_transform(clip),
                    speed=_get_clip_speed(clip),
                    composite_mode=_safe_int(clip, "CompositeMode", 0),
                    dynamic_zoom_ease=_safe_int(clip, "DynamicZoomEase", 0),
                    clip_enabled=_get_clip_enabled(clip),
                    item_type=item_type,
                    generator_name=generator_name,
                    fusion_comp_file=fusion_comp_file,
                    text_properties=text_props,
                )
            else:
                # Regular media clip
                media_pool_item = clip.GetMediaPoolItem()
                media_path = ""
                if media_pool_item:
                    media_path = media_pool_item.GetClipProperty("File Path") or ""
                media_ref = _compute_media_hash(media_path) if media_path else f"sha256:unknown_{i}"

                # Register asset
                if media_path and media_ref not in assets:
                    duration = int(media_pool_item.GetClipProperty("Frames") or 0) if media_pool_item else 0
                    codec = (media_pool_item.GetClipProperty("Video Codec") or "unknown") if media_pool_item else "unknown"
                    res = (media_pool_item.GetClipProperty("Resolution") or "unknown") if media_pool_item else "unknown"
                    assets[media_ref] = Asset(
                        filename=os.path.basename(media_path),
                        original_path=media_path,
                        duration_frames=duration,
                        codec=codec,
                        resolution=res,
                    )

                video_item = VideoItem(
                    id=item_id,
                    name=clip_name,
                    media_ref=media_ref,
                    record_start_frame=int(clip.GetStart()),
                    record_end_frame=int(clip.GetEnd()),
                    source_start_frame=int(clip.GetLeftOffset()),
                    source_end_frame=int(clip.GetLeftOffset()) + int(clip.GetDuration()),
                    track_index=track_idx,
                    transform=_get_clip_transform(clip),
                    speed=_get_clip_speed(clip),
                    composite_mode=_safe_int(clip, "CompositeMode", 0),
                    dynamic_zoom_ease=_safe_int(clip, "DynamicZoomEase", 0),
                    clip_enabled=_get_clip_enabled(clip),
                )

            items.append(video_item)

        video_tracks.append(VideoTrack(index=track_idx, items=items))

    return video_tracks, assets


def _serialize_audio_tracks(timeline) -> List[AudioTrack]:
    """Extract audio tracks from Resolve timeline."""
    audio_tracks = []
    track_count = timeline.GetTrackCount("audio")

    for track_idx in range(1, track_count + 1):
        items = []
        clips = timeline.GetItemListInTrack("audio", track_idx)
        if not clips:
            audio_tracks.append(AudioTrack(index=track_idx))
            continue

        for i, clip in enumerate(clips):
            media_pool_item = clip.GetMediaPoolItem()
            media_path = ""
            if media_pool_item:
                media_path = media_pool_item.GetClipProperty("File Path") or ""
            media_ref = _compute_media_hash(media_path) if media_path else f"sha256:unknown_a{i}"

            audio_item = AudioItem(
                id=f"audio_{track_idx:03d}_{i:03d}",
                media_ref=media_ref,
                start_frame=int(clip.GetStart()),
                end_frame=int(clip.GetEnd()),
                volume=float(clip.GetProperty("Volume") or 0.0),
                pan=float(clip.GetProperty("Pan") or 0.0),
                speed=_get_clip_speed(clip),
            )
            items.append(audio_item)

        audio_tracks.append(AudioTrack(index=track_idx, items=items))

    return audio_tracks


def _frame_to_tc(frame: int, start_frame: int, start_tc: str, fps: float) -> str:
    """Convert absolute timeline frame to a timecode string."""
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


def _read_color_adjustments(clip) -> dict:
    """Read clip-level color adjustments via GetProperty().

    NOTE: On Resolve Free, GetProperty() for color properties (Contrast,
    Saturation, etc.) returns None. These values are only readable on
    Resolve Studio. The function still tries in case the user has Studio.
    """
    adjustments = {}

    props = {
        "contrast": "Contrast",
        "saturation": "Saturation",
        "hue": "Hue",
        "pivot": "Pivot",
        "color_boost": "ColorBoost",
    }

    for adj_key, prop_name in props.items():
        try:
            val = clip.GetProperty(prop_name)
            if val is not None:
                fval = float(val)
                adjustments[adj_key] = round(fval, 6)
        except (AttributeError, TypeError, ValueError):
            continue

    return adjustments


def _read_clip_grade_info(clip) -> Tuple[int, List[ColorNodeGrade], str]:
    """Read color grade info from a Resolve clip.

    Captures what the scripting API exposes (read-only access is limited):
    - Node count and structure via GetNumNodes() / GetNodeGraph()
    - Node labels and LUT paths via NodeGraph.GetNodeLabel/GetLUT
    - Tool names per node via NodeGraph.GetToolsInNode (change detection)
    - Clip-level adjustments via GetProperty (Studio only)
    - Full grade via DRX still export (Studio only, in _export_grade_stills)
    """
    num_nodes = 1
    nodes: List[ColorNodeGrade] = []
    version_name = ""
    node_graph = None

    # Prefer NodeGraph API (available in Resolve 18+)
    try:
        node_graph = clip.GetNodeGraph()
        if node_graph:
            n = node_graph.GetNumNodes()
            if n:
                num_nodes = int(n)
    except (AttributeError, TypeError):
        pass

    # Fallback to clip-level GetNumNodes
    if num_nodes <= 1 and not node_graph:
        try:
            n = clip.GetNumNodes()
            if n:
                num_nodes = int(n)
        except (AttributeError, TypeError):
            pass

    # Read clip-level color adjustments via GetProperty()
    clip_adjustments = _read_color_adjustments(clip)

    for node_idx in range(1, num_nodes + 1):
        label = ""
        lut = ""
        tools = []

        # Read from NodeGraph API first (more reliable)
        if node_graph:
            try:
                label = node_graph.GetNodeLabel(node_idx) or ""
            except (AttributeError, TypeError):
                pass
            try:
                lut = node_graph.GetLUT(node_idx) or ""
            except (AttributeError, TypeError):
                pass
            try:
                t = node_graph.GetToolsInNode(node_idx)
                if t and isinstance(t, list):
                    tools = t
            except (AttributeError, TypeError):
                pass
        else:
            # Fallback to clip-level APIs
            try:
                label = clip.GetNodeLabel(node_idx) or ""
            except (AttributeError, TypeError):
                pass
            try:
                lut = clip.GetLUT(node_idx) or ""
            except (AttributeError, TypeError):
                pass

        node = ColorNodeGrade(index=node_idx, label=label, lut=lut,
                              tools=tools if tools else None)

        # Clip-level adjustments go on the first node
        if node_idx == 1 and clip_adjustments:
            node.contrast = clip_adjustments.get("contrast")
            node.saturation = clip_adjustments.get("saturation")
            node.pivot = clip_adjustments.get("pivot")
            node.hue = clip_adjustments.get("hue")
            node.color_boost = clip_adjustments.get("color_boost")

        nodes.append(node)

    try:
        ver = clip.GetCurrentVersion()
        if ver and isinstance(ver, dict):
            version_name = ver.get("versionName", "")
    except (AttributeError, TypeError):
        pass

    return num_nodes, nodes, version_name


def _export_grade_stills(timeline, project, project_dir: str,
                         grades: Dict[str, ColorGrade],
                         resolve_app=None) -> None:
    """Export DRX grade stills for each clip.

    DRX (DaVinci Resolve eXchange) files contain the complete color grade:
    all nodes, CDL values, curves, qualifiers, power windows, etc.
    Git tracks them as binary — any color change = different file = detected.

    NOTE: ExportStills requires DaVinci Resolve Studio. On the Free edition
    the method exists but always returns False. When that happens we fall
    back to the metadata-only color capture (node structure, LUTs, clip
    adjustments) which is handled by _serialize_color.
    """
    grades_dir = os.path.join(project_dir, "timeline", "grades")
    os.makedirs(grades_dir, exist_ok=True)

    # Remove old DRX files — Resolve appends version suffixes (e.g. _1.1.1)
    # so stale exports accumulate as untracked files and block merges
    for f in os.listdir(grades_dir):
        if f.endswith(".drx"):
            try:
                os.remove(os.path.join(grades_dir, f))
            except OSError:
                pass

    gallery = None
    album = None
    try:
        gallery = project.GetGallery()
        if gallery:
            album = gallery.GetCurrentStillAlbum()
    except (AttributeError, TypeError):
        pass

    if not album:
        return

    fps = float(timeline.GetSetting("timelineFrameRate") or 24)
    start_frame = timeline.GetStartFrame()
    start_tc = timeline.GetStartTimecode() or "01:00:00:00"

    saved_page = None
    if resolve_app:
        try:
            saved_page = resolve_app.GetCurrentPage()
            resolve_app.OpenPage("color")
            time.sleep(0.3)
        except (AttributeError, TypeError):
            pass

    drx_export_works = None  # tri-state: None=untested, True/False

    track_count = timeline.GetTrackCount("video")

    for track_idx in range(1, track_count + 1):
        clips = timeline.GetItemListInTrack("video", track_idx)
        if not clips:
            continue

        for i, clip in enumerate(clips):
            if drx_export_works is False:
                break  # skip remaining clips once we know it's broken

            item_id = f"item_{track_idx:03d}_{i:03d}"
            try:
                clip_start = clip.GetStart()
                tc = _frame_to_tc(clip_start + 1, start_frame, start_tc, fps)

                timeline.SetCurrentTimecode(tc)
                time.sleep(0.15)

                # Retry loop — SetCurrentTimecode can be unreliable
                for _ in range(3):
                    current = timeline.GetCurrentTimecode()
                    if current == tc:
                        break
                    timeline.SetCurrentTimecode(tc)
                    time.sleep(0.15)

                still = timeline.GrabStill()
                if not still:
                    continue

                time.sleep(0.1)
                drx_name = item_id
                success = album.ExportStills([still], grades_dir, drx_name, "drx")

                if success:
                    exported = [f for f in os.listdir(grades_dir)
                                if f.startswith(drx_name) and f.endswith(".drx")]
                    if exported:
                        grades[item_id].drx_file = exported[0]
                    else:
                        grades[item_id].drx_file = f"{drx_name}.drx"
                    if drx_export_works is None:
                        drx_export_works = True
                else:
                    if drx_export_works is None:
                        # First failure — ExportStills is not available
                        drx_export_works = False
                        print("  Note: DRX export unavailable (Resolve Studio required).")
                        print("  Color tracked via node structure and clip properties.")

                try:
                    album.DeleteStills([still])
                except (AttributeError, TypeError):
                    pass

            except Exception:
                pass

    if saved_page and resolve_app:
        try:
            resolve_app.OpenPage(saved_page)
        except (AttributeError, TypeError):
            pass


def _serialize_color(timeline, video_tracks: List[VideoTrack],
                     project=None, project_dir: str = "",
                     resolve_app=None) -> Dict[str, ColorGrade]:
    """Extract color grading data per clip.

    The Resolve API is mostly write-only for color, so we capture what we can:
      1. Clip-level adjustments (contrast, saturation, hue) via GetProperty()
      2. Node structure (count, labels) via undocumented but working APIs
      3. DRX grade stills for full-fidelity binary backup (the only way to
         capture complete grades including CDL, curves, qualifiers, etc.)
    """
    grades = {}
    track_count = timeline.GetTrackCount("video")

    for track_idx in range(1, track_count + 1):
        clips = timeline.GetItemListInTrack("video", track_idx)
        if not clips:
            continue

        for i, clip in enumerate(clips):
            item_id = f"item_{track_idx:03d}_{i:03d}"
            num_nodes, nodes, version_name = _read_clip_grade_info(clip)
            grades[item_id] = ColorGrade(
                num_nodes=num_nodes,
                nodes=nodes,
                version_name=version_name,
            )

    if project and project_dir:
        _export_grade_stills(timeline, project, project_dir, grades, resolve_app)

    return grades


def _serialize_markers(timeline) -> List[Marker]:
    """Extract timeline markers."""
    markers = []
    marker_dict = timeline.GetMarkers()
    if not marker_dict:
        return markers

    for frame, info in sorted(marker_dict.items()):
        markers.append(Marker(
            frame=int(frame),
            color=info.get("color", "Blue"),
            name=info.get("name", ""),
            note=info.get("note", ""),
            duration=int(info.get("duration", 1)),
        ))

    return markers


def _serialize_metadata(timeline, project) -> TimelineMetadata:
    """Extract timeline metadata."""
    setting = timeline.GetSetting
    return TimelineMetadata(
        project_name=project.GetName() or "",
        timeline_name=timeline.GetName() or "",
        frame_rate=float(setting("timelineFrameRate") or 24.0),
        width=int(setting("timelineResolutionWidth") or 1920),
        height=int(setting("timelineResolutionHeight") or 1080),
        start_timecode=timeline.GetStartTimecode() or "01:00:00:00",
        video_track_count=timeline.GetTrackCount("video"),
        audio_track_count=timeline.GetTrackCount("audio"),
    )


def serialize_timeline(timeline, project, project_dir: str,
                       resolve_app=None) -> Timeline:
    """Serialize a DaVinci Resolve timeline into domain-split JSON files.

    Args:
        timeline: Resolve Timeline object (from resolve API)
        project: Resolve Project object
        project_dir: Path to the giteo project directory
        resolve_app: Optional Resolve application object (for page switching
                     during DRX grade export). Pass the `resolve` global.

    Returns:
        Timeline dataclass with all extracted data
    """
    video_tracks, assets = _serialize_video_tracks(timeline, project_dir)
    audio_tracks = _serialize_audio_tracks(timeline)
    color_grades = _serialize_color(timeline, video_tracks, project,
                                    project_dir, resolve_app)
    markers = _serialize_markers(timeline)
    metadata = _serialize_metadata(timeline, project)

    tl = Timeline(
        metadata=metadata,
        video_tracks=video_tracks,
        audio_tracks=audio_tracks,
        color_grades=color_grades,
        effects={},
        markers=markers,
        assets=assets,
    )

    write_timeline(project_dir, tl)
    return tl
