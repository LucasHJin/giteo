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


def _get_clip_transform(clip) -> Transform:
    """Extract transform properties from a Resolve timeline item."""
    try:
        return Transform(
            pan=float(clip.GetProperty("Pan") or 0.0),
            tilt=float(clip.GetProperty("Tilt") or 0.0),
            zoom_x=float(clip.GetProperty("ZoomX") or 1.0),
            zoom_y=float(clip.GetProperty("ZoomY") or 1.0),
            opacity=float(clip.GetProperty("Opacity") or 100.0),
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


def _serialize_video_tracks(timeline) -> Tuple[List[VideoTrack], Dict[str, Asset]]:
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
            media_pool_item = clip.GetMediaPoolItem()
            clip_name = clip.GetName() or f"clip_{track_idx}_{i}"

            # Build media reference
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

            item_id = f"item_{track_idx:03d}_{i:03d}"

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

    The Resolve scripting API is write-only for per-node color data
    (SetCDL exists but GetCDL does not, SetLUT exists but GetLUT does not).

    However, clip-level properties like Contrast and Saturation may be
    readable via GetProperty() — this is not officially documented but
    works in some Resolve versions.
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

    The Resolve scripting API is largely write-only for color:
    - SetCDL() exists but GetCDL() does NOT
    - SetLUT() exists but GetLUT() does NOT
    - GetNumNodes() / GetNodeLabel() are undocumented but may work

    What we CAN read:
    1. Node count & labels (undocumented, try with fallback)
    2. Clip-level properties like Contrast/Saturation via GetProperty()
    3. Full grade via DRX still export (handled separately in _export_grade_stills)
    """
    num_nodes = 1
    nodes: List[ColorNodeGrade] = []
    version_name = ""

    # GetNumNodes() is undocumented but works in many Resolve versions
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
        # GetNodeLabel() is undocumented but may work
        try:
            label = clip.GetNodeLabel(node_idx) or ""
        except (AttributeError, TypeError):
            pass
        # GetLUT() is NOT in the official API — try anyway
        try:
            lut = clip.GetLUT(node_idx) or ""
        except (AttributeError, TypeError):
            pass

        node = ColorNodeGrade(index=node_idx, label=label, lut=lut)

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
        print("  Warning: Could not access Gallery — DRX grade export skipped.")
        print("  (Color grades will be tracked by node structure only.)")
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

    track_count = timeline.GetTrackCount("video")

    for track_idx in range(1, track_count + 1):
        clips = timeline.GetItemListInTrack("video", track_idx)
        if not clips:
            continue

        for i, clip in enumerate(clips):
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
                    print(f"  Warning: GrabStill returned None for {item_id}")
                    continue

                time.sleep(0.1)
                drx_name = item_id
                success = album.ExportStills([still], grades_dir, drx_name, "drx")

                if success:
                    # Find the exported file (Resolve may add suffixes)
                    exported = [f for f in os.listdir(grades_dir)
                                if f.startswith(drx_name) and f.endswith(".drx")]
                    if exported:
                        grades[item_id].drx_file = exported[0]
                    else:
                        grades[item_id].drx_file = f"{drx_name}.drx"
                else:
                    print(f"  Warning: ExportStills failed for {item_id}")

                try:
                    album.DeleteStills([still])
                except (AttributeError, TypeError):
                    pass

            except Exception as e:
                print(f"  Warning: DRX export failed for {item_id}: {e}")

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
    video_tracks, assets = _serialize_video_tracks(timeline)
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
