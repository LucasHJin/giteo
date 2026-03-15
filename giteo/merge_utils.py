"""Helpers for deterministic merge policies on timeline domain files."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Dict, Tuple


@dataclass
class OverlayMergePlan:
    """Bookkeeping for title-overlay remaps created during merge."""

    id_remaps: Dict[str, str] = field(default_factory=dict)
    generator_renames: Dict[str, str] = field(default_factory=dict)
    grade_renames: Dict[str, str] = field(default_factory=dict)
    grade_restore_ours: set[str] = field(default_factory=set)


def _is_generator_item(item: dict) -> bool:
    return item.get("item_type") in ("generator", "title") or str(
        item.get("media_ref", "")
    ).startswith("generator:")


def _collect_track_items(cuts: dict) -> Dict[int, list]:
    return {
        int(track.get("index", 0)): copy.deepcopy(track.get("items", []))
        for track in cuts.get("video_tracks", [])
    }


def _collect_existing_ids(track_map: Dict[int, list]) -> set:
    return {
        item.get("id")
        for items in track_map.values()
        for item in items
        if item.get("id")
    }


def _find_item(track_map: Dict[int, list], item_id: str) -> tuple[int, dict] | None:
    for track_index, items in track_map.items():
        for item in items:
            if item.get("id") == item_id:
                return track_index, item
    return None


def _find_overlay_item(track_map: Dict[int, list], item_id: str) -> tuple[int, dict] | None:
    prefix = f"{item_id}_overlay"
    for track_index, items in track_map.items():
        for item in items:
            current_id = str(item.get("id", ""))
            if current_id.startswith(prefix) and _is_generator_item(item):
                return track_index, item
    return None


def _remove_item(track_map: Dict[int, list], item_id: str) -> None:
    for track_index, items in list(track_map.items()):
        filtered = [item for item in items if item.get("id") != item_id]
        track_map[track_index] = filtered


def _ranges_overlap(a: dict, b: dict) -> bool:
    return not (
        a.get("record_end_frame", 0) <= b.get("record_start_frame", 0)
        or b.get("record_end_frame", 0) <= a.get("record_start_frame", 0)
    )


def _first_overlay_track(track_map: Dict[int, list], item: dict) -> int:
    track_index = 2
    while True:
        items = track_map.get(track_index, [])
        if all(not _ranges_overlap(existing, item) for existing in items):
            return track_index
        track_index += 1


def _unique_overlay_id(existing_ids: set, base_id: str) -> str:
    candidate = f"{base_id}_overlay"
    suffix = 1
    while candidate in existing_ids:
        suffix += 1
        candidate = f"{base_id}_overlay_{suffix}"
    return candidate


def _remap_generator_fields(item: dict, old_id: str, new_id: str, plan: OverlayMergePlan) -> None:
    media_ref = str(item.get("media_ref", ""))
    if media_ref == f"generator:{old_id}":
        item["media_ref"] = f"generator:{new_id}"

    comp_file = item.get("fusion_comp_file")
    if comp_file == f"{old_id}.comp":
        new_comp = f"{new_id}.comp"
        item["fusion_comp_file"] = new_comp
        plan.generator_renames[comp_file] = new_comp


def merge_timeline_domains_for_overlays(
    merged_files: Dict[str, dict],
    ours_files: Dict[str, dict],
    theirs_files: Dict[str, dict],
) -> Tuple[Dict[str, dict], OverlayMergePlan]:
    """Normalize title/media ID collisions so titles become overlays."""
    merged = copy.deepcopy(merged_files)
    plan = OverlayMergePlan()

    ours_cuts = ours_files.get("cuts", {})
    theirs_cuts = theirs_files.get("cuts", {})
    track_map = _collect_track_items(merged.get("cuts", {}))
    existing_ids = _collect_existing_ids(track_map)

    for their_track in theirs_cuts.get("video_tracks", []):
        for their_item in their_track.get("items", []):
            their_id = their_item.get("id")
            if not their_id:
                continue

            ours_match = _find_item(_collect_track_items(ours_cuts), their_id)
            if ours_match is None:
                continue

            _, ours_item = ours_match
            if (
                not _is_generator_item(ours_item)
                and _is_generator_item(their_item)
            ):
                current_match = _find_item(track_map, their_id)
                overlay_match = _find_overlay_item(track_map, their_id)

                if overlay_match:
                    _, existing_overlay = overlay_match
                    new_id = existing_overlay["id"]
                else:
                    new_id = _unique_overlay_id(existing_ids, their_id)
                    existing_ids.add(new_id)

                if current_match and _is_generator_item(current_match[1]):
                    _remove_item(track_map, their_id)

                current_after = _find_item(track_map, their_id)
                if current_after is None:
                    restored_media = copy.deepcopy(ours_item)
                    restored_media["track_index"] = ours_item.get("track_index", 1)
                    track_map.setdefault(restored_media["track_index"], []).append(restored_media)

                if overlay_match:
                    overlay_track, overlay_item = overlay_match
                    overlay_item["track_index"] = overlay_track
                else:
                    overlay_item = copy.deepcopy(their_item)
                    overlay_track = _first_overlay_track(track_map, overlay_item)
                    overlay_item["track_index"] = overlay_track

                if overlay_item.get("id") != new_id:
                    plan.id_remaps[their_id] = new_id
                overlay_item["id"] = new_id
                _remap_generator_fields(overlay_item, their_id, new_id, plan)
                if not overlay_match:
                    track_map.setdefault(overlay_track, []).append(overlay_item)

    merged["cuts"] = {
        "video_tracks": [
            {
                "index": idx,
                "items": sorted(
                    items,
                    key=lambda item: (
                        item.get("record_start_frame", 0),
                        item.get("record_end_frame", 0),
                        item.get("id", ""),
                    ),
                ),
            }
            for idx, items in sorted(track_map.items())
        ]
    }

    merged.setdefault("effects", {})
    merged.setdefault("color", {})
    merged["effects"].setdefault("clip_effects", {})
    merged["color"].setdefault("grades", {})

    for original_id, overlay_id in plan.id_remaps.items():
        ours_effect = ours_files.get("effects", {}).get("clip_effects", {}).get(original_id)
        theirs_effect = theirs_files.get("effects", {}).get("clip_effects", {}).get(original_id)
        if ours_effect is not None:
            merged["effects"]["clip_effects"][original_id] = copy.deepcopy(ours_effect)
        else:
            merged["effects"]["clip_effects"].pop(original_id, None)
        if theirs_effect is not None:
            merged["effects"]["clip_effects"][overlay_id] = copy.deepcopy(theirs_effect)

        ours_grade = ours_files.get("color", {}).get("grades", {}).get(original_id)
        theirs_grade = theirs_files.get("color", {}).get("grades", {}).get(original_id)
        if ours_grade is not None:
            merged["color"]["grades"][original_id] = copy.deepcopy(ours_grade)
        else:
            merged["color"]["grades"].pop(original_id, None)

        if theirs_grade is not None:
            grade_copy = copy.deepcopy(theirs_grade)
            drx_file = grade_copy.get("drx_file")
            if drx_file:
                if str(drx_file).startswith(f"{original_id}_"):
                    new_drx = str(drx_file).replace(f"{original_id}_", f"{overlay_id}_", 1)
                elif str(drx_file).startswith(original_id):
                    new_drx = str(drx_file).replace(original_id, overlay_id, 1)
                else:
                    new_drx = f"{overlay_id}.drx"
                if new_drx != drx_file:
                    plan.grade_renames[str(drx_file)] = new_drx
                    if ours_grade is not None and ours_grade.get("drx_file") == drx_file:
                        plan.grade_restore_ours.add(str(drx_file))
                    grade_copy["drx_file"] = new_drx
            merged["color"]["grades"][overlay_id] = grade_copy

    merged["metadata"] = copy.deepcopy(merged.get("metadata", {}))
    merged["metadata"].setdefault("track_count", {})
    highest_video_track = max(
        (track["index"] for track in merged["cuts"].get("video_tracks", [])),
        default=1,
    )
    merged["metadata"]["track_count"]["video"] = max(
        int(merged_files.get("metadata", {}).get("track_count", {}).get("video", 0) or 0),
        highest_video_track,
    )

    if "audio_tracks" in merged.get("audio", {}):
        merged["metadata"]["track_count"]["audio"] = max(
            int(merged_files.get("metadata", {}).get("track_count", {}).get("audio", 0) or 0),
            len(merged["audio"].get("audio_tracks", [])),
        )

    return merged, plan


def referenced_sidecars(domain_files: Dict[str, dict]) -> Tuple[set, set]:
    """Return referenced generator and grade sidecar paths."""
    generator_files = set()
    grade_files = set()

    for track in domain_files.get("cuts", {}).get("video_tracks", []):
        for item in track.get("items", []):
            comp_file = item.get("fusion_comp_file")
            if comp_file:
                generator_files.add(f"timeline/generators/{comp_file}")

    for grade in domain_files.get("color", {}).get("grades", {}).values():
        drx_file = grade.get("drx_file")
        if drx_file:
            grade_files.add(f"timeline/grades/{drx_file}")

    return generator_files, grade_files


def domain_file_map() -> Dict[str, str]:
    return {
        "cuts": "timeline/cuts.json",
        "color": "timeline/color.json",
        "audio": "timeline/audio.json",
        "effects": "timeline/effects.json",
        "markers": "timeline/markers.json",
        "metadata": "timeline/metadata.json",
        "manifest": "assets/manifest.json",
    }
