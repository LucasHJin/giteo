from giteo.merge_utils import merge_timeline_domains_for_overlays, referenced_sidecars


def test_title_collision_becomes_v2_overlay():
    ours = {
        "cuts": {
            "video_tracks": [
                {
                    "index": 1,
                    "items": [
                        {
                            "id": "item_001_000",
                            "name": "0117.mov",
                            "media_ref": "sha256:clip",
                            "record_start_frame": 0,
                            "record_end_frame": 120,
                            "source_start_frame": 0,
                            "source_end_frame": 120,
                            "track_index": 1,
                            "transform": {},
                        }
                    ],
                }
            ]
        },
        "color": {
            "grades": {
                "item_001_000": {"drx_file": "item_001_000_1.1.1.drx"}
            }
        },
        "audio": {"audio_tracks": []},
        "effects": {},
        "markers": {"markers": []},
        "metadata": {"track_count": {"video": 1, "audio": 1}},
        "manifest": {"assets": {"sha256:clip": {"path": "/clip.mov"}}},
    }
    theirs = {
        "cuts": {
            "video_tracks": [
                {
                    "index": 1,
                    "items": [
                        {
                            "id": "item_001_000",
                            "name": "Text+",
                            "media_ref": "generator:item_001_000",
                            "record_start_frame": 0,
                            "record_end_frame": 120,
                            "source_start_frame": 0,
                            "source_end_frame": 120,
                            "track_index": 1,
                            "item_type": "title",
                            "generator_name": "Text+",
                            "fusion_comp_file": "item_001_000.comp",
                            "text_properties": {"styled_text": "lucas"},
                            "transform": {},
                        }
                    ],
                }
            ]
        },
        "color": {
            "grades": {
                "item_001_000": {"drx_file": "item_001_000_1.1.1.drx"}
            }
        },
        "audio": {"audio_tracks": []},
        "effects": {},
        "markers": {"markers": []},
        "metadata": {"track_count": {"video": 1, "audio": 0}},
        "manifest": {"assets": {}},
    }

    merged, plan = merge_timeline_domains_for_overlays(theirs, ours, theirs)

    v1 = merged["cuts"]["video_tracks"][0]["items"][0]
    v2_track = merged["cuts"]["video_tracks"][1]
    overlay = v2_track["items"][0]

    assert v1["name"] == "0117.mov"
    assert overlay["name"] == "Text+"
    assert overlay["track_index"] == 2
    assert overlay["id"] == "item_001_000_overlay"
    assert overlay["media_ref"] == "generator:item_001_000_overlay"
    assert overlay["fusion_comp_file"] == "item_001_000_overlay.comp"
    assert merged["metadata"]["track_count"]["video"] == 2
    assert merged["color"]["grades"]["item_001_000"]["drx_file"] == "item_001_000_1.1.1.drx"
    assert (
        merged["color"]["grades"]["item_001_000_overlay"]["drx_file"]
        == "item_001_000_overlay_1.1.1.drx"
    )
    assert plan.generator_renames == {
        "item_001_000.comp": "item_001_000_overlay.comp"
    }
    assert plan.grade_renames == {
        "item_001_000_1.1.1.drx": "item_001_000_overlay_1.1.1.drx"
    }
    assert plan.grade_restore_ours == {"item_001_000_1.1.1.drx"}


def test_overlay_normalization_preserves_existing_non_overlay_merge_edits():
    ours = {
        "cuts": {
            "video_tracks": [
                {
                    "index": 1,
                    "items": [
                        {
                            "id": "item_001_000",
                            "name": "clip",
                            "media_ref": "sha256:clip",
                            "record_start_frame": 0,
                            "record_end_frame": 100,
                            "source_start_frame": 0,
                            "source_end_frame": 100,
                            "track_index": 1,
                            "transform": {},
                        }
                    ],
                }
            ]
        },
        "color": {"grades": {}},
        "audio": {"audio_tracks": []},
        "effects": {},
        "markers": {"markers": []},
        "metadata": {"track_count": {"video": 1, "audio": 0}},
        "manifest": {"assets": {}},
    }
    theirs = {
        "cuts": {
            "video_tracks": [
                {
                    "index": 1,
                    "items": [
                        {
                            "id": "item_001_000",
                            "name": "Text+",
                            "media_ref": "generator:item_001_000",
                            "record_start_frame": 0,
                            "record_end_frame": 120,
                            "source_start_frame": 0,
                            "source_end_frame": 120,
                            "track_index": 1,
                            "item_type": "title",
                            "generator_name": "Text+",
                            "fusion_comp_file": "item_001_000.comp",
                            "text_properties": {"styled_text": "lucas"},
                            "transform": {},
                        }
                    ],
                }
            ]
        },
        "color": {"grades": {}},
        "audio": {"audio_tracks": []},
        "effects": {},
        "markers": {"markers": []},
        "metadata": {"track_count": {"video": 1, "audio": 0}},
        "manifest": {"assets": {}},
    }
    current_merged = {
        "cuts": {
            "video_tracks": [
                {
                    "index": 1,
                    "items": [
                        {
                            "id": "item_001_000",
                            "name": "Text+",
                            "media_ref": "generator:item_001_000",
                            "record_start_frame": 0,
                            "record_end_frame": 120,
                            "source_start_frame": 0,
                            "source_end_frame": 120,
                            "track_index": 1,
                            "item_type": "title",
                            "generator_name": "Text+",
                            "fusion_comp_file": "item_001_000.comp",
                            "text_properties": {"styled_text": "lucas"},
                            "transform": {},
                        },
                        {
                            "id": "item_002_000",
                            "name": "broll",
                            "media_ref": "sha256:broll",
                            "record_start_frame": 130,
                            "record_end_frame": 200,
                            "source_start_frame": 0,
                            "source_end_frame": 70,
                            "track_index": 1,
                            "transform": {},
                        },
                    ],
                }
            ]
        },
        "color": {"grades": {}},
        "audio": {"audio_tracks": []},
        "effects": {},
        "markers": {"markers": []},
        "metadata": {"track_count": {"video": 1, "audio": 0}},
        "manifest": {"assets": {}},
    }

    merged, _ = merge_timeline_domains_for_overlays(current_merged, ours, theirs)

    assert merged["cuts"]["video_tracks"][0]["items"][0]["name"] == "clip"
    assert merged["cuts"]["video_tracks"][0]["items"][1]["name"] == "broll"
    assert merged["cuts"]["video_tracks"][1]["items"][0]["name"] == "Text+"


def test_referenced_sidecars_tracks_renamed_overlay_assets():
    merged = {
        "cuts": {
            "video_tracks": [
                {
                    "index": 2,
                    "items": [
                        {
                            "id": "item_001_000_overlay",
                            "fusion_comp_file": "item_001_000_overlay.comp",
                        }
                    ],
                }
            ]
        },
        "color": {
            "grades": {
                "item_001_000_overlay": {
                    "drx_file": "item_001_000_overlay_1.1.1.drx"
                }
            }
        },
    }

    generators, grades = referenced_sidecars(merged)

    assert generators == {"timeline/generators/item_001_000_overlay.comp"}
    assert grades == {"timeline/grades/item_001_000_overlay_1.1.1.drx"}
