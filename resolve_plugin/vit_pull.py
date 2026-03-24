"""Vit: Pull & Restore — Resolve Workspace > Scripts menu item.

Pulls the latest changes from the remote and restores the timeline in Resolve.
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
    if os.path.isdir(os.path.join(_root, "vit")) and _root not in sys.path:
        sys.path.insert(0, _root)
else:
    _pf = os.path.expanduser("~/.vit/package_path")
    if os.path.exists(_pf):
        with open(_pf) as _f:
            _root = _f.read().strip()
        if _root and os.path.isdir(os.path.join(_root, "vit")) and _root not in sys.path:
            sys.path.insert(0, _root)


def main():
    from resolve_plugin.plugin_utils import (
        check_resolve, get_project_dir, show_error, show_message, _log,
    )
    from vit.core import git_current_branch, git_pull, GitError
    from vit.deserializer import deserialize_timeline

    try:
        _resolve = resolve  # noqa: F821 — injected by DaVinci Resolve
    except NameError:
        _resolve = None
    if not check_resolve(_resolve):
        return

    project_dir = get_project_dir()
    if not project_dir:
        show_error("Vit", "No vit project found.\nRun 'vit init <path>' from terminal.")
        return

    branch = git_current_branch(project_dir)
    _log(f"Pulling '{branch}' from origin...")

    try:
        output = git_pull(project_dir, "origin", branch)
        _log(f"Pull output: {output.strip()}")
    except GitError as e:
        error_msg = str(e)
        if "No configured" in error_msg or "does not appear to be a git repository" in error_msg:
            show_error(
                "Vit: Pull",
                f"No remote configured.\n\n"
                f"From terminal, run:\n"
                f"  cd {project_dir}\n"
                f"  git remote add origin <your-github-url>\n"
                f"  vit pull",
            )
        else:
            show_error("Vit: Pull", f"Pull failed:\n{error_msg}")
        return

    project = _resolve.GetProjectManager().GetCurrentProject()
    timeline = project.GetCurrentTimeline()
    if timeline:
        deserialize_timeline(timeline, project, project_dir, resolve_app=_resolve)
        show_message("Vit: Pull", f"Pulled latest for '{branch}' and restored timeline.\n\n{output.strip()}")
    else:
        show_message("Vit: Pull", f"Pulled latest for '{branch}'.\nNo active timeline to restore.\n\n{output.strip()}")


try:
    main()
except Exception:
    print(f"[vit] SCRIPT ERROR:\n{traceback.format_exc()}")
