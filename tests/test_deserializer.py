"""Tests for DRX grade restore fallbacks and overlay restore."""

from giteo.deserializer import _apply_grade_from_drx, restore_timeline_overlays


class _FakeTimeline:
    def __init__(self, apply_result=None):
        self._apply_result = apply_result
        self.deleted_markers = []
        self.added_markers = []
        self._markers = {10: {"color": "Blue", "name": "old", "note": "", "duration": 1}}
        if apply_result is not None:
            self.ApplyGradeFromDRX = lambda *args: apply_result
        else:
            self.ApplyGradeFromDRX = None

    def GetMarkers(self):
        return dict(self._markers)

    def DeleteMarkerAtFrame(self, frame):
        self.deleted_markers.append(frame)
        self._markers.pop(frame, None)

    def AddMarker(self, frame, color, name, note, duration):
        self.added_markers.append((frame, color, name, note, duration))


class _FakeNodeGraph:
    def __init__(self, apply_result=None):
        self._apply_result = apply_result
        if apply_result is not None:
            self.ApplyGradeFromDRX = lambda *args: apply_result
        else:
            self.ApplyGradeFromDRX = None


class _FakeClip:
    def __init__(self, node_graph=None):
        self._node_graph = node_graph

    def GetNodeGraph(self):
        return self._node_graph


def test_apply_grade_from_drx_uses_timeline_api_list_form():
    timeline = _FakeTimeline(True)
    clip = _FakeClip()

    assert _apply_grade_from_drx(timeline, clip, "/tmp/test.drx", "item_001") is True


def test_apply_grade_from_drx_falls_back_to_node_graph():
    timeline = _FakeTimeline(None)
    clip = _FakeClip(_FakeNodeGraph(True))

    assert _apply_grade_from_drx(timeline, clip, "/tmp/test.drx", "item_001") is True


def test_apply_grade_from_drx_returns_false_when_no_api_available():
    timeline = _FakeTimeline(None)
    clip = _FakeClip(_FakeNodeGraph(None))

    assert _apply_grade_from_drx(timeline, clip, "/tmp/test.drx", "item_001") is False


def test_restore_timeline_overlays_clears_and_reapplies_markers(monkeypatch):
    timeline = _FakeTimeline(None)

    monkeypatch.setattr("giteo.deserializer._load_color", lambda project_dir: {})
    monkeypatch.setattr(
        "giteo.deserializer._load_markers",
        lambda project_dir: [
            type("Marker", (), {
                "frame": 25,
                "color": "Green",
                "name": "new",
                "note": "note",
                "duration": 2,
            })()
        ],
    )
    monkeypatch.setattr("giteo.deserializer._apply_color", lambda *args, **kwargs: None)

    restore_timeline_overlays(timeline, "/tmp/project")

    assert timeline.deleted_markers == [10]
    assert timeline.added_markers == [(25, "Green", "new", "note", 2)]
