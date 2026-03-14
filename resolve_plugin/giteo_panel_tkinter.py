"""Giteo: Panel — Single unified UI for all Giteo operations.

Opens a tkinter window with buttons for Save, Branch, Switch, Merge, Push, Pull, Status.
Works on DaVinci Resolve Free (no Studio license required).
Run from Workspace > Scripts > Giteo - Panel.
"""
import os
import sys
import traceback
import tkinter as tk
from tkinter import scrolledtext

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
    try:
        _resolve = resolve  # noqa: F821
    except NameError:
        _resolve = None

    if _resolve is None:
        print("[giteo] This script must be run from DaVinci Resolve (Workspace > Scripts).")
        return

    from resolve_plugin.plugin_utils import (
        get_project_dir, ask_string, ask_choice,
        show_error, show_message, _log,
    )

    project_dir = get_project_dir()
    if not project_dir:
        show_error("Giteo", "No giteo project found.\nRun 'giteo init <path>' from terminal.")
        return

    # Create tkinter window
    root = tk.Tk()
    root.title("Giteo")
    root.geometry("340x480")
    root.resizable(False, True)
    root.lift()
    root.attributes("-topmost", True)

    # Branch label
    branch_var = tk.StringVar(value="Branch: —")
    branch_label = tk.Label(root, textvariable=branch_var, font=("Courier", 12, "bold"), pady=5)
    branch_label.pack(fill=tk.X, padx=10)

    def refresh_branch():
        try:
            from giteo.core import git_current_branch
            branch = git_current_branch(project_dir)
            branch_var.set(f"Branch: {branch}")
        except Exception as e:
            append_log(f"Error: {e}")

    # Log area
    log_frame = tk.LabelFrame(root, text="Log", padx=5, pady=5)
    log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

    log_text = scrolledtext.ScrolledText(log_frame, height=10, width=38, font=("Courier", 10))
    log_text.pack(fill=tk.BOTH, expand=True)
    log_text.config(state=tk.DISABLED)

    def append_log(msg):
        log_text.config(state=tk.NORMAL)
        log_text.insert(tk.END, msg + "\n")
        log_text.see(tk.END)
        log_text.config(state=tk.DISABLED)
        root.update()

    # Button frame
    btn_frame = tk.Frame(root)
    btn_frame.pack(fill=tk.X, padx=10, pady=5)

    def on_save():
        from giteo.serializer import serialize_timeline
        from giteo.core import git_add, git_commit, GitError

        project = _resolve.GetProjectManager().GetCurrentProject()
        timeline = project.GetCurrentTimeline()
        if not timeline:
            show_error("Giteo", "No timeline is currently active.")
            return
        msg = ask_string("Save Version", "Commit message:", initial="save version")
        if not msg:
            append_log("Save cancelled.")
            return
        append_log(f"Saving: {msg}")
        try:
            serialize_timeline(timeline, project, project_dir, resolve_app=_resolve)
            git_add(project_dir, ["timeline/", "assets/", ".giteo/", ".gitignore"])
            hash_val = git_commit(project_dir, f"giteo: {msg}")
            append_log(f"Saved. Commit: {hash_val}")
            refresh_branch()
        except GitError as e:
            if "nothing to commit" in str(e):
                append_log("Nothing to commit — unchanged.")
            else:
                append_log(f"Error: {e}")
                show_error("Giteo", str(e))

    def on_new_branch():
        from giteo.core import git_branch, git_current_branch, git_list_branches

        current = git_current_branch(project_dir)
        name = ask_string("New Branch", f"Current: {current}\nNew branch name:")
        if not name or not name.strip():
            append_log("New branch cancelled.")
            return
        name = name.strip()
        append_log(f"Creating branch '{name}'...")
        try:
            git_branch(project_dir, name)
            append_log(f"Switched to '{name}'.")
            refresh_branch()
            show_message("Giteo", f"Created branch '{name}'")
        except Exception as e:
            append_log(f"Error: {e}")
            show_error("Giteo", str(e))

    def on_switch():
        from giteo.core import git_checkout, git_current_branch, git_list_branches
        from giteo.deserializer import deserialize_timeline

        current = git_current_branch(project_dir)
        branches = git_list_branches(project_dir)
        target = ask_choice("Switch Branch", f"Current: {current}\nSelect branch:", branches)
        if not target:
            append_log("Switch cancelled.")
            return
        if target != current:
            append_log(f"Switching to '{target}'...")
            try:
                git_checkout(project_dir, target)
                append_log(f"Switched to '{target}'.")
                refresh_branch()
            except Exception as e:
                append_log(f"Error: {e}")
                show_error("Giteo", str(e))
                return
        else:
            append_log("Restoring timeline from current branch...")
        project = _resolve.GetProjectManager().GetCurrentProject()
        timeline = project.GetCurrentTimeline()
        if timeline:
            deserialize_timeline(timeline, project, project_dir)
            append_log("Timeline restored.")
            show_message("Giteo", f"Restored timeline from '{target}'.")
        else:
            append_log("No active timeline to restore.")

    def on_merge():
        from giteo.core import (
            git_add, git_commit, git_merge, git_is_clean,
            git_current_branch, git_list_branches, git_list_conflicted_files,
            git_checkout_theirs, GitError,
        )
        from giteo.serializer import serialize_timeline
        from giteo.deserializer import deserialize_timeline
        from giteo.validator import validate_project, format_issues

        current = git_current_branch(project_dir)
        branches = [b for b in git_list_branches(project_dir) if b != current]
        if not branches:
            append_log("No other branches to merge.")
            show_message("Giteo", "No other branches to merge.")
            return
        target = ask_choice("Merge Branch", f"Merging into '{current}':\nSelect branch:", branches)
        if not target:
            append_log("Merge cancelled.")
            return
        append_log(f"Merging '{target}' into '{current}'...")
        if not git_is_clean(project_dir):
            append_log("Auto-saving uncommitted changes...")
            project = _resolve.GetProjectManager().GetCurrentProject()
            timeline = project.GetCurrentTimeline()
            if timeline:
                serialize_timeline(timeline, project, project_dir, resolve_app=_resolve)
            git_add(project_dir, ["timeline/", "assets/", ".giteo/", ".gitignore"])
            try:
                git_commit(project_dir, f"giteo: auto-save before merging '{target}'")
                append_log("Auto-saved.")
            except GitError as e:
                if "nothing to commit" not in str(e):
                    append_log(f"Auto-save failed: {e}")
                    show_error("Giteo", str(e))
                    return
        success, output = git_merge(project_dir, target)
        if not success:
            conflicted = git_list_conflicted_files(project_dir)
            append_log(f"Conflicts in: {', '.join(conflicted)}")
            auto_resolvable = [f for f in conflicted if f.endswith(".drx") or f.startswith("timeline/")]
            non_resolvable = [f for f in conflicted if f not in auto_resolvable]
            if auto_resolvable and not non_resolvable:
                append_log("Auto-resolving conflicts...")
                try:
                    git_checkout_theirs(project_dir, auto_resolvable)
                    git_add(project_dir, auto_resolvable)
                    git_commit(project_dir, f"giteo: merged '{target}' (auto-resolved)")
                    success = True
                    append_log("Auto-resolved.")
                except GitError as e:
                    append_log(f"Auto-resolve failed: {e}")
        if success:
            issues = validate_project(project_dir)
            if issues:
                append_log(format_issues(issues))
            else:
                append_log(f"Merged '{target}' cleanly.")
            project = _resolve.GetProjectManager().GetCurrentProject()
            timeline = project.GetCurrentTimeline()
            if timeline:
                deserialize_timeline(timeline, project, project_dir)
                append_log("Timeline restored.")
            refresh_branch()
            show_message("Giteo", f"Merged '{target}' into '{current}'.")
        else:
            append_log("Merge has conflicts. Use 'giteo merge' from terminal for AI resolution.")
            show_error("Giteo", f"Merge conflicts.\nUse terminal: giteo merge {target}")

    def on_push():
        from giteo.core import git_current_branch, git_push, GitError

        branch = git_current_branch(project_dir)
        append_log(f"Pushing '{branch}'...")
        try:
            output = git_push(project_dir, "origin", branch)
            append_log(f"Pushed. {output.strip()}")
            show_message("Giteo", f"Pushed '{branch}' to origin.")
        except GitError as e:
            err = str(e)
            append_log(f"Push failed: {err}")
            if "No configured" in err or "does not appear" in err:
                show_error("Giteo: Push", "No remote configured.\nFrom terminal: git remote add origin <url>")
            else:
                show_error("Giteo: Push", str(e))

    def on_pull():
        from giteo.core import git_current_branch, git_pull, GitError
        from giteo.deserializer import deserialize_timeline

        branch = git_current_branch(project_dir)
        append_log(f"Pulling '{branch}'...")
        try:
            output = git_pull(project_dir, "origin", branch)
            append_log(f"Pulled. {output.strip()}")
        except GitError as e:
            err = str(e)
            append_log(f"Pull failed: {err}")
            if "No configured" in err or "does not appear" in err:
                show_error("Giteo: Pull", "No remote configured.\nFrom terminal: git remote add origin <url>")
            else:
                show_error("Giteo: Pull", str(e))
            return
        project = _resolve.GetProjectManager().GetCurrentProject()
        timeline = project.GetCurrentTimeline()
        if timeline:
            deserialize_timeline(timeline, project, project_dir)
            append_log("Timeline restored.")
        show_message("Giteo", f"Pulled '{branch}' and restored timeline.")

    def on_status():
        from giteo.core import git_current_branch, git_status, git_log

        branch = git_current_branch(project_dir)
        status = git_status(project_dir)
        log_out = git_log(project_dir, max_count=5)
        append_log(f"Branch: {branch}")
        append_log(status.strip() if status else "Working tree clean")
        append_log("Recent:\n" + (log_out or ""))

    # Create buttons
    tk.Button(btn_frame, text="Save Version", command=on_save, width=36).pack(pady=2)

    row1 = tk.Frame(btn_frame)
    row1.pack(fill=tk.X, pady=2)
    tk.Button(row1, text="New Branch", command=on_new_branch, width=17).pack(side=tk.LEFT, padx=(0, 2))
    tk.Button(row1, text="Switch Branch", command=on_switch, width=17).pack(side=tk.LEFT)

    row2 = tk.Frame(btn_frame)
    row2.pack(fill=tk.X, pady=2)
    tk.Button(row2, text="Push", command=on_push, width=17).pack(side=tk.LEFT, padx=(0, 2))
    tk.Button(row2, text="Pull", command=on_pull, width=17).pack(side=tk.LEFT)

    tk.Button(btn_frame, text="Merge Branch", command=on_merge, width=36).pack(pady=2)
    tk.Button(btn_frame, text="Status", command=on_status, width=36).pack(pady=2)

    # Initialize
    refresh_branch()
    append_log("Giteo panel ready.")

    # Run
    root.mainloop()


try:
    main()
except Exception:
    print(f"[giteo] PANEL ERROR:\n{traceback.format_exc()}")
