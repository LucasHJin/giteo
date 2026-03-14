"""Tests for DRX grade restore fallbacks."""

from giteo.deserializer import _apply_grade_from_drx


class _FakeTimeline:
    def __init__(self, apply_result=None):
        self._apply_result = apply_result
        if apply_result is not None:
            self.ApplyGradeFromDRX = lambda *args: apply_result
        else:
            self.ApplyGradeFromDRX = None


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
