"""Post-merge validation — detect orphaned refs, sync issues, overlapping clips."""

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Set

from .json_writer import read_json


@dataclass
class ValidationIssue:
    severity: str  # "error" or "warning"
    category: str  # "orphaned_ref", "sync", "overlap", "track_count"
    message: str
    details: dict = field(default_factory=dict)

    def __str__(self) -> str:
        icon = "ERROR" if self.severity == "error" else "WARN"
        return f"[{icon}] {self.category}: {self.message}"


def validate_project(project_dir: str) -> List[ValidationIssue]:
    """Run all validation checks on the current project state.

    Returns a list of issues found. Empty list = valid.
    """
    issues = []

    cuts = read_json(os.path.join(project_dir, "timeline", "cuts.json"))
    color = read_json(os.path.join(project_dir, "timeline", "color.json"))
    audio = read_json(os.path.join(project_dir, "timeline", "audio.json"))
    metadata = read_json(os.path.join(project_dir, "timeline", "metadata.json"))
    effects = read_json(os.path.join(project_dir, "timeline", "effects.json"))

    # Collect all video item IDs
    video_item_ids = _collect_video_item_ids(cuts)

    issues.extend(_check_orphaned_color_refs(color, video_item_ids))
    issues.extend(_check_orphaned_effect_refs(effects, video_item_ids))
    issues.extend(_check_overlapping_clips(cuts))
    issues.extend(_check_audio_video_sync(cuts, audio))
    issues.extend(_check_track_count_consistency(cuts, audio, metadata))
    issues.extend(_check_speed_duration_consistency(cuts))
    issues.extend(_check_speed_sync(cuts, audio))

    return issues


def _collect_video_item_ids(cuts: dict) -> Set[str]:
    """Get all video item IDs from cuts.json."""
    ids = set()
    for track in cuts.get("video_tracks", []):
        for item in track.get("items", []):
            item_id = item.get("id")
            if item_id:
                ids.add(item_id)
    return ids


def _check_orphaned_color_refs(color: dict, video_ids: Set[str]) -> List[ValidationIssue]:
    """Check for color grades that reference non-existent clips."""
    issues = []
    grades = color.get("grades", {})
    for item_id in grades:
        if item_id not in video_ids:
            issues.append(ValidationIssue(
                severity="error",
                category="orphaned_ref",
                message=f"Color grade references deleted clip '{item_id}'",
                details={"item_id": item_id, "domain": "color"},
            ))
    return issues


def _check_orphaned_effect_refs(effects: dict, video_ids: Set[str]) -> List[ValidationIssue]:
    """Check for effects that reference non-existent clips."""
    issues = []
    clip_effects = effects.get("clip_effects", {})
    for item_id in clip_effects:
        if item_id not in video_ids:
            issues.append(ValidationIssue(
                severity="error",
                category="orphaned_ref",
                message=f"Effect references deleted clip '{item_id}'",
                details={"item_id": item_id, "domain": "effects"},
            ))
    return issues


def _check_overlapping_clips(cuts: dict) -> List[ValidationIssue]:
    """Check for clips that overlap on the same track at the same timecode."""
    issues = []
    for track in cuts.get("video_tracks", []):
        items = track.get("items", [])
        track_idx = track.get("index", "?")

        # Sort by start frame
        sorted_items = sorted(items, key=lambda x: x.get("record_start_frame", 0))

        for i in range(len(sorted_items) - 1):
            current = sorted_items[i]
            next_item = sorted_items[i + 1]

            current_end = current.get("record_end_frame", 0)
            next_start = next_item.get("record_start_frame", 0)

            if current_end > next_start:
                issues.append(ValidationIssue(
                    severity="error",
                    category="overlap",
                    message=(
                        f"Clips overlap on V{track_idx}: "
                        f"'{current.get('name', '?')}' (ends frame {current_end}) "
                        f"overlaps '{next_item.get('name', '?')}' (starts frame {next_start})"
                    ),
                    details={
                        "track": track_idx,
                        "clip_a": current.get("id"),
                        "clip_b": next_item.get("id"),
                    },
                ))
    return issues


def _check_audio_video_sync(cuts: dict, audio: dict) -> List[ValidationIssue]:
    """Check for audio/video sync issues — linked clips should have matching boundaries."""
    issues = []

    # Build a map of video items by media_ref
    video_by_ref: Dict[str, dict] = {}
    for track in cuts.get("video_tracks", []):
        for item in track.get("items", []):
            ref = item.get("media_ref")
            if ref:
                video_by_ref[ref] = item

    # Check audio items against their video counterparts
    for track in audio.get("audio_tracks", []):
        for audio_item in track.get("items", []):
            ref = audio_item.get("media_ref")
            if not ref or ref not in video_by_ref:
                continue

            video_item = video_by_ref[ref]
            v_start = video_item.get("record_start_frame", 0)
            v_end = video_item.get("record_end_frame", 0)
            a_start = audio_item.get("start_frame", 0)
            a_end = audio_item.get("end_frame", 0)

            if v_start != a_start or v_end != a_end:
                issues.append(ValidationIssue(
                    severity="warning",
                    category="sync",
                    message=(
                        f"Audio/video sync mismatch for media '{ref}': "
                        f"video [{v_start}-{v_end}] vs audio [{a_start}-{a_end}]"
                    ),
                    details={
                        "media_ref": ref,
                        "video_item": video_item.get("id"),
                        "audio_item": audio_item.get("id"),
                    },
                ))

    return issues


def _check_track_count_consistency(cuts: dict, audio: dict, metadata: dict) -> List[ValidationIssue]:
    """Check that track counts in metadata match actual tracks."""
    issues = []
    track_count = metadata.get("track_count", {})

    expected_video = track_count.get("video", 0)
    actual_video = len(cuts.get("video_tracks", []))
    if expected_video and actual_video != expected_video:
        issues.append(ValidationIssue(
            severity="warning",
            category="track_count",
            message=f"Metadata says {expected_video} video tracks, but cuts.json has {actual_video}",
            details={"expected": expected_video, "actual": actual_video, "domain": "video"},
        ))

    expected_audio = track_count.get("audio", 0)
    actual_audio = len(audio.get("audio_tracks", []))
    if expected_audio and actual_audio != expected_audio:
        issues.append(ValidationIssue(
            severity="warning",
            category="track_count",
            message=f"Metadata says {expected_audio} audio tracks, but audio.json has {actual_audio}",
            details={"expected": expected_audio, "actual": actual_audio, "domain": "audio"},
        ))

    return issues


def _check_speed_duration_consistency(cuts: dict) -> List[ValidationIssue]:
    """Check that retimed clips have plausible record durations.

    When a clip has a speed change, the record duration (timeline footprint)
    should roughly equal source_duration / speed_multiplier. Large mismatches
    suggest the speed metadata is stale after a merge.
    """
    issues = []
    for track in cuts.get("video_tracks", []):
        for item in track.get("items", []):
            speed = item.get("speed", {})
            pct = speed.get("speed_percent", 100.0)
            if pct == 100.0 or pct <= 0:
                continue

            record_dur = item.get("record_end_frame", 0) - item.get("record_start_frame", 0)
            source_dur = item.get("source_end_frame", 0) - item.get("source_start_frame", 0)
            if source_dur <= 0 or record_dur <= 0:
                continue

            expected_record = source_dur / (pct / 100.0)
            # Allow 10% tolerance for rounding and frame-boundary effects
            if abs(record_dur - expected_record) > max(expected_record * 0.1, 2):
                issues.append(ValidationIssue(
                    severity="warning",
                    category="speed_duration",
                    message=(
                        f"Clip '{item.get('name', '?')}' has {pct}% speed but "
                        f"record duration ({record_dur}f) doesn't match expected "
                        f"({expected_record:.0f}f) — may be stale after merge"
                    ),
                    details={
                        "item_id": item.get("id"),
                        "speed_percent": pct,
                        "record_duration": record_dur,
                        "expected_duration": round(expected_record),
                    },
                ))
    return issues


def _check_speed_sync(cuts: dict, audio: dict) -> List[ValidationIssue]:
    """Check that linked video and audio clips have matching speed values.

    If one branch changes a video clip's speed but the audio branch doesn't
    update the corresponding audio clip, they'll be out of sync.
    """
    issues = []
    video_by_ref: Dict[str, dict] = {}
    for track in cuts.get("video_tracks", []):
        for item in track.get("items", []):
            ref = item.get("media_ref")
            if ref:
                video_by_ref[ref] = item

    for track in audio.get("audio_tracks", []):
        for audio_item in track.get("items", []):
            ref = audio_item.get("media_ref")
            if not ref or ref not in video_by_ref:
                continue

            video_item = video_by_ref[ref]
            v_speed = video_item.get("speed", {}).get("speed_percent", 100.0)
            a_speed = audio_item.get("speed", {}).get("speed_percent", 100.0)

            if v_speed != a_speed:
                issues.append(ValidationIssue(
                    severity="warning",
                    category="speed_sync",
                    message=(
                        f"Speed mismatch for linked media '{ref}': "
                        f"video={v_speed}% vs audio={a_speed}%"
                    ),
                    details={
                        "media_ref": ref,
                        "video_item": video_item.get("id"),
                        "audio_item": audio_item.get("id"),
                        "video_speed": v_speed,
                        "audio_speed": a_speed,
                    },
                ))

    return issues


def format_issues(issues: List[ValidationIssue]) -> str:
    """Format validation issues for display."""
    if not issues:
        return "  No issues found."

    lines = []
    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]

    if errors:
        lines.append(f"  {len(errors)} error(s):")
        for issue in errors:
            lines.append(f"    {issue}")

    if warnings:
        lines.append(f"  {len(warnings)} warning(s):")
        for issue in warnings:
            lines.append(f"    {issue}")

    return "\n".join(lines)
