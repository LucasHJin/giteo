"""Tests for Resolve plugin utilities."""

from giteo.core import GitError
from resolve_plugin import plugin_utils


class _FakeTimeline:
    def GetName(self):
        return "Color Pass"


class _FakeProject:
    def __init__(self, timeline):
        self._timeline = timeline

    def GetCurrentTimeline(self):
        return self._timeline


class _FakeProjectManager:
    def __init__(self, project):
        self._project = project

    def GetCurrentProject(self):
        return self._project


class _FakeResolve:
    def __init__(self, timeline):
        self._pm = _FakeProjectManager(_FakeProject(timeline))

    def GetProjectManager(self):
        return self._pm


def test_auto_save_current_timeline_serializes_and_commits(monkeypatch):
    """Auto-save should serialize the active timeline and create a commit."""
    calls = []
    resolve = _FakeResolve(_FakeTimeline())

    def fake_serialize_timeline(timeline, project, project_dir, resolve_app=None):
        calls.append(("serialize", timeline.GetName(), project_dir, resolve_app))

    def fake_git_add(project_dir, paths):
        calls.append(("add", project_dir, tuple(paths)))

    def fake_git_commit(project_dir, message):
        calls.append(("commit", project_dir, message))
        return "abc1234"

    monkeypatch.setattr("giteo.serializer.serialize_timeline", fake_serialize_timeline)
    monkeypatch.setattr("giteo.core.git_add", fake_git_add)
    monkeypatch.setattr("giteo.core.git_commit", fake_git_commit)

    ok = plugin_utils.auto_save_current_timeline(
        resolve, "/tmp/project", "switching to 'main'"
    )

    assert ok is True
    assert calls == [
        ("serialize", "Color Pass", "/tmp/project", resolve),
        ("add", "/tmp/project", ("timeline/", "assets/", ".giteo/", ".gitignore")),
        ("commit", "/tmp/project", "giteo: auto-save before switching to 'main'"),
    ]


def test_auto_save_current_timeline_treats_nothing_to_commit_as_success(monkeypatch):
    """A no-op auto-save should not block branch operations."""
    resolve = _FakeResolve(_FakeTimeline())

    def fake_git_commit(project_dir, message):
        raise GitError("nothing to commit")

    monkeypatch.setattr("giteo.serializer.serialize_timeline", lambda *args, **kwargs: None)
    monkeypatch.setattr("giteo.core.git_add", lambda *args, **kwargs: None)
    monkeypatch.setattr("giteo.core.git_commit", fake_git_commit)

    ok = plugin_utils.auto_save_current_timeline(
        resolve, "/tmp/project", "merging 'color' into 'main'"
    )

    assert ok is True


def test_auto_save_current_timeline_allows_missing_timeline(monkeypatch):
    """If no timeline is open, branch operations should continue."""
    calls = []
    resolve = _FakeResolve(None)

    monkeypatch.setattr(
        "giteo.serializer.serialize_timeline",
        lambda *args, **kwargs: calls.append("serialize"),
    )
    monkeypatch.setattr("giteo.core.git_add", lambda *args, **kwargs: calls.append("add"))
    monkeypatch.setattr("giteo.core.git_commit", lambda *args, **kwargs: calls.append("commit"))

    ok = plugin_utils.auto_save_current_timeline(
        resolve, "/tmp/project", "switching to 'main'"
    )

    assert ok is True
    assert calls == []
