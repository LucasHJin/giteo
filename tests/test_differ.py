"""Tests for differ.py — human-readable diff formatting."""

import pytest

from giteo.differ import (
    diff_cuts,
    diff_color,
    diff_audio,
    diff_markers,
    diff_metadata,
    format_diff,
    _frames_to_timecode,
)


def test_frames_to_timecode():
    assert _frames_to_timecode(0) == "00:00:00:00"
    assert _frames_to_timecode(24) == "00:00:01:00"
    assert _frames_to_timecode(240) == "00:00:10:00"
    assert _frames_to_timecode(1440) == "00:01:00:00"
    assert _frames_to_timecode(12, 24.0) == "00:00:00:12"


def test_diff_cuts_added_clip():
    old = {"video_tracks": [{"index": 1, "items": []}]}
    new = {
        "video_tracks": [
            {
                "index": 1,
                "items": [
                    {
                        "id": "item_001",
                        "name": "Interview.mov",
                        "track_index": 1,
                        "record_start_frame": 240,
                        "record_end_frame": 480,
                    }
                ],
            }
        ]
    }

    lines = diff_cuts(old, new, fps=24.0)
    assert len(lines) == 1
    assert "+ Added clip" in lines[0]
    assert "Interview.mov" in lines[0]


def test_diff_cuts_removed_clip():
    old = {
        "video_tracks": [
            {
                "index": 1,
                "items": [
                    {
                        "id": "item_001",
                        "name": "OldClip.mov",
                        "track_index": 1,
                        "record_start_frame": 0,
                        "record_end_frame": 100,
                    }
                ],
            }
        ]
    }
    new = {"video_tracks": [{"index": 1, "items": []}]}

    lines = diff_cuts(old, new, fps=24.0)
    assert len(lines) == 1
    assert "- Removed clip" in lines[0]
    assert "OldClip.mov" in lines[0]


def test_diff_cuts_trimmed_clip():
    old = {
        "video_tracks": [
            {
                "index": 1,
                "items": [
                    {
                        "id": "item_001",
                        "name": "Clip.mov",
                        "track_index": 1,
                        "record_start_frame": 0,
                        "record_end_frame": 720,
                    }
                ],
            }
        ]
    }
    new = {
        "video_tracks": [
            {
                "index": 1,
                "items": [
                    {
                        "id": "item_001",
                        "name": "Clip.mov",
                        "track_index": 1,
                        "record_start_frame": 0,
                        "record_end_frame": 684,
                    }
                ],
            }
        ]
    }

    lines = diff_cuts(old, new, fps=24.0)
    assert len(lines) == 1
    assert "Trimmed" in lines[0]
    assert "end" in lines[0]


def test_diff_color_changed():
    old = {"grades": {"item_001": {"num_nodes": 1, "nodes": [{"index": 1, "label": "", "lut": ""}], "version_name": "", "drx_file": None}}}
    new = {"grades": {"item_001": {"num_nodes": 2, "nodes": [{"index": 1, "label": "", "lut": ""}, {"index": 2, "label": "LUT", "lut": "Rec709.cube"}], "version_name": "", "drx_file": None}}}

    lines = diff_color(old, new)
    assert len(lines) >= 1
    found_change = any("num_nodes" in l or "node" in l.lower() or "LUT" in l for l in lines)
    assert found_change


def test_diff_markers_added():
    old = {"markers": []}
    new = {
        "markers": [
            {"frame": 240, "color": "Blue", "name": "Fix here", "note": "", "duration": 1}
        ]
    }

    lines = diff_markers(old, new, fps=24.0)
    assert len(lines) == 1
    assert "+ Added marker" in lines[0]
    assert "Fix here" in lines[0]


def test_diff_markers_removed():
    old = {
        "markers": [
            {"frame": 240, "color": "Blue", "name": "Old", "note": "", "duration": 1}
        ]
    }
    new = {"markers": []}

    lines = diff_markers(old, new, fps=24.0)
    assert len(lines) == 1
    assert "- Removed marker" in lines[0]


def test_diff_metadata_changed():
    old = {"project_name": "Old Name", "frame_rate": 24.0}
    new = {"project_name": "New Name", "frame_rate": 24.0}

    lines = diff_metadata(old, new)
    assert len(lines) == 1
    assert "project_name" in lines[0]


def test_diff_cuts_speed_changed():
    """Speed changes on a clip should appear in the diff."""
    old = {
        "video_tracks": [
            {
                "index": 1,
                "items": [
                    {
                        "id": "item_001",
                        "name": "Action.mov",
                        "track_index": 1,
                        "record_start_frame": 0,
                        "record_end_frame": 480,
                    }
                ],
            }
        ]
    }
    new = {
        "video_tracks": [
            {
                "index": 1,
                "items": [
                    {
                        "id": "item_001",
                        "name": "Action.mov",
                        "track_index": 1,
                        "record_start_frame": 0,
                        "record_end_frame": 480,
                        "speed": {
                            "speed_percent": 50.0,
                            "retime_process": 3,
                        },
                    }
                ],
            }
        ]
    }

    lines = diff_cuts(old, new, fps=24.0)
    speed_lines = [l for l in lines if "Speed" in l]
    assert len(speed_lines) >= 1
    assert "50.0%" in speed_lines[0]
    assert "slow" in speed_lines[0]

    retime_lines = [l for l in lines if "Retime" in l]
    assert len(retime_lines) == 1
    assert "optical_flow" in retime_lines[0]


def test_diff_audio_speed_changed():
    """Speed changes on audio clips should appear in the diff."""
    old = {
        "audio_tracks": [
            {
                "index": 1,
                "items": [
                    {"id": "audio_001", "volume": 0.0, "pan": 0.0}
                ],
            }
        ]
    }
    new = {
        "audio_tracks": [
            {
                "index": 1,
                "items": [
                    {
                        "id": "audio_001",
                        "volume": 0.0,
                        "pan": 0.0,
                        "speed": {"speed_percent": 200.0},
                    }
                ],
            }
        ]
    }

    lines = diff_audio(old, new, fps=24.0)
    speed_lines = [l for l in lines if "Speed" in l]
    assert len(speed_lines) == 1
    assert "200.0%" in speed_lines[0]
    assert "fast" in speed_lines[0]


def test_format_diff_no_changes():
    files = {"cuts": {}, "color": {}, "audio": {}, "markers": {}, "metadata": {}}
    output = format_diff(files, files, timeline_name="Test")
    assert "No changes" in output


def test_format_diff_full():
    old_files = {
        "cuts": {"video_tracks": [{"index": 1, "items": []}]},
        "color": {"grades": {}},
        "audio": {"audio_tracks": []},
        "markers": {"markers": []},
        "metadata": {"frame_rate": 24.0},
    }
    new_files = {
        "cuts": {
            "video_tracks": [
                {
                    "index": 1,
                    "items": [
                        {
                            "id": "item_001",
                            "name": "NewClip.mov",
                            "track_index": 1,
                            "record_start_frame": 0,
                            "record_end_frame": 480,
                        }
                    ],
                }
            ]
        },
        "color": {"grades": {}},
        "audio": {"audio_tracks": []},
        "markers": {"markers": []},
        "metadata": {"frame_rate": 24.0},
    }

    output = format_diff(old_files, new_files, timeline_name="Main Edit")
    assert "Timeline: Main Edit" in output
    assert "CUTS" in output
    assert "NewClip.mov" in output
