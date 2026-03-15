"""Tests for text/generator clip handling — serialize, deserialize, roundtrip.

Covers:
- Adding/removing Text+ clips
- Changing text content, font, size, bold, italic, color
- Mixed timelines (media + Text+ clips)
- Fusion comp export/import roundtrip
- Generator detection and tagging
- Backward compatibility (JSON without generator fields)
"""

import json
import os
import tempfile

import pytest

from giteo.serializer import (
    _is_generator,
    _export_fusion_comp,
    _read_text_properties,
    _serialize_video_tracks,
    serialize_timeline,
)
from giteo.deserializer import (
    _apply_generators,
    _collect_video_clip_infos,
    _insert_fusion_item,
    deserialize_timeline,
)
from giteo.json_writer import read_json
from giteo.models import TextProperties, VideoItem, VideoTrack
from tests.mock_resolve import (
    MockFusionComp,
    MockFusionTool,
    MockMediaPool,
    MockMediaPoolItem,
    MockProject,
    MockTimeline,
    MockTimelineItem,
    create_text_clip,
    create_test_timeline,
)


@pytest.fixture
def project_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, "timeline"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "assets"), exist_ok=True)
        yield tmpdir


# ---------------------------------------------------------------------------
# Generator detection
# ---------------------------------------------------------------------------

class TestGeneratorDetection:

    def test_media_clip_is_not_generator(self):
        media = MockMediaPoolItem(filepath="/Volumes/Media/clip.mov")
        clip = MockTimelineItem(name="Clip", media_pool_item=media)
        assert _is_generator(clip, media) is False

    def test_text_clip_is_generator(self):
        text_clip = create_text_clip(text="Hello")
        pool_item = text_clip.GetMediaPoolItem()
        assert _is_generator(text_clip, pool_item) is True

    def test_clip_with_no_path_and_no_fusion_is_still_generator(self):
        """Any clip without a File Path is a generator/title (e.g. 'Text' title)."""
        pool_item = MockMediaPoolItem(filepath="")
        clip = MockTimelineItem(name="Text", media_pool_item=pool_item)
        assert _is_generator(clip, pool_item) is True

    def test_none_media_pool_item_with_fusion_is_generator(self):
        fusion_comp = MockFusionComp(tools={"T": MockFusionTool()})
        clip = MockTimelineItem(
            name="Text+", media_pool_item=None, fusion_comp=fusion_comp)
        assert _is_generator(clip, None) is True


# ---------------------------------------------------------------------------
# Text property reading
# ---------------------------------------------------------------------------

class TestReadTextProperties:

    def test_reads_text_content(self):
        clip = create_text_clip(text="Welcome to the show")
        props = _read_text_properties(clip)
        assert props is not None
        assert props.styled_text == "Welcome to the show"

    def test_reads_font(self):
        clip = create_text_clip(font="Helvetica Neue")
        props = _read_text_properties(clip)
        assert props.font == "Helvetica Neue"

    def test_reads_size(self):
        clip = create_text_clip(size=0.15)
        props = _read_text_properties(clip)
        assert props.size == 0.15

    def test_reads_bold(self):
        clip = create_text_clip(bold=True)
        props = _read_text_properties(clip)
        assert props.bold is True

    def test_reads_bold_false(self):
        clip = create_text_clip(bold=False)
        props = _read_text_properties(clip)
        assert props.bold is False

    def test_reads_italic(self):
        clip = create_text_clip(italic=True)
        props = _read_text_properties(clip)
        assert props.italic is True

    def test_reads_color(self):
        clip = create_text_clip(color_r=1.0, color_g=0.5, color_b=0.0)
        props = _read_text_properties(clip)
        assert props.color is not None
        assert props.color["r"] == 1.0
        assert props.color["g"] == 0.5
        assert props.color["b"] == 0.0

    def test_returns_none_for_no_fusion_comp(self):
        clip = MockTimelineItem(name="Regular Clip")
        assert _read_text_properties(clip) is None

    def test_returns_none_for_non_text_fusion(self):
        non_text_tool = MockFusionTool(tool_id="Merge", inputs={})
        comp = MockFusionComp(tools={"Merge1": non_text_tool})
        clip = MockTimelineItem(name="Effect", fusion_comp=comp)
        assert _read_text_properties(clip) is None


# ---------------------------------------------------------------------------
# Fusion comp export
# ---------------------------------------------------------------------------

class TestExportFusionComp:

    def test_exports_comp_file(self, project_dir):
        clip = create_text_clip(text="Export Test")
        filename = _export_fusion_comp(clip, project_dir, "item_001_000")
        assert filename == "item_001_000.comp"
        comp_path = os.path.join(
            project_dir, "timeline", "generators", "item_001_000.comp")
        assert os.path.exists(comp_path)

    def test_creates_generators_directory(self, project_dir):
        clip = create_text_clip(text="Dir Test")
        _export_fusion_comp(clip, project_dir, "item_001_000")
        assert os.path.isdir(
            os.path.join(project_dir, "timeline", "generators"))

    def test_returns_none_for_clip_without_fusion(self, project_dir):
        clip = MockTimelineItem(name="No Fusion")
        result = _export_fusion_comp(clip, project_dir, "item_001_000")
        assert result is None


# ---------------------------------------------------------------------------
# Serialization of text clips
# ---------------------------------------------------------------------------

class TestSerializeTextClips:

    def test_text_clip_tagged_as_title(self, project_dir):
        text_clip = create_text_clip(text="Title Card", start=0, end=120)
        timeline = MockTimeline(
            name="Text Test", video_tracks={1: [text_clip]})
        project = MockProject(name="Text Project", timeline=timeline)

        serialize_timeline(timeline, project, project_dir)
        cuts = read_json(os.path.join(project_dir, "timeline", "cuts.json"))

        item = cuts["video_tracks"][0]["items"][0]
        assert item["item_type"] == "title"
        assert item["media_ref"].startswith("generator:")

    def test_text_properties_in_json(self, project_dir):
        text_clip = create_text_clip(
            text="Hello World", font="Arial", size=0.1,
            bold=True, italic=False)
        timeline = MockTimeline(
            name="Props Test", video_tracks={1: [text_clip]})
        project = MockProject(name="Test", timeline=timeline)

        serialize_timeline(timeline, project, project_dir)
        cuts = read_json(os.path.join(project_dir, "timeline", "cuts.json"))

        item = cuts["video_tracks"][0]["items"][0]
        assert "text_properties" in item
        tp = item["text_properties"]
        assert tp["styled_text"] == "Hello World"
        assert tp["font"] == "Arial"
        assert tp["size"] == 0.1
        assert tp["bold"] is True
        assert "italic" not in tp  # False values omitted

    def test_fusion_comp_exported(self, project_dir):
        text_clip = create_text_clip(text="Comp Export")
        timeline = MockTimeline(
            name="Comp Test", video_tracks={1: [text_clip]})
        project = MockProject(name="Test", timeline=timeline)

        serialize_timeline(timeline, project, project_dir)
        cuts = read_json(os.path.join(project_dir, "timeline", "cuts.json"))

        item = cuts["video_tracks"][0]["items"][0]
        assert item.get("fusion_comp_file") is not None
        comp_path = os.path.join(
            project_dir, "timeline", "generators", item["fusion_comp_file"])
        assert os.path.exists(comp_path)

    def test_generator_name_preserved(self, project_dir):
        text_clip = create_text_clip(name="Lower Third")
        timeline = MockTimeline(
            name="Name Test", video_tracks={1: [text_clip]})
        project = MockProject(name="Test", timeline=timeline)

        serialize_timeline(timeline, project, project_dir)
        cuts = read_json(os.path.join(project_dir, "timeline", "cuts.json"))

        item = cuts["video_tracks"][0]["items"][0]
        assert item["generator_name"] == "Lower Third"

    def test_text_clip_not_in_manifest(self, project_dir):
        """Generator clips should NOT appear in assets/manifest.json."""
        text_clip = create_text_clip(text="No Manifest")
        timeline = MockTimeline(
            name="Manifest Test", video_tracks={1: [text_clip]})
        project = MockProject(name="Test", timeline=timeline)

        serialize_timeline(timeline, project, project_dir)
        manifest = read_json(
            os.path.join(project_dir, "assets", "manifest.json"))

        for ref in manifest.get("assets", {}):
            assert not ref.startswith("generator:")


# ---------------------------------------------------------------------------
# Mixed timeline (media + text clips)
# ---------------------------------------------------------------------------

class TestMixedTimeline:

    def _create_mixed_timeline(self):
        media = MockMediaPoolItem(
            filepath="/Volumes/Media/interview.mov", frames=14400)
        media_clip = MockTimelineItem(
            name="Interview", start=0, end=720,
            left_offset=100, media_pool_item=media)
        text_clip = create_text_clip(
            name="Title", text="My Documentary",
            font="Futura", bold=True, start=720, end=840)
        timeline = MockTimeline(
            name="Mixed Edit",
            video_tracks={1: [media_clip, text_clip]})
        project = MockProject(name="Doc Project", timeline=timeline)
        project.GetMediaPool().GetRootFolder()._clips = [media]
        return project, timeline

    def test_both_clips_serialized(self, project_dir):
        project, timeline = self._create_mixed_timeline()
        serialize_timeline(timeline, project, project_dir)
        cuts = read_json(os.path.join(project_dir, "timeline", "cuts.json"))

        items = cuts["video_tracks"][0]["items"]
        assert len(items) == 2
        assert items[0].get("item_type", "media") == "media"
        assert items[1]["item_type"] == "title"

    def test_only_media_in_manifest(self, project_dir):
        project, timeline = self._create_mixed_timeline()
        serialize_timeline(timeline, project, project_dir)
        manifest = read_json(
            os.path.join(project_dir, "assets", "manifest.json"))

        assert len(manifest["assets"]) == 1
        for ref, info in manifest["assets"].items():
            assert info["filename"] == "interview.mov"

    def test_generator_skipped_in_clip_infos(self, project_dir):
        project, timeline = self._create_mixed_timeline()
        serialize_timeline(timeline, project, project_dir)

        video_tracks = [
            VideoTrack.from_dict(t) for t in
            read_json(os.path.join(project_dir, "timeline", "cuts.json"))
            .get("video_tracks", [])
        ]
        manifest = read_json(
            os.path.join(project_dir, "assets", "manifest.json"))
        media_pool = project.GetMediaPool()

        clip_infos = _collect_video_clip_infos(
            media_pool, video_tracks, manifest)
        assert len(clip_infos) == 1

    def test_deserialize_mixed_timeline(self, project_dir):
        project, timeline = self._create_mixed_timeline()
        serialize_timeline(timeline, project, project_dir)
        deserialize_timeline(timeline, project, project_dir)

        current = project.GetCurrentTimeline()
        assert current is not timeline
        assert current.GetName() == "Mixed Edit"


# ---------------------------------------------------------------------------
# Text content changes (diffing scenarios)
# ---------------------------------------------------------------------------

class TestTextChanges:

    def test_text_content_change(self, project_dir):
        """Changing text content should produce different JSON."""
        clip_v1 = create_text_clip(text="Draft Title")
        tl1 = MockTimeline(name="V1", video_tracks={1: [clip_v1]})
        p1 = MockProject(name="P", timeline=tl1)
        serialize_timeline(tl1, p1, project_dir)
        cuts_v1 = read_json(
            os.path.join(project_dir, "timeline", "cuts.json"))

        clip_v2 = create_text_clip(text="Final Title")
        tl2 = MockTimeline(name="V2", video_tracks={1: [clip_v2]})
        p2 = MockProject(name="P", timeline=tl2)
        serialize_timeline(tl2, p2, project_dir)
        cuts_v2 = read_json(
            os.path.join(project_dir, "timeline", "cuts.json"))

        tp_v1 = cuts_v1["video_tracks"][0]["items"][0]["text_properties"]
        tp_v2 = cuts_v2["video_tracks"][0]["items"][0]["text_properties"]
        assert tp_v1["styled_text"] == "Draft Title"
        assert tp_v2["styled_text"] == "Final Title"

    def test_font_change(self, project_dir):
        clip_v1 = create_text_clip(font="Arial")
        tl1 = MockTimeline(name="V1", video_tracks={1: [clip_v1]})
        serialize_timeline(tl1, MockProject(name="P", timeline=tl1), project_dir)
        cuts_v1 = read_json(
            os.path.join(project_dir, "timeline", "cuts.json"))

        clip_v2 = create_text_clip(font="Helvetica Neue")
        tl2 = MockTimeline(name="V2", video_tracks={1: [clip_v2]})
        serialize_timeline(tl2, MockProject(name="P", timeline=tl2), project_dir)
        cuts_v2 = read_json(
            os.path.join(project_dir, "timeline", "cuts.json"))

        assert cuts_v1["video_tracks"][0]["items"][0]["text_properties"]["font"] == "Arial"
        assert cuts_v2["video_tracks"][0]["items"][0]["text_properties"]["font"] == "Helvetica Neue"

    def test_bold_toggle(self, project_dir):
        clip_off = create_text_clip(text="Title", bold=False)
        tl_off = MockTimeline(name="Off", video_tracks={1: [clip_off]})
        serialize_timeline(
            tl_off, MockProject(name="P", timeline=tl_off), project_dir)
        cuts_off = read_json(
            os.path.join(project_dir, "timeline", "cuts.json"))

        clip_on = create_text_clip(text="Title", bold=True)
        tl_on = MockTimeline(name="On", video_tracks={1: [clip_on]})
        serialize_timeline(
            tl_on, MockProject(name="P", timeline=tl_on), project_dir)
        cuts_on = read_json(
            os.path.join(project_dir, "timeline", "cuts.json"))

        tp_off = cuts_off["video_tracks"][0]["items"][0]["text_properties"]
        tp_on = cuts_on["video_tracks"][0]["items"][0]["text_properties"]
        assert "bold" not in tp_off  # False omitted
        assert tp_on["bold"] is True

    def test_italic_toggle(self, project_dir):
        clip = create_text_clip(text="Emphasis", italic=True)
        tl = MockTimeline(name="Italic", video_tracks={1: [clip]})
        serialize_timeline(
            tl, MockProject(name="P", timeline=tl), project_dir)
        cuts = read_json(
            os.path.join(project_dir, "timeline", "cuts.json"))

        tp = cuts["video_tracks"][0]["items"][0]["text_properties"]
        assert tp["italic"] is True

    def test_size_change(self, project_dir):
        clip_small = create_text_clip(size=0.05)
        tl = MockTimeline(name="Small", video_tracks={1: [clip_small]})
        serialize_timeline(
            tl, MockProject(name="P", timeline=tl), project_dir)
        cuts = read_json(
            os.path.join(project_dir, "timeline", "cuts.json"))

        assert cuts["video_tracks"][0]["items"][0]["text_properties"]["size"] == 0.05

    def test_color_change(self, project_dir):
        clip = create_text_clip(color_r=1.0, color_g=0.0, color_b=0.0)
        tl = MockTimeline(name="Red", video_tracks={1: [clip]})
        serialize_timeline(
            tl, MockProject(name="P", timeline=tl), project_dir)
        cuts = read_json(
            os.path.join(project_dir, "timeline", "cuts.json"))

        tp = cuts["video_tracks"][0]["items"][0]["text_properties"]
        assert tp["color"]["r"] == 1.0
        assert tp["color"]["g"] == 0.0
        assert tp["color"]["b"] == 0.0


# ---------------------------------------------------------------------------
# Adding / removing text clips
# ---------------------------------------------------------------------------

class TestAddRemoveText:

    def test_add_text_to_empty_timeline(self, project_dir):
        text_clip = create_text_clip(text="First Title")
        tl = MockTimeline(name="Empty Start", video_tracks={1: [text_clip]})
        project = MockProject(name="P", timeline=tl)
        serialize_timeline(tl, project, project_dir)
        cuts = read_json(
            os.path.join(project_dir, "timeline", "cuts.json"))

        items = cuts["video_tracks"][0]["items"]
        assert len(items) == 1
        assert items[0]["item_type"] == "title"

    def test_remove_text_produces_empty_track(self, project_dir):
        tl = MockTimeline(name="No Text", video_tracks={1: []})
        project = MockProject(name="P", timeline=tl)
        serialize_timeline(tl, project, project_dir)
        cuts = read_json(
            os.path.join(project_dir, "timeline", "cuts.json"))

        items = cuts["video_tracks"][0]["items"]
        assert len(items) == 0

    def test_multiple_text_clips(self, project_dir):
        clip1 = create_text_clip(text="Title", start=0, end=120)
        clip2 = create_text_clip(text="Subtitle", start=120, end=240)
        clip3 = create_text_clip(text="Credits", start=240, end=360)
        tl = MockTimeline(
            name="Multi Text",
            video_tracks={1: [clip1, clip2, clip3]})
        project = MockProject(name="P", timeline=tl)
        serialize_timeline(tl, project, project_dir)
        cuts = read_json(
            os.path.join(project_dir, "timeline", "cuts.json"))

        items = cuts["video_tracks"][0]["items"]
        assert len(items) == 3
        assert all(i["item_type"] == "title" for i in items)
        texts = [i["text_properties"]["styled_text"] for i in items]
        assert texts == ["Title", "Subtitle", "Credits"]

    def test_text_on_multiple_tracks(self, project_dir):
        clip_v1 = create_text_clip(text="Lower Third", start=0, end=120)
        clip_v2 = create_text_clip(text="Bug Logo", start=0, end=120)
        tl = MockTimeline(
            name="Multi Track",
            video_tracks={1: [clip_v1], 2: [clip_v2]})
        project = MockProject(name="P", timeline=tl)
        serialize_timeline(tl, project, project_dir)
        cuts = read_json(
            os.path.join(project_dir, "timeline", "cuts.json"))

        assert len(cuts["video_tracks"]) == 2
        assert cuts["video_tracks"][0]["items"][0]["text_properties"]["styled_text"] == "Lower Third"
        assert cuts["video_tracks"][1]["items"][0]["text_properties"]["styled_text"] == "Bug Logo"


# ---------------------------------------------------------------------------
# Deserialization of generators
# ---------------------------------------------------------------------------

class TestDeserializeGenerators:

    def test_apply_generators_inserts_title(self):
        timeline = MockTimeline(name="Test")
        item = VideoItem(
            id="item_001_000", name="Text+",
            media_ref="generator:item_001_000",
            record_start_frame=0, record_end_frame=120,
            source_start_frame=0, source_end_frame=120,
            track_index=1,
            item_type="title", generator_name="Text+",
        )
        tracks = [VideoTrack(index=1, items=[item])]

        _apply_generators(timeline, tracks, "/tmp/nonexistent")

        clips = timeline.GetItemListInTrack("video", 1)
        assert len(clips) == 1
        assert clips[0].GetName() == "Text+"

    def test_insert_fusion_item_uses_title_api_for_titles(self):
        """Title items should try InsertFusionTitleIntoTimeline first."""
        timeline = MockTimeline(name="Title API Test")
        calls = []
        orig_title = timeline.InsertFusionTitleIntoTimeline
        orig_gen = timeline.InsertFusionGeneratorIntoTimeline

        def track_title(name):
            calls.append("title")
            return orig_title(name)

        def track_gen(name):
            calls.append("generator")
            return orig_gen(name)

        timeline.InsertFusionTitleIntoTimeline = track_title
        timeline.InsertFusionGeneratorIntoTimeline = track_gen

        item = VideoItem(
            id="item_001_000", name="Text+",
            media_ref="generator:item_001_000",
            record_start_frame=0, record_end_frame=120,
            source_start_frame=0, source_end_frame=120,
            track_index=1,
            item_type="title", generator_name="Text+",
        )
        _insert_fusion_item(timeline, item)
        assert calls == ["title"]

    def test_insert_fusion_item_falls_back(self):
        """If title API fails, should fall back to generator API."""
        timeline = MockTimeline(name="Fallback Test")
        timeline.InsertFusionTitleIntoTimeline = lambda name: None

        item = VideoItem(
            id="item_001_000", name="Text+",
            media_ref="generator:item_001_000",
            record_start_frame=0, record_end_frame=120,
            source_start_frame=0, source_end_frame=120,
            track_index=1,
            item_type="title", generator_name="Text+",
        )
        result = _insert_fusion_item(timeline, item)
        assert result is not None

    def test_apply_generators_imports_fusion_comp(self, project_dir):
        generators_dir = os.path.join(
            project_dir, "timeline", "generators")
        os.makedirs(generators_dir, exist_ok=True)
        comp_path = os.path.join(generators_dir, "item_001_000.comp")
        with open(comp_path, "w") as f:
            f.write("mock comp data")

        timeline = MockTimeline(name="Import Test")
        item = VideoItem(
            id="item_001_000", name="Text+",
            media_ref="generator:item_001_000",
            record_start_frame=0, record_end_frame=120,
            source_start_frame=0, source_end_frame=120,
            track_index=1,
            item_type="title", generator_name="Text+",
            fusion_comp_file="item_001_000.comp",
        )
        tracks = [VideoTrack(index=1, items=[item])]

        _apply_generators(timeline, tracks, project_dir)

        clips = timeline.GetItemListInTrack("video", 1)
        assert len(clips) == 1
        assert clips[0]._imported_comp_path == comp_path

    def test_apply_generators_applies_transform(self):
        from giteo.models import Transform

        timeline = MockTimeline(name="Transform Test")
        item = VideoItem(
            id="item_001_000", name="Text+",
            media_ref="generator:item_001_000",
            record_start_frame=0, record_end_frame=120,
            source_start_frame=0, source_end_frame=120,
            track_index=1,
            item_type="title", generator_name="Text+",
            transform=Transform(pan=50.0, tilt=-20.0, opacity=80.0),
        )
        tracks = [VideoTrack(index=1, items=[item])]

        _apply_generators(timeline, tracks, "/tmp/nonexistent")

        clip = timeline.GetItemListInTrack("video", 1)[0]
        assert clip.GetProperty("Pan") == 50.0
        assert clip.GetProperty("Tilt") == -20.0
        assert clip.GetProperty("Opacity") == 80.0

    def test_skips_media_items(self):
        timeline = MockTimeline(name="Skip Test")
        media_item = VideoItem(
            id="item_001_000", name="Clip",
            media_ref="sha256:abc123",
            record_start_frame=0, record_end_frame=720,
            source_start_frame=0, source_end_frame=720,
            track_index=1,
        )
        tracks = [VideoTrack(index=1, items=[media_item])]

        _apply_generators(timeline, tracks, "/tmp/nonexistent")

        clips = timeline.GetItemListInTrack("video", 1)
        assert len(clips) == 0


# ---------------------------------------------------------------------------
# Full roundtrip: serialize → write JSON → read JSON → deserialize
# ---------------------------------------------------------------------------

class TestTextRoundtrip:

    def test_text_properties_survive_json_roundtrip(self, project_dir):
        """TextProperties survive serialize → JSON → deserialize."""
        text_clip = create_text_clip(
            text="Roundtrip Test", font="Georgia", size=0.12,
            bold=True, italic=True,
            color_r=0.8, color_g=0.2, color_b=0.1)
        tl = MockTimeline(
            name="Roundtrip", video_tracks={1: [text_clip]})
        project = MockProject(name="P", timeline=tl)

        serialize_timeline(tl, project, project_dir)

        cuts = read_json(
            os.path.join(project_dir, "timeline", "cuts.json"))
        item_dict = cuts["video_tracks"][0]["items"][0]
        item = VideoItem.from_dict(item_dict)

        assert item.item_type == "title"
        assert item.is_generator is True
        assert item.text_properties is not None
        assert item.text_properties.styled_text == "Roundtrip Test"
        assert item.text_properties.font == "Georgia"
        assert item.text_properties.size == 0.12
        assert item.text_properties.bold is True
        assert item.text_properties.italic is True
        assert item.text_properties.color["r"] == 0.8

    def test_fusion_comp_file_survives_roundtrip(self, project_dir):
        text_clip = create_text_clip(text="Comp Roundtrip")
        tl = MockTimeline(
            name="Comp RT", video_tracks={1: [text_clip]})
        project = MockProject(name="P", timeline=tl)

        serialize_timeline(tl, project, project_dir)

        cuts = read_json(
            os.path.join(project_dir, "timeline", "cuts.json"))
        item = VideoItem.from_dict(cuts["video_tracks"][0]["items"][0])

        assert item.fusion_comp_file is not None
        comp_path = os.path.join(
            project_dir, "timeline", "generators", item.fusion_comp_file)
        assert os.path.exists(comp_path)

    def test_full_deserialize_with_text_clip(self, project_dir):
        """Full deserialize_timeline handles Text+ clips without error."""
        text_clip = create_text_clip(text="Full Test", font="Futura")
        media = MockMediaPoolItem(
            filepath="/Volumes/Media/clip.mov", frames=1000)
        media_clip = MockTimelineItem(
            name="Video Clip", start=0, end=500,
            left_offset=0, media_pool_item=media)
        tl = MockTimeline(
            name="Full Test",
            video_tracks={1: [media_clip, text_clip]})
        project = MockProject(name="P", timeline=tl)
        project.GetMediaPool().GetRootFolder()._clips = [media]

        serialize_timeline(tl, project, project_dir)
        deserialize_timeline(tl, project, project_dir)

        current = project.GetCurrentTimeline()
        assert current.GetName() == "Full Test"


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:

    def test_video_item_without_generator_fields(self):
        """VideoItem.from_dict should handle JSON without generator fields."""
        d = {
            "id": "item_001_000",
            "name": "Old Clip",
            "media_ref": "sha256:abc123",
            "record_start_frame": 0,
            "record_end_frame": 720,
            "source_start_frame": 0,
            "source_end_frame": 720,
            "track_index": 1,
            "transform": {"Pan": 0.0, "Tilt": 0.0, "ZoomX": 1.0,
                          "ZoomY": 1.0, "Opacity": 100.0},
        }
        item = VideoItem.from_dict(d)
        assert item.item_type == "media"
        assert item.is_generator is False
        assert item.generator_name == ""
        assert item.fusion_comp_file is None
        assert item.text_properties is None


# ---------------------------------------------------------------------------
# TextProperties model
# ---------------------------------------------------------------------------

class TestTextPropertiesModel:

    def test_to_dict_includes_required_fields(self):
        tp = TextProperties(
            styled_text="Hello", font="Arial", size=0.1)
        d = tp.to_dict()
        assert d["styled_text"] == "Hello"
        assert d["font"] == "Arial"
        assert d["size"] == 0.1

    def test_to_dict_omits_false_booleans(self):
        tp = TextProperties(bold=False, italic=False)
        d = tp.to_dict()
        assert "bold" not in d
        assert "italic" not in d

    def test_to_dict_includes_true_booleans(self):
        tp = TextProperties(bold=True, italic=True)
        d = tp.to_dict()
        assert d["bold"] is True
        assert d["italic"] is True

    def test_to_dict_omits_none_color(self):
        tp = TextProperties(color=None)
        d = tp.to_dict()
        assert "color" not in d

    def test_to_dict_includes_color(self):
        tp = TextProperties(color={"r": 1.0, "g": 0.5, "b": 0.0})
        d = tp.to_dict()
        assert d["color"] == {"r": 1.0, "g": 0.5, "b": 0.0}

    def test_roundtrip(self):
        original = TextProperties(
            styled_text="Test", font="Courier", size=0.08,
            bold=True, italic=True,
            color={"r": 0.5, "g": 0.5, "b": 1.0})
        d = original.to_dict()
        restored = TextProperties.from_dict(d)
        assert restored.styled_text == original.styled_text
        assert restored.font == original.font
        assert restored.size == original.size
        assert restored.bold == original.bold
        assert restored.italic == original.italic
        assert restored.color == original.color

    def test_from_dict_defaults(self):
        tp = TextProperties.from_dict({})
        assert tp.styled_text == ""
        assert tp.font == ""
        assert tp.size == 0.0
        assert tp.bold is False
        assert tp.italic is False
        assert tp.color is None


# ---------------------------------------------------------------------------
# JSON formatting (git-diffable)
# ---------------------------------------------------------------------------

class TestJsonFormatting:

    def test_text_clip_json_is_sorted_and_indented(self, project_dir):
        text_clip = create_text_clip(text="Format Test", bold=True)
        tl = MockTimeline(
            name="Format", video_tracks={1: [text_clip]})
        project = MockProject(name="P", timeline=tl)

        serialize_timeline(tl, project, project_dir)

        cuts_path = os.path.join(project_dir, "timeline", "cuts.json")
        with open(cuts_path) as f:
            content = f.read()

        assert content.endswith("\n")
        parsed = json.loads(content)
        expected = json.dumps(parsed, indent=2, sort_keys=True) + "\n"
        assert content == expected
