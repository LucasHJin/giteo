"""Giteo: Merge — Resolve Workspace > Scripts menu item.

Merges a branch into the current branch and restores the timeline.
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
    from giteo.core import (
        git_add, git_checkout_theirs, git_commit, git_current_branch,
        git_is_clean, git_list_branches, git_list_conflicted_files,
        git_merge, GitError,
    )
    from giteo.deserializer import deserialize_timeline
    from giteo.validator import validate_project, format_issues

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
    other_branches = [b for b in branches if b != current]

    if not other_branches:
        show_message("Giteo", "No other branches to merge.")
        return

    _log(f"Current branch: {current}")
    _log(f"Merge candidates: {', '.join(other_branches)}")

    branch = ask_choice(
        "Giteo: Merge Branch",
        f"Current: {current}\nSelect branch to merge into '{current}':",
        other_branches,
    )
    if not branch:
        _log("No branch selected — cancelled.")
        _log("To merge from CLI: giteo merge <branch>")
        return

    # Always serialize the active timeline before merge. Resolve changes exist
    # in memory until saved, so git status cannot reliably detect them.
    if not auto_save_current_timeline(
        _resolve, project_dir, f"merging '{branch}' into '{current}'"
    ):
        return

    # Keep the existing safeguard for already-dirty project files on disk.
    if not git_is_clean(project_dir):
        _log("Working directory still has uncommitted giteo files — committing them...")
        git_add(project_dir, ["timeline/", "assets/", ".giteo/", ".gitignore"])
        try:
            git_commit(project_dir, f"giteo: auto-save before merging '{branch}'")
        except GitError as e:
            if "nothing to commit" not in str(e):
                show_error("Giteo", f"Auto-save failed:\n{e}")
                return

    _log(f"Merging '{branch}' into '{current}'...")
    success, output = git_merge(project_dir, branch)

    if not success:
        # Try to auto-resolve: DRX files are binary and should take the
        # incoming branch's version; domain JSON conflicts from parallel
        # serialization can also be resolved by taking "theirs"
        conflicted = git_list_conflicted_files(project_dir)
        _log(f"Conflicts in: {', '.join(conflicted)}")

        auto_resolvable = [f for f in conflicted
                           if f.endswith(".drx") or f.startswith("timeline/")]
        non_resolvable = [f for f in conflicted if f not in auto_resolvable]

        if auto_resolvable and not non_resolvable:
            _log(f"Auto-resolving {len(auto_resolvable)} domain file conflict(s) "
                 f"(taking '{branch}' version)...")
            try:
                git_checkout_theirs(project_dir, auto_resolvable)
                git_add(project_dir, auto_resolvable)
                git_commit(project_dir,
                           f"giteo: merged '{branch}' into '{current}' (auto-resolved)")
                success = True
                output = "Auto-resolved domain file conflicts."
            except GitError as e:
                _log(f"Auto-resolve failed: {e}")

    if success:
        issues = validate_project(project_dir)
        if issues:
            msg = f"Merge succeeded with issues:\n{format_issues(issues)}"
        else:
            msg = f"Merged '{branch}' into '{current}' cleanly."

        project = _resolve.GetProjectManager().GetCurrentProject()
        timeline = project.GetCurrentTimeline()
        if timeline:
            deserialize_timeline(timeline, project, project_dir, resolve_app=_resolve)
            msg += "\n\nTimeline restored."

        show_message("Giteo", msg)
    else:
        show_error(
            "Giteo",
            f"Merge has conflicts.\n\n{output}\n\n"
            f"Use 'giteo merge {branch}' from terminal for AI-assisted resolution.",
        )


try:
    main()
except Exception:
    print(f"[giteo] SCRIPT ERROR:\n{traceback.format_exc()}")
