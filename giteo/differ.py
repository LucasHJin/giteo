"""Human-readable diff formatting for timeline changes."""

import json
import os
from typing import Dict, List, Optional, Tuple

from .json_writer import read_json


def _frames_to_timecode(frames: int, fps: float = 24.0) -> str:
    """Convert frame number to HH:MM:SS:FF timecode."""
    total_frames = int(frames)
    ff = total_frames % int(fps)
    total_seconds = total_frames // int(fps)
    ss = total_seconds % 60
    total_minutes = total_seconds // 60
    mm = total_minutes % 60
    hh = total_minutes // 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


def _frames_to_duration(frames: int, fps: float = 24.0) -> str:
    """Convert frame count to human-readable duration."""
    seconds = frames / fps
    if seconds < 1:
        return f"{int(frames)}f"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}m{secs:.0f}s"


def diff_cuts(old: dict, new: dict, fps: float = 24.0) -> List[str]:
    """Diff cuts.json and return human-readable lines."""
    lines = []

    old_items = {}
    for track in old.get("video_tracks", []):
        for item in track.get("items", []):
            old_items[item["id"]] = item

    new_items = {}
    for track in new.get("video_tracks", []):
        for item in track.get("items", []):
            new_items[item["id"]] = item

    # Added clips
    for item_id, item in new_items.items():
        if item_id not in old_items:
            tc = _frames_to_timecode(item["record_start_frame"], fps)
            dur = _frames_to_duration(
                item["record_end_frame"] - item["record_start_frame"], fps
            )
            lines.append(
                f"  + Added clip '{item['name']}' on V{item['track_index']} at {tc} ({dur})"
            )

    # Removed clips
    for item_id, item in old_items.items():
        if item_id not in new_items:
            lines.append(
                f"  - Removed clip '{item['name']}' from V{item['track_index']}"
            )

    # Modified clips
    for item_id in new_items:
        if item_id not in old_items:
            continue
        old_item = old_items[item_id]
        new_item = new_items[item_id]

        # Check trim changes
        if old_item["record_start_frame"] != new_item["record_start_frame"]:
            old_tc = _frames_to_timecode(old_item["record_start_frame"], fps)
            new_tc = _frames_to_timecode(new_item["record_start_frame"], fps)
            lines.append(
                f"  ~ Trimmed '{new_item['name']}' start: {old_tc} → {new_tc}"
            )
        if old_item["record_end_frame"] != new_item["record_end_frame"]:
            old_tc = _frames_to_timecode(old_item["record_end_frame"], fps)
            new_tc = _frames_to_timecode(new_item["record_end_frame"], fps)
            lines.append(
                f"  ~ Trimmed '{new_item['name']}' end: {old_tc} → {new_tc}"
            )

        # Check track move
        if old_item["track_index"] != new_item["track_index"]:
            lines.append(
                f"  ~ Moved '{new_item['name']}' from V{old_item['track_index']} to V{new_item['track_index']}"
            )

        # Check transform changes
        old_t = old_item.get("transform", {})
        new_t = new_item.get("transform", {})
        for key in ["Pan", "Tilt", "ZoomX", "ZoomY", "Opacity"]:
            old_v = old_t.get(key, 0)
            new_v = new_t.get(key, 0)
            if old_v != new_v:
                lines.append(
                    f"  ~ clip '{new_item['name']}': {key} {old_v} → {new_v}"
                )

    return lines


def _format_rgb(vals: list) -> str:
    """Format RGB list as readable string."""
    if not vals or len(vals) != 3:
        return str(vals)
    return f"R:{vals[0]:.3f} G:{vals[1]:.3f} B:{vals[2]:.3f}"


def _format_wheel(wheel: dict) -> str:
    """Format a color wheel dict as readable string."""
    if not wheel:
        return str(wheel)
    parts = []
    for ch in ["r", "g", "b", "y"]:
        if ch in wheel:
            label = {"r": "R", "g": "G", "b": "B", "y": "Y"}[ch]
            parts.append(f"{label}:{wheel[ch]:.3f}")
    return " ".join(parts)


def _diff_node_values(old_node: dict, new_node: dict, item_id: str, node_idx: int) -> List[str]:
    """Diff color values within a single node."""
    lines = []
    prefix = f"  ~ clip '{item_id}' node {node_idx}"

    # CDL values
    for key, label in [("slope", "Slope"), ("offset", "Offset"), ("power", "Power")]:
        old_v = old_node.get(key)
        new_v = new_node.get(key)
        if old_v != new_v:
            old_s = _format_rgb(old_v) if old_v else "default"
            new_s = _format_rgb(new_v) if new_v else "default"
            lines.append(f"{prefix}: {label} {old_s} → {new_s}")

    # Scalar values
    for key, label in [("saturation", "Saturation"), ("contrast", "Contrast"),
                        ("pivot", "Pivot"), ("hue", "Hue"), ("color_boost", "Color Boost")]:
        old_v = old_node.get(key)
        new_v = new_node.get(key)
        if old_v != new_v and (old_v is not None or new_v is not None):
            old_s = f"{old_v:.3f}" if old_v is not None else "default"
            new_s = f"{new_v:.3f}" if new_v is not None else "default"
            lines.append(f"{prefix}: {label} {old_s} → {new_s}")

    # Color wheels
    for key, label in [("lift", "Lift"), ("gamma", "Gamma"),
                        ("gain", "Gain"), ("color_offset", "Offset")]:
        old_v = old_node.get(key)
        new_v = new_node.get(key)
        if old_v != new_v and (old_v is not None or new_v is not None):
            old_s = _format_wheel(old_v) if old_v else "default"
            new_s = _format_wheel(new_v) if new_v else "default"
            lines.append(f"{prefix}: {label} {old_s} → {new_s}")

    # LUT changes
    old_lut = old_node.get("lut", "")
    new_lut = new_node.get("lut", "")
    if old_lut != new_lut:
        lines.append(f"{prefix}: LUT '{old_lut or 'none'}' → '{new_lut or 'none'}'")

    return lines


def diff_color(old: dict, new: dict) -> List[str]:
    """Diff color.json and return human-readable lines."""
    lines = []
    old_grades = old.get("grades", {})
    new_grades = new.get("grades", {})

    for item_id in sorted(new_grades):
        if item_id not in old_grades:
            lines.append(f"  + Added color grade for clip '{item_id}'")
            # Show what was added
            new_g = new_grades[item_id]
            for node in new_g.get("nodes", []):
                for key, label in [("slope", "Slope"), ("saturation", "Saturation"),
                                    ("contrast", "Contrast"), ("hue", "Hue")]:
                    val = node.get(key)
                    if val is not None:
                        if isinstance(val, list):
                            lines.append(f"    {label}: {_format_rgb(val)}")
                        else:
                            lines.append(f"    {label}: {val:.3f}")
            continue

        old_g = old_grades[item_id]
        new_g = new_grades[item_id]

        for key in ["num_nodes", "version_name", "drx_file"]:
            old_v = old_g.get(key)
            new_v = new_g.get(key)
            if old_v != new_v:
                lines.append(f"  ~ clip '{item_id}': {key} {old_v} → {new_v}")

        old_nodes = old_g.get("nodes", [])
        new_nodes = new_g.get("nodes", [])

        # Diff nodes pairwise
        max_nodes = max(len(old_nodes), len(new_nodes))
        for idx in range(max_nodes):
            if idx >= len(old_nodes):
                lines.append(f"  + clip '{item_id}': added node {idx + 1}")
                continue
            if idx >= len(new_nodes):
                lines.append(f"  - clip '{item_id}': removed node {idx + 1}")
                continue
            node_lines = _diff_node_values(old_nodes[idx], new_nodes[idx], item_id, idx + 1)
            lines.extend(node_lines)

    for item_id in sorted(old_grades):
        if item_id not in new_grades:
            lines.append(f"  - Removed color grade for clip '{item_id}'")

    return lines


def diff_audio(old: dict, new: dict, fps: float = 24.0) -> List[str]:
    """Diff audio.json and return human-readable lines."""
    lines = []

    old_items = {}
    for track in old.get("audio_tracks", []):
        for item in track.get("items", []):
            old_items[item["id"]] = item

    new_items = {}
    for track in new.get("audio_tracks", []):
        for item in track.get("items", []):
            new_items[item["id"]] = item

    for item_id, item in new_items.items():
        if item_id not in old_items:
            lines.append(f"  + Added audio clip '{item_id}'")
        else:
            old_item = old_items[item_id]
            for key in ["volume", "pan"]:
                if old_item.get(key) != item.get(key):
                    lines.append(
                        f"  ~ audio '{item_id}': {key} {old_item.get(key)} → {item.get(key)}"
                    )

    for item_id in old_items:
        if item_id not in new_items:
            lines.append(f"  - Removed audio clip '{item_id}'")

    return lines


def diff_markers(old: dict, new: dict, fps: float = 24.0) -> List[str]:
    """Diff markers.json and return human-readable lines."""
    lines = []
    old_markers = {m["frame"]: m for m in old.get("markers", [])}
    new_markers = {m["frame"]: m for m in new.get("markers", [])}

    for frame, marker in new_markers.items():
        if frame not in old_markers:
            tc = _frames_to_timecode(frame, fps)
            lines.append(f'  + Added marker at {tc}: "{marker.get("name", "")}"')
        else:
            old_m = old_markers[frame]
            if old_m != marker:
                tc = _frames_to_timecode(frame, fps)
                lines.append(f'  ~ Modified marker at {tc}: "{marker.get("name", "")}"')

    for frame in old_markers:
        if frame not in new_markers:
            tc = _frames_to_timecode(frame, fps)
            lines.append(f"  - Removed marker at {tc}")

    return lines


def diff_metadata(old: dict, new: dict) -> List[str]:
    """Diff metadata.json and return human-readable lines."""
    lines = []
    for key in ["project_name", "timeline_name", "frame_rate", "start_timecode"]:
        old_v = old.get(key)
        new_v = new.get(key)
        if old_v != new_v:
            lines.append(f"  ~ {key}: {old_v} → {new_v}")

    old_res = old.get("resolution", {})
    new_res = new.get("resolution", {})
    if old_res != new_res:
        lines.append(
            f"  ~ resolution: {old_res.get('width')}x{old_res.get('height')} → "
            f"{new_res.get('width')}x{new_res.get('height')}"
        )

    return lines


def format_diff(
    old_files: Dict[str, dict],
    new_files: Dict[str, dict],
    timeline_name: str = "",
    branch_info: str = "",
) -> str:
    """Format a complete human-readable diff across all domain files.

    Args:
        old_files: Dict of domain name → old JSON data
        new_files: Dict of domain name → new JSON data
        timeline_name: Optional timeline name for header
        branch_info: Optional branch context (e.g. "color-grade → main")

    Returns:
        Formatted diff string
    """
    fps = new_files.get("metadata", {}).get("frame_rate", 24.0)
    output_lines = []

    if timeline_name:
        output_lines.append(f"  Timeline: {timeline_name}")
    if branch_info:
        output_lines.append(f"  Branch: {branch_info}")
    if output_lines:
        output_lines.append("")

    sections = [
        ("CUTS", diff_cuts, "cuts"),
        ("COLOR", diff_color, "color"),
        ("AUDIO", diff_audio, "audio"),
        ("MARKERS", diff_markers, "markers"),
        ("METADATA", diff_metadata, "metadata"),
    ]

    has_changes = False
    for section_name, diff_fn, key in sections:
        old_data = old_files.get(key, {})
        new_data = new_files.get(key, {})
        if old_data == new_data:
            continue

        if diff_fn in (diff_cuts, diff_audio, diff_markers):
            diff_lines = diff_fn(old_data, new_data, fps)
        else:
            diff_lines = diff_fn(old_data, new_data)

        if diff_lines:
            has_changes = True
            output_lines.append(f"  {section_name}:")
            output_lines.extend(diff_lines)
            output_lines.append("")

    if not has_changes:
        output_lines.append("  No changes.")

    return "\n".join(output_lines)


def diff_from_project(project_dir: str, ref: str = "HEAD") -> str:
    """Generate a human-readable diff between current state and a git ref.

    Uses git show to get the old versions of files.
    """
    from .core import git_show_file

    domain_files = {
        "cuts": "timeline/cuts.json",
        "color": "timeline/color.json",
        "audio": "timeline/audio.json",
        "markers": "timeline/markers.json",
        "metadata": "timeline/metadata.json",
    }

    old_files = {}
    new_files = {}
    for domain, filepath in domain_files.items():
        # Old version from git
        old_content = git_show_file(project_dir, ref, filepath)
        old_files[domain] = json.loads(old_content) if old_content else {}

        # Current version from disk
        full_path = os.path.join(project_dir, filepath)
        if os.path.exists(full_path):
            with open(full_path) as f:
                new_files[domain] = json.load(f)
        else:
            new_files[domain] = {}

    metadata = new_files.get("metadata", {})
    timeline_name = metadata.get("timeline_name", "")

    return format_diff(old_files, new_files, timeline_name=timeline_name)
