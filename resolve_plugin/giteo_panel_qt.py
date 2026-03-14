"""Giteo Panel — PySide6 UI subprocess.

This runs as a standalone process spawned by giteo_panel_launcher.py.
Communicates with the launcher via a JSON-over-TCP socket for operations
that require the DaVinci Resolve API (serialize, deserialize).

Usage: python giteo_panel_qt.py --project-dir /path/to/project --port 12345
"""
import argparse
import json
import socket
import sys
import threading
from functools import partial

from PySide6.QtCore import Qt, Signal, QObject, QThread, Slot
from PySide6.QtGui import QFont, QColor, QPalette, QIcon
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTextEdit, QLineEdit, QDialog, QDialogButtonBox,
    QListWidget, QListWidgetItem, QFrame, QSizePolicy, QSpacerItem,
)

# -- Colors / Theme ----------------------------------------------------------

ORANGE = "#E8772E"
ORANGE_HOVER = "#F09040"
ORANGE_PRESSED = "#C46020"
BG_DARK = "#1E1E1E"
BG_PANEL = "#252526"
BG_INPUT = "#2D2D30"
TEXT_PRIMARY = "#CCCCCC"
TEXT_SECONDARY = "#808080"
TEXT_BRIGHT = "#FFFFFF"
BORDER = "#3E3E42"
SUCCESS = "#4EC9B0"
ERROR = "#F44747"

STYLESHEET = f"""
QMainWindow {{
    background-color: {BG_DARK};
}}
QWidget {{
    background-color: {BG_DARK};
    color: {TEXT_PRIMARY};
    font-family: "SF Mono", "Menlo", "Consolas", monospace;
    font-size: 13px;
}}
QLabel#branchLabel {{
    color: {ORANGE};
    font-size: 15px;
    font-weight: bold;
    padding: 8px 0;
}}
QLabel#titleLabel {{
    color: {TEXT_BRIGHT};
    font-size: 18px;
    font-weight: bold;
}}
QPushButton {{
    background-color: {BG_INPUT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 8px 16px;
    font-size: 13px;
    min-height: 20px;
}}
QPushButton:hover {{
    background-color: #3E3E42;
    border-color: {ORANGE};
}}
QPushButton:pressed {{
    background-color: #4E4E52;
}}
QPushButton#primaryBtn {{
    background-color: {ORANGE};
    color: {TEXT_BRIGHT};
    border: none;
    font-weight: bold;
}}
QPushButton#primaryBtn:hover {{
    background-color: {ORANGE_HOVER};
}}
QPushButton#primaryBtn:pressed {{
    background-color: {ORANGE_PRESSED};
}}
QTextEdit {{
    background-color: {BG_PANEL};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 8px;
    font-size: 12px;
    selection-background-color: {ORANGE};
}}
QLineEdit {{
    background-color: {BG_INPUT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 6px 10px;
    font-size: 13px;
    selection-background-color: {ORANGE};
}}
QLineEdit:focus {{
    border-color: {ORANGE};
}}
QListWidget {{
    background-color: {BG_PANEL};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 4px;
    font-size: 13px;
    outline: none;
}}
QListWidget::item {{
    padding: 6px 8px;
    border-radius: 3px;
}}
QListWidget::item:selected {{
    background-color: {ORANGE};
    color: {TEXT_BRIGHT};
}}
QListWidget::item:hover {{
    background-color: #3E3E42;
}}
QDialog {{
    background-color: {BG_DARK};
}}
QDialogButtonBox QPushButton {{
    min-width: 80px;
}}
QFrame#separator {{
    background-color: {BORDER};
    max-height: 1px;
}}
"""


# -- IPC Client ---------------------------------------------------------------

class IPCClient:
    """Newline-delimited JSON over TCP."""

    def __init__(self, port):
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect(("127.0.0.1", port))
        self._buf = b""
        self._lock = threading.Lock()

    def send(self, request: dict) -> dict:
        with self._lock:
            data = json.dumps(request) + "\n"
            self.sock.sendall(data.encode("utf-8"))
            # Read response
            while True:
                while b"\n" in self._buf:
                    line, self._buf = self._buf.split(b"\n", 1)
                    line = line.strip()
                    if line:
                        return json.loads(line.decode("utf-8"))
                chunk = self.sock.recv(4096)
                if not chunk:
                    return {"ok": False, "error": "Connection lost"}
                self._buf += chunk

    def close(self):
        try:
            self.send({"action": "quit"})
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass


# -- Async Worker -------------------------------------------------------------

class Worker(QObject):
    """Run IPC requests off the main thread."""
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, ipc, request):
        super().__init__()
        self.ipc = ipc
        self.request = request

    @Slot()
    def run(self):
        try:
            result = self.ipc.send(self.request)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


# -- Dialogs ------------------------------------------------------------------

class InputDialog(QDialog):
    """Styled text input dialog."""

    def __init__(self, parent, title, prompt, initial=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(340)
        self.setStyleSheet(STYLESHEET)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        label = QLabel(prompt)
        label.setWordWrap(True)
        layout.addWidget(label)

        self.input = QLineEdit(initial)
        self.input.selectAll()
        layout.addWidget(self.input)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.input.setFocus()

    def get_value(self):
        return self.input.text()


class ChoiceDialog(QDialog):
    """Styled list picker dialog."""

    def __init__(self, parent, title, prompt, choices):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(340, 380)
        self.setStyleSheet(STYLESHEET)
        self.choices = choices

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        label = QLabel(prompt)
        label.setWordWrap(True)
        layout.addWidget(label)

        self.list_widget = QListWidget()
        for c in choices:
            self.list_widget.addItem(c)
        if choices:
            self.list_widget.setCurrentRow(0)
        self.list_widget.itemDoubleClicked.connect(self.accept)
        layout.addWidget(self.list_widget)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_value(self):
        item = self.list_widget.currentItem()
        return item.text() if item else None


# -- Main Window --------------------------------------------------------------

class GiteoPanel(QMainWindow):
    """Main Giteo panel window."""

    _append_log_signal = Signal(str, str)  # message, color

    def __init__(self, ipc, project_dir):
        super().__init__()
        self.ipc = ipc
        self.project_dir = project_dir
        self._threads = []

        self.setWindowTitle("Giteo")
        self.setMinimumSize(380, 520)
        self.resize(380, 580)
        self.setStyleSheet(STYLESHEET)

        # Always on top
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(8)
        layout.setContentsMargins(16, 12, 16, 12)

        # Header
        header = QHBoxLayout()
        title = QLabel("GITEO")
        title.setObjectName("titleLabel")
        header.addWidget(title)
        header.addStretch()
        self.branch_label = QLabel("branch: —")
        self.branch_label.setObjectName("branchLabel")
        header.addWidget(self.branch_label)
        layout.addLayout(header)

        # Separator
        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFrameShape(QFrame.HLine)
        layout.addWidget(sep)

        # Log area
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Ready...")
        layout.addWidget(self.log, stretch=1)

        # Buttons
        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(6)

        # Save — primary action
        save_btn = QPushButton("Save Version")
        save_btn.setObjectName("primaryBtn")
        save_btn.clicked.connect(self.on_save)
        btn_layout.addWidget(save_btn)

        # Branch row
        branch_row = QHBoxLayout()
        branch_row.setSpacing(6)
        new_branch_btn = QPushButton("New Branch")
        new_branch_btn.clicked.connect(self.on_new_branch)
        branch_row.addWidget(new_branch_btn)
        switch_btn = QPushButton("Switch Branch")
        switch_btn.clicked.connect(self.on_switch)
        branch_row.addWidget(switch_btn)
        btn_layout.addLayout(branch_row)

        # Push/Pull row
        sync_row = QHBoxLayout()
        sync_row.setSpacing(6)
        push_btn = QPushButton("Push")
        push_btn.clicked.connect(self.on_push)
        sync_row.addWidget(push_btn)
        pull_btn = QPushButton("Pull")
        pull_btn.clicked.connect(self.on_pull)
        sync_row.addWidget(pull_btn)
        btn_layout.addLayout(sync_row)

        # Merge
        merge_btn = QPushButton("Merge Branch")
        merge_btn.clicked.connect(self.on_merge)
        btn_layout.addWidget(merge_btn)

        # Status
        status_btn = QPushButton("Status")
        status_btn.clicked.connect(self.on_status)
        btn_layout.addWidget(status_btn)

        layout.addLayout(btn_layout)

        # Connect signal for thread-safe log updates
        self._append_log_signal.connect(self._do_append_log)

        # Initial state
        self.refresh_branch()
        self.append_log("Giteo panel ready.", SUCCESS)

    def append_log(self, msg, color=None):
        """Thread-safe log append."""
        self._append_log_signal.emit(msg, color or TEXT_PRIMARY)

    @Slot(str, str)
    def _do_append_log(self, msg, color):
        cursor = self.log.textCursor()
        cursor.movePosition(cursor.End)
        self.log.setTextCursor(cursor)
        self.log.insertHtml(
            f'<span style="color:{color};">{msg}</span><br>'
        )
        self.log.ensureCursorVisible()

    def _run_async(self, request, callback):
        """Run an IPC request on a background thread."""
        thread = QThread()
        worker = Worker(self.ipc, request)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(lambda result: self._on_worker_done(thread, worker, callback, result))
        worker.error.connect(lambda err: self._on_worker_error(thread, worker, err))
        self._threads.append((thread, worker))
        thread.start()

    def _on_worker_done(self, thread, worker, callback, result):
        thread.quit()
        thread.wait()
        self._threads = [(t, w) for t, w in self._threads if t is not thread]
        callback(result)

    def _on_worker_error(self, thread, worker, err):
        thread.quit()
        thread.wait()
        self._threads = [(t, w) for t, w in self._threads if t is not thread]
        self.append_log(f"Error: {err}", ERROR)

    def refresh_branch(self):
        self._run_async({"action": "get_branch"}, self._on_branch_result)

    def _on_branch_result(self, result):
        if result.get("ok"):
            branch = result.get("branch", "?")
            self.branch_label.setText(f"branch: {branch}")

    # -- Button handlers -------------------------------------------------------

    def on_save(self):
        dlg = InputDialog(self, "Save Version", "Commit message:", "save version")
        if dlg.exec() != QDialog.Accepted:
            self.append_log("Save cancelled.")
            return
        msg = dlg.get_value().strip()
        if not msg:
            msg = "save version"
        self.append_log(f"Saving: {msg}...")
        self._run_async({"action": "save", "message": msg}, self._on_save_result)

    def _on_save_result(self, result):
        if result.get("ok"):
            h = result.get("hash", "")
            m = result.get("message", "")
            self.append_log(f"Saved. {m} {h}", SUCCESS)
            self.refresh_branch()
        else:
            self.append_log(f"Save failed: {result.get('error', '?')}", ERROR)

    def on_new_branch(self):
        dlg = InputDialog(self, "New Branch", "Branch name:")
        if dlg.exec() != QDialog.Accepted:
            self.append_log("New branch cancelled.")
            return
        name = dlg.get_value().strip()
        if not name:
            return
        self.append_log(f"Creating branch '{name}'...")
        self._run_async({"action": "new_branch", "name": name}, self._on_new_branch_result)

    def _on_new_branch_result(self, result):
        if result.get("ok"):
            self.append_log(f"Switched to '{result.get('branch')}'.", SUCCESS)
            self.refresh_branch()
        else:
            self.append_log(f"Error: {result.get('error', '?')}", ERROR)

    def on_switch(self):
        self.append_log("Loading branches...")
        self._run_async({"action": "list_branches"}, self._on_switch_branches_loaded)

    def _on_switch_branches_loaded(self, result):
        if not result.get("ok"):
            self.append_log(f"Error: {result.get('error', '?')}", ERROR)
            return
        branches = result.get("branches", [])
        current = result.get("current", "")
        if not branches:
            self.append_log("No branches found.")
            return
        dlg = ChoiceDialog(self, "Switch Branch", f"Current: {current}\nSelect branch:", branches)
        if dlg.exec() != QDialog.Accepted:
            self.append_log("Switch cancelled.")
            return
        target = dlg.get_value()
        if not target:
            return
        self.append_log(f"Switching to '{target}'...")
        self._run_async({"action": "switch_branch", "branch": target}, self._on_switch_result)

    def _on_switch_result(self, result):
        if result.get("ok"):
            branch = result.get("branch", "?")
            restored = result.get("restored", False)
            msg = f"Switched to '{branch}'."
            if restored:
                msg += " Timeline restored."
            self.append_log(msg, SUCCESS)
            self.refresh_branch()
        else:
            self.append_log(f"Error: {result.get('error', '?')}", ERROR)

    def on_merge(self):
        self.append_log("Loading branches...")
        self._run_async({"action": "list_branches"}, self._on_merge_branches_loaded)

    def _on_merge_branches_loaded(self, result):
        if not result.get("ok"):
            self.append_log(f"Error: {result.get('error', '?')}", ERROR)
            return
        current = result.get("current", "")
        branches = [b for b in result.get("branches", []) if b != current]
        if not branches:
            self.append_log("No other branches to merge.")
            return
        dlg = ChoiceDialog(self, "Merge Branch", f"Merging into '{current}':\nSelect branch:", branches)
        if dlg.exec() != QDialog.Accepted:
            self.append_log("Merge cancelled.")
            return
        target = dlg.get_value()
        if not target:
            return
        self.append_log(f"Merging '{target}' into '{current}'...")
        self._run_async({"action": "merge", "branch": target}, self._on_merge_result)

    def _on_merge_result(self, result):
        if result.get("ok"):
            target = result.get("branch", "?")
            current = result.get("current", "?")
            issues = result.get("issues", "")
            self.append_log(f"Merged '{target}' into '{current}'.", SUCCESS)
            if issues:
                self.append_log(issues, ORANGE)
            self.append_log("Timeline restored.", SUCCESS)
            self.refresh_branch()
        else:
            self.append_log(f"Merge failed: {result.get('error', '?')}", ERROR)

    def on_push(self):
        self.append_log("Pushing...")
        self._run_async({"action": "push"}, self._on_push_result)

    def _on_push_result(self, result):
        if result.get("ok"):
            self.append_log(f"Pushed '{result.get('branch', '?')}'.", SUCCESS)
            output = result.get("output", "")
            if output:
                self.append_log(output)
        else:
            self.append_log(f"Push failed: {result.get('error', '?')}", ERROR)

    def on_pull(self):
        self.append_log("Pulling...")
        self._run_async({"action": "pull"}, self._on_pull_result)

    def _on_pull_result(self, result):
        if result.get("ok"):
            self.append_log(f"Pulled '{result.get('branch', '?')}'. Timeline restored.", SUCCESS)
        else:
            self.append_log(f"Pull failed: {result.get('error', '?')}", ERROR)

    def on_status(self):
        self._run_async({"action": "status"}, self._on_status_result)

    def _on_status_result(self, result):
        if result.get("ok"):
            self.append_log(f"Branch: {result.get('branch', '?')}", ORANGE)
            self.append_log(result.get("status", ""))
            log = result.get("log", "")
            if log:
                self.append_log("Recent commits:")
                self.append_log(log)
        else:
            self.append_log(f"Error: {result.get('error', '?')}", ERROR)

    def closeEvent(self, event):
        self.ipc.close()
        for thread, worker in self._threads:
            thread.quit()
            thread.wait(1000)
        event.accept()


# -- Entry Point ---------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Giteo PySide6 Panel")
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setApplicationName("Giteo")

    ipc = IPCClient(args.port)
    window = GiteoPanel(ipc, args.project_dir)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
