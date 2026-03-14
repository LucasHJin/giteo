"""Shared utilities for DaVinci Resolve plugin scripts.

Provides dialogs (PySide6 preferred, tkinter fallback) and project directory
discovery.

IMPORTANT: Resolve runs scripts in its own Python environment. Dialogs
may or may not work depending on the Resolve version and OS.
All dialogs have print()-based fallbacks so scripts never silently fail.
"""

import os
import sys
import traceback
from datetime import datetime

GITEO_USER_DIR = os.path.expanduser("~/.giteo")
LAST_PROJECT_FILE = os.path.join(GITEO_USER_DIR, "last_project")


def _save_last_project(project_dir):
    os.makedirs(GITEO_USER_DIR, exist_ok=True)
    with open(LAST_PROJECT_FILE, "w") as f:
        f.write(project_dir)


def _log(msg):
    """Print to Resolve's console."""
    print(f"[giteo] {msg}")


def _has_pyside6():
    """Check if PySide6 is available."""
    try:
        import PySide6
        return True
    except ImportError:
        return False


def get_project_dir():
    """Find the giteo project directory.

    Checks in order:
      1. GITEO_PROJECT_DIR environment variable
      2. ~/.giteo/last_project saved path
      3. Directory picker dialog (PySide6 or tkinter)
    """
    # 1. Env var
    env_dir = os.environ.get("GITEO_PROJECT_DIR")
    if env_dir and os.path.isdir(os.path.join(env_dir, ".giteo")):
        _save_last_project(env_dir)
        return env_dir

    # 2. Last used project
    if os.path.exists(LAST_PROJECT_FILE):
        with open(LAST_PROJECT_FILE) as f:
            last_dir = f.read().strip()
        if last_dir and os.path.isdir(os.path.join(last_dir, ".giteo")):
            return last_dir

    # 3. Ask with dialog
    selected = None

    if _has_pyside6():
        try:
            from PySide6.QtWidgets import QApplication, QFileDialog
            app = QApplication.instance() or QApplication(sys.argv)
            selected = QFileDialog.getExistingDirectory(None, "Select Giteo Project Directory")
        except Exception as e:
            _log(f"PySide6 dialog failed: {e}")

    if not selected:
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            selected = filedialog.askdirectory(title="Select Giteo Project Directory")
            root.destroy()
        except Exception as e:
            _log(f"Tkinter dialog failed: {e}")

    if not selected:
        _log("Set GITEO_PROJECT_DIR env var or create ~/.giteo/last_project with the path.")
        return None

    if not os.path.isdir(os.path.join(selected, ".giteo")):
        show_error(
            "Not a giteo project",
            f"'{selected}' has no .giteo folder.\nRun 'giteo init' from terminal first.",
        )
        return None
    _save_last_project(selected)
    return selected


def show_message(title, message):
    """Show an info dialog. Falls back to print()."""
    _log(message)
    if _has_pyside6():
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.information(None, title, message)
            return
        except Exception:
            pass
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(title, message)
        root.destroy()
    except Exception:
        pass


def show_error(title, message):
    """Show an error dialog. Falls back to print()."""
    _log(f"ERROR: {message}")
    if _has_pyside6():
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, title, message)
            return
        except Exception:
            pass
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
    except Exception:
        pass


def ask_string(title, prompt, initial=""):
    """Ask user for a text string via dialog. Returns initial value on failure."""
    if _has_pyside6():
        try:
            from PySide6.QtWidgets import QApplication, QInputDialog
            app = QApplication.instance() or QApplication(sys.argv)
            text, ok = QInputDialog.getText(None, title, prompt, text=initial)
            if ok:
                return text
            return None
        except Exception as e:
            _log(f"PySide6 dialog failed ({e}), trying tkinter...")

    try:
        import tkinter as tk
        from tkinter import simpledialog

        root = tk.Tk()
        root.withdraw()
        result = simpledialog.askstring(title, prompt, parent=root, initialvalue=initial)
        root.destroy()
        if result is not None:
            return result
        return None  # user clicked Cancel
    except Exception as e:
        _log(f"Dialog failed ({e}), using default: '{initial}'")
        return initial if initial else None


def ask_choice(title, prompt, choices):
    """Ask user to pick from a list via dialog. Returns the selected string."""
    if not choices:
        return None

    if _has_pyside6():
        try:
            from PySide6.QtWidgets import QApplication, QInputDialog
            app = QApplication.instance() or QApplication(sys.argv)
            item, ok = QInputDialog.getItem(None, title, prompt, choices, 0, False)
            if ok and item:
                return item
            return None
        except Exception as e:
            _log(f"PySide6 dialog failed ({e}), trying tkinter...")

    try:
        import tkinter as tk

        root = tk.Tk()
        root.title(title)
        root.geometry("350x400")
        root.resizable(False, True)
        root.lift()
        root.attributes("-topmost", True)

        selected = [None]

        tk.Label(root, text=prompt, font=("Helvetica", 13), pady=10, wraplength=300).pack()

        frame = tk.Frame(root)
        frame.pack(fill=tk.BOTH, expand=True, padx=15)

        listbox = tk.Listbox(
            frame, selectmode=tk.SINGLE, font=("Courier", 12), activestyle="dotbox"
        )
        scrollbar = tk.Scrollbar(frame, orient=tk.VERTICAL, command=listbox.yview)
        listbox.config(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        for c in choices:
            listbox.insert(tk.END, c)
        listbox.selection_set(0)

        def on_ok():
            sel = listbox.curselection()
            if sel:
                selected[0] = choices[sel[0]]
            root.destroy()

        listbox.bind("<Double-1>", lambda _: on_ok())

        btn_frame = tk.Frame(root)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="OK", width=8, command=on_ok).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Cancel", width=8, command=root.destroy).pack(
            side=tk.LEFT, padx=5
        )

        root.mainloop()
        return selected[0]
    except Exception as e:
        _log(f"Dialog failed ({e}). Use the giteo CLI instead:")
        _log(f"  Choices were: {', '.join(choices)}")
        return None


def check_resolve(resolve_var):
    """Verify the resolve object is valid. Returns True if OK."""
    if resolve_var is None:
        show_error(
            "Giteo",
            "This script must be run from DaVinci Resolve.\n(Workspace > Scripts menu)",
        )
        return False
    return True


def auto_save_current_timeline(resolve_var, project_dir, reason):
    """Serialize and commit the active timeline before changing git state.

    Resolve timeline edits live in-memory until giteo serializes them, so git
    status alone cannot detect unsaved timeline changes.
    """
    try:
        from giteo.core import GitError, git_add, git_commit
        from giteo.serializer import serialize_timeline
    except Exception as e:
        show_error("Giteo", f"Could not load auto-save helpers:\n{e}")
        return False

    try:
        project = resolve_var.GetProjectManager().GetCurrentProject()
        timeline = project.GetCurrentTimeline() if project else None
    except Exception as e:
        show_error("Giteo", f"Could not access the current Resolve project:\n{e}")
        return False

    if not project or not timeline:
        _log("No active timeline available for auto-save.")
        return True

    timeline_name = timeline.GetName() or "untitled"
    _log(f"Auto-saving timeline '{timeline_name}' before {reason}...")

    try:
        serialize_timeline(timeline, project, project_dir, resolve_app=resolve_var)
        git_add(project_dir, ["timeline/", "assets/", ".giteo/", ".gitignore"])
        commit_hash = git_commit(project_dir, f"giteo: auto-save before {reason}")
        if commit_hash:
            _log(f"Auto-saved current timeline ({commit_hash}).")
        else:
            _log("Auto-saved current timeline.")
        return True
    except GitError as e:
        if "nothing to commit" in str(e):
            _log("Timeline already matches the current branch snapshot.")
            return True
        show_error("Giteo", f"Auto-save failed:\n{e}")
        return False
    except Exception as e:
        show_error("Giteo", f"Auto-save failed:\n{e}")
        return False
