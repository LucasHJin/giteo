"""Vit Panel Launcher — Resolve entry point for the PySide6 panel.

Runs inside DaVinci Resolve's Python environment. Discovers the project
directory, then opens a socket server and spawns the PySide6 UI as a
subprocess. All Resolve-dependent operations (serialize, deserialize)
are handled here; the subprocess sends JSON requests over the socket.

Run from Workspace > Scripts > Vit - Panel.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import traceback

# Bootstrap: find the vit package
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


def _log(msg):
    print(f"[vit] {msg}")


def _find_system_python():
    """Find a system Python 3 that has PySide6 installed."""
    candidates = [
        sys.executable,
        "/usr/local/bin/python3",
        "/usr/bin/python3",
        "/opt/homebrew/bin/python3",
    ]
    # Check vit project venv first (from install-resolve package_path)
    _pf = os.path.expanduser("~/.vit/package_path")
    if os.path.exists(_pf):
        with open(_pf) as _f:
            pkg_root = _f.read().strip()
        for venv_name in (".venv", "venv", "env"):
            venv_py = os.path.join(pkg_root, venv_name, "bin", "python3")
            if os.path.exists(venv_py):
                candidates.insert(1, venv_py)  # High priority
                break
    # Check versioned Pythons (3.9-3.13) in common locations
    import glob
    for pattern in [
        "/opt/homebrew/opt/python@3.*/bin/python3.*",
        "/opt/homebrew/bin/python3.*",
        "/usr/local/bin/python3.*",
    ]:
        for p in sorted(glob.glob(pattern), reverse=True):
            if not p.endswith(("-config", "-intel64")):
                candidates.append(p)
    # Also check common virtualenv/pyenv locations
    home = os.path.expanduser("~")
    candidates.append(os.path.join(home, ".pyenv", "shims", "python3"))

    for python in candidates:
        if not os.path.exists(python):
            continue
        try:
            result = subprocess.run(
                [python, "-c", "import PySide6; print('ok')"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and "ok" in result.stdout:
                return python
        except (subprocess.TimeoutExpired, OSError):
            continue
    return None


def handle_request(request, resolve_app, project_dir):
    """Handle a JSON request from the Qt subprocess.

    Returns a JSON-serializable response dict.
    """
    action = request.get("action")

    try:
        if action == "ping":
            return {"ok": True}

        elif action == "get_branch":
            from vit.core import git_current_branch
            branch = git_current_branch(project_dir)
            return {"ok": True, "branch": branch}

        elif action == "save":
            from vit.serializer import serialize_timeline
            from vit.core import git_add, git_commit, GitError

            project = resolve_app.GetProjectManager().GetCurrentProject()
            timeline = project.GetCurrentTimeline()
            if not timeline:
                return {"ok": False, "error": "No timeline is currently active."}

            msg = request.get("message", "save version")
            serialize_timeline(timeline, project, project_dir, resolve_app=resolve_app)
            git_add(project_dir, ["timeline/", "assets/", ".vit/", ".gitignore"])
            try:
                hash_val = git_commit(project_dir, f"vit: {msg}")
                return {"ok": True, "hash": hash_val, "message": msg}
            except GitError as e:
                if "nothing to commit" in str(e):
                    return {"ok": True, "message": "Nothing to commit — unchanged."}
                return {"ok": False, "error": str(e)}

        elif action == "new_branch":
            from vit.core import git_branch
            name = request.get("name", "").strip()
            if not name:
                return {"ok": False, "error": "No branch name provided."}
            git_branch(project_dir, name)
            return {"ok": True, "branch": name}

        elif action == "list_branches":
            from vit.core import git_list_branches, git_current_branch
            branches = git_list_branches(project_dir)
            current = git_current_branch(project_dir)
            return {"ok": True, "branches": branches, "current": current}

        elif action == "switch_branch":
            from vit.core import git_checkout, git_current_branch
            from vit.deserializer import deserialize_timeline

            target = request.get("branch", "")
            current = git_current_branch(project_dir)
            if target and target != current:
                git_checkout(project_dir, target)

            project = resolve_app.GetProjectManager().GetCurrentProject()
            timeline = project.GetCurrentTimeline()
            if timeline:
                deserialize_timeline(timeline, project, project_dir, resolve_app=resolve_app)
                return {"ok": True, "branch": target, "restored": True}
            return {"ok": True, "branch": target, "restored": False}

        elif action == "merge":
            from vit.core import (
                git_add, git_commit, git_merge, git_is_clean,
                git_current_branch, git_list_conflicted_files,
                git_checkout_theirs, GitError,
            )
            from vit.serializer import serialize_timeline
            from vit.deserializer import deserialize_timeline
            from vit.validator import validate_project, format_issues

            target = request.get("branch", "")
            current = git_current_branch(project_dir)

            # Auto-save if dirty
            if not git_is_clean(project_dir):
                project = resolve_app.GetProjectManager().GetCurrentProject()
                timeline = project.GetCurrentTimeline()
                if timeline:
                    serialize_timeline(timeline, project, project_dir, resolve_app=resolve_app)
                git_add(project_dir, ["timeline/", "assets/", ".vit/", ".gitignore"])
                try:
                    git_commit(project_dir, f"vit: auto-save before merging '{target}'")
                except GitError as e:
                    if "nothing to commit" not in str(e):
                        return {"ok": False, "error": str(e)}

            success, output = git_merge(project_dir, target)
            if not success:
                conflicted = git_list_conflicted_files(project_dir)
                auto_resolvable = [f for f in conflicted if f.endswith(".drx") or f.startswith("timeline/")]
                non_resolvable = [f for f in conflicted if f not in auto_resolvable]
                if auto_resolvable and not non_resolvable:
                    try:
                        git_checkout_theirs(project_dir, auto_resolvable)
                        git_add(project_dir, auto_resolvable)
                        git_commit(project_dir, f"vit: merged '{target}' (auto-resolved)")
                        success = True
                    except GitError as e:
                        return {"ok": False, "error": f"Auto-resolve failed: {e}"}

            if success:
                issues = validate_project(project_dir)
                project = resolve_app.GetProjectManager().GetCurrentProject()
                timeline = project.GetCurrentTimeline()
                if timeline:
                    deserialize_timeline(timeline, project, project_dir, resolve_app=resolve_app)
                issue_text = format_issues(issues) if issues else ""
                return {"ok": True, "branch": target, "current": current, "issues": issue_text}
            else:
                return {"ok": False, "error": f"Merge conflicts. Use terminal: vit merge {target}"}

        elif action == "push":
            from vit.core import git_current_branch, git_push, GitError
            branch = git_current_branch(project_dir)
            try:
                output = git_push(project_dir, "origin", branch)
                return {"ok": True, "branch": branch, "output": output.strip()}
            except GitError as e:
                return {"ok": False, "error": str(e)}

        elif action == "pull":
            from vit.core import git_current_branch, git_pull, GitError
            from vit.deserializer import deserialize_timeline

            branch = git_current_branch(project_dir)
            try:
                output = git_pull(project_dir, "origin", branch)
            except GitError as e:
                return {"ok": False, "error": str(e)}

            project = resolve_app.GetProjectManager().GetCurrentProject()
            timeline = project.GetCurrentTimeline()
            if timeline:
                deserialize_timeline(timeline, project, project_dir, resolve_app=resolve_app)
            return {"ok": True, "branch": branch, "output": output.strip()}

        elif action == "status":
            from vit.core import git_current_branch, git_status, git_log
            branch = git_current_branch(project_dir)
            status = git_status(project_dir)
            log_out = git_log(project_dir, max_count=5)
            return {
                "ok": True,
                "branch": branch,
                "status": status.strip() if status else "Working tree clean",
                "log": log_out or "",
            }

        elif action == "get_changes":
            from vit.differ import get_changes_by_category
            from vit.serializer import serialize_timeline
            try:
                # Re-serialize current timeline state before diffing
                project = resolve_app.GetProjectManager().GetCurrentProject()
                timeline = project.GetCurrentTimeline()
                if timeline:
                    serialize_timeline(timeline, project, project_dir, resolve_app=resolve_app)
                changes = get_changes_by_category(project_dir, "HEAD")
                return {"ok": True, "changes": changes}
            except Exception as e:
                return {"ok": True, "changes": {"audio": [], "video": [], "color": []}}

        elif action == "get_commit_history":
            from vit.core import git_log_with_changes, categorize_commit
            limit = request.get("limit", 10)
            commits = git_log_with_changes(project_dir, max_count=limit)
            # Add category to each commit
            for commit in commits:
                commit["category"] = categorize_commit(commit.get("files_changed", []))
            return {"ok": True, "commits": commits}

        elif action == "compare_branches":
            from vit.differ import get_branch_diff_by_category
            branch_a = request.get("branch_a", "")
            branch_b = request.get("branch_b", "")
            if not branch_a or not branch_b:
                return {"ok": False, "error": "Both branch_a and branch_b required"}
            changes_a, changes_b = get_branch_diff_by_category(project_dir, branch_a, branch_b)
            return {
                "ok": True,
                "branch_a": branch_a,
                "branch_b": branch_b,
                "changes_a": changes_a,
                "changes_b": changes_b,
            }

        elif action == "analyze_merge":
            from vit.differ import get_branch_diff_by_category
            from vit.ai_merge import analyze_branch_comparison
            branch_a = request.get("branch_a", "")
            branch_b = request.get("branch_b", "")
            if not branch_a or not branch_b:
                return {"ok": False, "error": "Both branch_a and branch_b required"}
            changes_a, changes_b = get_branch_diff_by_category(project_dir, branch_a, branch_b)
            try:
                analysis = analyze_branch_comparison(branch_a, branch_b, changes_a, changes_b)
                return {
                    "ok": True,
                    "branch_a": branch_a,
                    "branch_b": branch_b,
                    "changes_a": changes_a,
                    "changes_b": changes_b,
                    "analysis": analysis,
                }
            except Exception as e:
                return {
                    "ok": True,
                    "branch_a": branch_a,
                    "branch_b": branch_b,
                    "changes_a": changes_a,
                    "changes_b": changes_b,
                    "analysis": {"recommendation": "Manual review required", "explanation": str(e)},
                }

        elif action == "classify_commit":
            from vit.ai_merge import classify_commit_type
            commit_hash = request.get("hash", "")
            files_changed = request.get("files", [])
            message = request.get("message", "")
            try:
                category = classify_commit_type(commit_hash, files_changed, message)
                return {"ok": True, "hash": commit_hash, "category": category}
            except Exception as e:
                from vit.core import categorize_commit
                fallback = categorize_commit(files_changed)
                return {"ok": True, "hash": commit_hash, "category": fallback}

        elif action == "get_commit_graph":
            from vit.core import git_log_with_topology
            limit = request.get("limit", 30)
            try:
                data = git_log_with_topology(project_dir, max_count=limit)
                # Assign color indices to branches dynamically
                branch_colors = {}
                color_idx = 0
                for branch in data.get("branches", []):
                    if branch in ("main", "master"):
                        branch_colors[branch] = 3  # orange
                    else:
                        branch_colors[branch] = color_idx % 3  # rotate R(0), G(1), B(2)
                        color_idx += 1
                return {
                    "ok": True,
                    "commits": data.get("commits", []),
                    "branches": data.get("branches", []),
                    "branch_colors": branch_colors,
                    "head": data.get("head", ""),
                }
            except Exception as e:
                return {"ok": False, "error": str(e)}

        elif action == "quit":
            return {"ok": True, "quit": True}

        else:
            return {"ok": False, "error": f"Unknown action: {action}"}

    except Exception as e:
        return {"ok": False, "error": str(e)}


def run_server(resolve_app, project_dir):
    """Start a socket server, spawn the Qt subprocess, and handle requests."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    port = server.getsockname()[1]
    server.listen(1)
    server.settimeout(30)  # 30s timeout for initial connection

    _log(f"Launcher listening on port {port}")

    # Find system Python with PySide6
    python = _find_system_python()
    if not python:
        _log("ERROR: PySide6 not found. Install it: pip install PySide6")
        # Try tkinter fallback
        try:
            _log("Falling back to tkinter panel...")
            server.close()
            from resolve_plugin.vit_panel_tkinter import main as tkinter_main
            tkinter_main()
            return
        except ImportError:
            _log("No fallback available. Install PySide6: pip install PySide6")
            server.close()
            return

    # Spawn Qt subprocess
    # Find vit_panel_qt.py — __file__ may not be defined in Resolve
    qt_script = None
    try:
        qt_script = os.path.join(os.path.dirname(os.path.realpath(__file__)), "vit_panel_qt.py")
    except NameError:
        pass
    if not qt_script or not os.path.exists(qt_script):
        # Use saved package path from install-resolve
        _pf = os.path.expanduser("~/.vit/package_path")
        if os.path.exists(_pf):
            with open(_pf) as f:
                pkg_root = f.read().strip()
            qt_script = os.path.join(pkg_root, "resolve_plugin", "vit_panel_qt.py")

    _log(f"Spawning Qt panel: {python} {qt_script}")
    proc = subprocess.Popen(
        [python, qt_script, "--project-dir", project_dir, "--port", str(port)],
        stdout=None,
        stderr=None,
    )

    conn = None
    try:
        conn, addr = server.accept()
        _log(f"Qt panel connected from {addr}")
        server.settimeout(None)
        conn.settimeout(None)

        buf = b""
        should_quit = False
        while not should_quit:
            data = conn.recv(4096)
            if not data:
                _log("Qt panel disconnected.")
                break
            buf += data

            # Process complete JSON messages (newline-delimited)
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    request = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError as e:
                    _log(f"Bad JSON: {e}")
                    continue

                response = handle_request(request, resolve_app, project_dir)
                conn.sendall((json.dumps(response) + "\n").encode("utf-8"))

                if response.get("quit"):
                    should_quit = True
                    break

    except socket.timeout:
        _log("Qt panel did not connect within timeout.")
        # Check if subprocess crashed
        if proc.poll() is not None:
            _log(f"Qt subprocess exited with code {proc.returncode}")
    except Exception as e:
        _log(f"Server error: {e}")
        import traceback as tb
        _log(tb.format_exc())
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        server.close()
        proc.terminate()
        _log("Launcher done.")


def main():
    try:
        _resolve = resolve  # noqa: F821
    except NameError:
        _resolve = None

    if _resolve is None:
        _log("This script must be run from DaVinci Resolve (Workspace > Scripts).")
        return

    from resolve_plugin.plugin_utils import get_project_dir, show_error

    project_dir = get_project_dir()
    if not project_dir:
        show_error("Vit", "No vit project found.\nRun 'vit init <path>' from terminal.")
        return

    run_server(_resolve, project_dir)


try:
    main()
except Exception:
    print(f"[vit] LAUNCHER ERROR:\n{traceback.format_exc()}")
