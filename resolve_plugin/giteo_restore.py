"""Giteo: Switch Branch / Restore — Resolve Workspace > Scripts menu item.

Switches to a branch and restores the timeline state in Resolve.
The `resolve` variable is injected by DaVinci Resolve.
"""
import os
import sys
import traceback

try:
    _real = os.path.realpath(__file__)
except NameError:
    _real = None
if _real:
    _root = os.path.dirname(os.path.dirname(_real))
    if os.path.isdir(os.path.join(_root, "giteo")) and _root not in sys.path:
        sys.path.insert(0, _root)
else:
    _pf = os.path.expanduser("~/.giteo/package_path")
    if os.path.exists(_pf):
        with open(_pf) as _f:
            _root = _f.read().strip()
        if _root and os.path.isdir(os.path.join(_root, "giteo")) and _root not in sys.path:
            sys.path.insert(0, _root)


def main():
    from resolve_plugin.plugin_utils import (
        auto_save_current_timeline, check_resolve, get_project_dir, ask_choice,
        show_error, show_message, _log,
    )
    from giteo.core import git_checkout, git_current_branch, git_list_branches
    from giteo.deserializer import deserialize_timeline

    try:
        _resolve = resolve  # noqa: F821 — injected by DaVinci Resolve
    except NameError:
        _resolve = None
    if not check_resolve(_resolve):
        return

    project_dir = get_project_dir()
    if not project_dir:
        show_error("Giteo", "No giteo project found.\nRun 'giteo init <path>' from terminal.")
        return

    current = git_current_branch(project_dir)
    branches = git_list_branches(project_dir)
    _log(f"Current branch: {current}")
    _log(f"Available: {', '.join(branches)}")

    target = ask_choice(
        "Giteo: Switch Branch",
        f"Current: {current}\nSelect branch to restore:",
        branches,
    )
    if not target:
        _log("No branch selected — cancelled.")
        _log("To switch from CLI: giteo checkout <branch>")
        return
    if target != current:
        if not auto_save_current_timeline(
            _resolve, project_dir, f"switching to '{target}'"
        ):
            return
        try:
            git_checkout(project_dir, target)
            _log(f"Switched to '{target}'")
        except Exception as e:
            show_error("Giteo", f"Failed to switch branch: {e}")
            return

    project = _resolve.GetProjectManager().GetCurrentProject()
    timeline = project.GetCurrentTimeline()
    if timeline:
        deserialize_timeline(timeline, project, project_dir, resolve_app=_resolve)
        if target == current:
            show_message("Giteo", f"Restored timeline from '{target}'.")
        else:
            show_message("Giteo", f"Switched to '{target}' and restored timeline.")
    else:
        show_message("Giteo", f"On '{target}'.\nNo active timeline to restore.")


try:
    main()
except Exception:
    print(f"[giteo] SCRIPT ERROR:\n{traceback.format_exc()}")
