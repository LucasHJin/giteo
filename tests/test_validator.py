"""Tests for validator.py — orphaned refs, overlaps, sync issues."""

import os
import tempfile

import pytest

from giteo.json_writer import _write_json
from giteo.validator import validate_project


@pytest.fixture
def project_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, "timeline"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "assets"), exist_ok=True)
        yield tmpdir


def _write_domain_files(project_dir, cuts=None, color=None, audio=None, metadata=None, effects=None):
    """Helper to write domain files."""
    if cuts is not None:
        _write_json(os.path.join(project_dir, "timeline", "cuts.json"), cuts)
    if color is not None:
        _write_json(os.path.join(project_dir, "timeline", "color.json"), color)
    if audio is not None:
        _write_json(os.path.join(project_dir, "timeline", "audio.json"), audio)
    if metadata is not None:
        _write_json(os.path.join(project_dir, "timeline", "metadata.json"), metadata)
    if effects is not None:
        _write_json(os.path.join(project_dir, "timeline", "effects.json"), effects)


def test_valid_project(project_dir):
    """A consistent project should have no issues."""
    _write_domain_files(
        project_dir,
        cuts={"video_tracks": [{"index": 1, "items": [
            {"id": "item_001", "name": "A", "record_start_frame": 0, "record_end_frame": 100, "track_index": 1, "media_ref": "sha256:abc"}
        ]}]},
        color={"grades": {"item_001": {"contrast": 1.0, "saturation": 1.0, "lut": None}}},
        audio={"audio_tracks": [{"index": 1, "items": [
            {"id": "audio_001", "media_ref": "sha256:abc", "start_frame": 0, "end_frame": 100, "volume": 0, "pan": 0}
        ]}]},
        metadata={"track_count": {"video": 1, "audio": 1}},
        effects={},
    )

    issues = validate_project(project_dir)
    assert len(issues) == 0


def test_orphaned_color_ref(project_dir):
    """Color grade referencing a deleted clip should be caught."""
    _write_domain_files(
        project_dir,
        cuts={"video_tracks": [{"index": 1, "items": []}]},  # No clips
        color={"grades": {"item_001": {"contrast": 1.0}}},  # References item_001
        audio={"audio_tracks": []},
        metadata={},
        effects={},
    )

    issues = validate_project(project_dir)
    assert len(issues) == 1
    assert issues[0].category == "orphaned_ref"
    assert "item_001" in issues[0].message


def test_overlapping_clips(project_dir):
    """Overlapping clips on the same track should be caught."""
    _write_domain_files(
        project_dir,
        cuts={"video_tracks": [{"index": 1, "items": [
            {"id": "item_001", "name": "A", "record_start_frame": 0, "record_end_frame": 200, "track_index": 1},
            {"id": "item_002", "name": "B", "record_start_frame": 100, "record_end_frame": 300, "track_index": 1},
        ]}]},
        color={"grades": {}},
        audio={"audio_tracks": []},
        metadata={},
        effects={},
    )

    issues = validate_project(project_dir)
    overlap_issues = [i for i in issues if i.category == "overlap"]
    assert len(overlap_issues) == 1


def test_audio_video_sync_mismatch(project_dir):
    """Audio/video boundary mismatch should produce a warning."""
    _write_domain_files(
        project_dir,
        cuts={"video_tracks": [{"index": 1, "items": [
            {"id": "item_001", "name": "A", "record_start_frame": 0, "record_end_frame": 100, "media_ref": "sha256:abc", "track_index": 1}
        ]}]},
        color={"grades": {}},
        audio={"audio_tracks": [{"index": 1, "items": [
            {"id": "audio_001", "media_ref": "sha256:abc", "start_frame": 0, "end_frame": 200, "volume": 0, "pan": 0}
        ]}]},
        metadata={},
        effects={},
    )

    issues = validate_project(project_dir)
    sync_issues = [i for i in issues if i.category == "sync"]
    assert len(sync_issues) == 1


def test_track_count_mismatch(project_dir):
    """Track count in metadata not matching actual tracks should warn."""
    _write_domain_files(
        project_dir,
        cuts={"video_tracks": [{"index": 1, "items": []}]},
        color={"grades": {}},
        audio={"audio_tracks": [{"index": 1, "items": []}]},
        metadata={"track_count": {"video": 3, "audio": 1}},
        effects={},
    )

    issues = validate_project(project_dir)
    tc_issues = [i for i in issues if i.category == "track_count"]
    assert len(tc_issues) == 1
    assert "video" in tc_issues[0].message.lower()


def test_speed_duration_consistency(project_dir):
    """A retimed clip whose record duration doesn't match speed should warn."""
    _write_domain_files(
        project_dir,
        cuts={"video_tracks": [{"index": 1, "items": [
            {
                "id": "item_001", "name": "SlowMo",
                "record_start_frame": 0, "record_end_frame": 200,
                "source_start_frame": 0, "source_end_frame": 100,
                "track_index": 1, "media_ref": "sha256:abc",
                "speed": {"speed_percent": 50.0},
            }
        ]}]},
        color={"grades": {}},
        audio={"audio_tracks": []},
        metadata={},
        effects={},
    )

    issues = validate_project(project_dir)
    speed_issues = [i for i in issues if i.category == "speed_duration"]
    # 50% speed on 100-frame source = 200 record frames — this is correct
    assert len(speed_issues) == 0


def test_speed_duration_inconsistency(project_dir):
    """A retimed clip with wrong record duration should warn."""
    _write_domain_files(
        project_dir,
        cuts={"video_tracks": [{"index": 1, "items": [
            {
                "id": "item_001", "name": "BrokenSpeed",
                "record_start_frame": 0, "record_end_frame": 100,
                "source_start_frame": 0, "source_end_frame": 100,
                "track_index": 1, "media_ref": "sha256:abc",
                "speed": {"speed_percent": 50.0},
            }
        ]}]},
        color={"grades": {}},
        audio={"audio_tracks": []},
        metadata={},
        effects={},
    )

    issues = validate_project(project_dir)
    speed_issues = [i for i in issues if i.category == "speed_duration"]
    # 50% speed on 100-frame source should = 200 record frames, but we have 100
    assert len(speed_issues) == 1
    assert "50.0%" in speed_issues[0].message


def test_speed_sync_mismatch(project_dir):
    """Linked video and audio clips with different speeds should warn."""
    _write_domain_files(
        project_dir,
        cuts={"video_tracks": [{"index": 1, "items": [
            {
                "id": "item_001", "name": "A",
                "record_start_frame": 0, "record_end_frame": 100,
                "source_start_frame": 0, "source_end_frame": 100,
                "track_index": 1, "media_ref": "sha256:abc",
                "speed": {"speed_percent": 200.0},
            }
        ]}]},
        color={"grades": {}},
        audio={"audio_tracks": [{"index": 1, "items": [
            {
                "id": "audio_001", "media_ref": "sha256:abc",
                "start_frame": 0, "end_frame": 100,
                "volume": 0, "pan": 0,
            }
        ]}]},
        metadata={},
        effects={},
    )

    issues = validate_project(project_dir)
    sync_issues = [i for i in issues if i.category == "speed_sync"]
    # Video has 200% speed, audio has default 100%
    assert len(sync_issues) == 1
    assert "200" in sync_issues[0].message
