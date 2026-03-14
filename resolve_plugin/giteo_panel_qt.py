"""Giteo Panel — PySide6 UI subprocess (VIT Design).

This runs as a standalone process spawned by giteo_panel_launcher.py.
Communicates with the launcher via a JSON-over-TCP socket for operations
that require the DaVinci Resolve API (serialize, deserialize).

Usage: python giteo_panel_qt.py --project-dir /path/to/project --port 12345
"""
import argparse
import json
import os
import socket
import sys
import threading
import traceback
from functools import partial

# -- Debug logging (survives crash, goes to ~/.giteo/panel_debug.log)
_DEBUG_LOG_PATH = os.path.expanduser("~/.giteo/panel_debug.log")
_DEBUG_ENABLED = True  # Set to False to disable; enable for debugging crashes


def _debug(msg: str):
    if _DEBUG_ENABLED:
        try:
            os.makedirs(os.path.dirname(_DEBUG_LOG_PATH), exist_ok=True)
            with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(f"[giteo-qt] {msg}\n")
                f.flush()
        except Exception:
            pass
        print(f"[giteo-qt] {msg}", flush=True)

from PySide6.QtCore import (
    Qt, Signal, QObject, QThread, Slot, QPropertyAnimation, 
    QRect, QEasingCurve, QTimer, QSize, QByteArray
)
from PySide6.QtGui import (
    QFont, QColor, QPalette, QIcon, QGuiApplication, QPainter,
    QPixmap, QPen, QBrush, QPainterPath
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTextEdit, QLineEdit, QDialog, QDialogButtonBox,
    QListWidget, QListWidgetItem, QFrame, QSizePolicy, QSpacerItem,
    QScrollArea, QComboBox, QGridLayout,
)
from PySide6.QtSvg import QSvgRenderer

# -- Colors / Theme (from SVG mockup) -----------------------------------------

ORANGE = "#FFB463"           # Buttons, accent
ORANGE_LIGHT = "#FFD2A1"     # Panels, backgrounds
ORANGE_DARK = "#E07603"      # Graph lines, icons
ORANGE_HOVER = "#FFCA8A"
ORANGE_PRESSED = "#E89F4A"

BG_DARK = "#1C1C1C"          # Main background
BG_PANEL = "#2C2C2C"         # Input fields
BG_INPUT = "#1C1C1C"         # Input background
BORDER = "#464646"           # Borders

TEXT_PRIMARY = "#D9D9D9"     # Primary text
TEXT_DARK = "#4A4A4A"        # Secondary/muted
TEXT_BLACK = "#000000"       # On orange buttons
TEXT_BRIGHT = "#FFFFFF"

SUCCESS = "#4EC9B0"
ERROR = "#F44747"

# -- SVG Icons ----------------------------------------------------------------

SVG_LOGO = """<svg width="24" height="24" viewBox="0 0 24 24" fill="none">
  <circle cx="12" cy="12" r="10" stroke="{color}" stroke-width="2" fill="none"/>
  <circle cx="8" cy="8" r="1.5" fill="{color}"/>
  <circle cx="16" cy="8" r="1.5" fill="{color}" fill-opacity="0.5"/>
  <circle cx="8" cy="16" r="1.5" fill="{color}" fill-opacity="0.7"/>
  <circle cx="16" cy="16" r="1.5" fill="{color}" fill-opacity="0.3"/>
  <circle cx="12" cy="12" r="1.5" fill="{color}"/>
</svg>"""

SVG_AUDIO = """<svg width="16" height="16" viewBox="0 0 16 16" fill="none">
  <path d="M3 5h2l3-3v12l-3-3H3a1 1 0 01-1-1V6a1 1 0 011-1z" fill="{color}"/>
  <path d="M11 4.5c1.5 1 2 2.5 2 3.5s-.5 2.5-2 3.5" stroke="{color}" stroke-width="1.5" stroke-linecap="round" fill="none"/>
  <path d="M11 7c.5.3.8.7.8 1s-.3.7-.8 1" stroke="{color}" stroke-width="1.5" stroke-linecap="round" fill="none"/>
</svg>"""

SVG_VIDEO = """<svg width="16" height="16" viewBox="0 0 16 16" fill="none">
  <rect x="1" y="3" width="10" height="10" rx="1" stroke="{color}" stroke-width="1.5" fill="none"/>
  <path d="M11 6l4-2v8l-4-2V6z" fill="{color}"/>
</svg>"""

SVG_COLOR = """<svg width="16" height="16" viewBox="0 0 16 16" fill="none">
  <circle cx="8" cy="8" r="6" stroke="{color}" stroke-width="1.5" fill="none"/>
  <circle cx="8" cy="8" r="4" fill="{color}" fill-opacity="0.3"/>
  <circle cx="8" cy="8" r="2" fill="{color}"/>
</svg>"""

SVG_CHEVRON_DOWN = """<svg width="12" height="12" viewBox="0 0 12 12" fill="none">
  <path d="M3 4.5L6 7.5L9 4.5" stroke="{color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""

SVG_CHEVRON_RIGHT = """<svg width="12" height="12" viewBox="0 0 12 12" fill="none">
  <path d="M4.5 3L7.5 6L4.5 9" stroke="{color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""

SVG_CHEVRON_LEFT = """<svg width="12" height="12" viewBox="0 0 12 12" fill="none">
  <path d="M7.5 3L4.5 6L7.5 9" stroke="{color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""

SVG_SPARKLE = """<svg width="16" height="16" viewBox="0 0 16 16" fill="none">
  <path d="M8 1l1.5 4.5L14 7l-4.5 1.5L8 13l-1.5-4.5L2 7l4.5-1.5L8 1z" fill="{color}"/>
</svg>"""

# -- Stylesheet ---------------------------------------------------------------

STYLESHEET = f"""
QMainWindow {{
    background-color: {BG_DARK};
}}
QWidget {{
    background-color: {BG_DARK};
    color: {TEXT_PRIMARY};
    font-family: "SF Pro Display", "Segoe UI", "Helvetica Neue", sans-serif;
    font-size: 13px;
}}
QLabel#titleLabel {{
    color: {TEXT_PRIMARY};
    font-size: 16px;
    font-weight: 600;
}}
QLabel#branchLabel {{
    color: {ORANGE};
    font-size: 13px;
    font-weight: 600;
}}
QLabel#sectionHeader {{
    color: {TEXT_PRIMARY};
    font-size: 12px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 1px;
}}
QPushButton {{
    background-color: {BG_PANEL};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 5px;
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
    color: {TEXT_BLACK};
    border: none;
    font-weight: 600;
    border-radius: 5px;
}}
QPushButton#primaryBtn:hover {{
    background-color: {ORANGE_HOVER};
}}
QPushButton#primaryBtn:pressed {{
    background-color: {ORANGE_PRESSED};
}}
QPushButton#sectionToggle {{
    background-color: transparent;
    border: none;
    padding: 4px 8px;
    text-align: left;
}}
QPushButton#sectionToggle:hover {{
    background-color: rgba(255, 180, 99, 0.1);
}}
QLineEdit {{
    background-color: {BG_INPUT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 8px 12px;
    font-size: 13px;
    selection-background-color: {ORANGE};
}}
QLineEdit:focus {{
    border-color: {ORANGE};
}}
QComboBox {{
    background-color: {ORANGE};
    color: {TEXT_BLACK};
    border: none;
    border-radius: 20px;
    padding: 6px 16px;
    font-size: 12px;
    font-weight: 600;
    min-width: 100px;
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 1px solid rgba(0,0,0,0.2);
    width: 20px;
}}
QComboBox QAbstractItemView {{
    background-color: {BG_PANEL};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    selection-background-color: {ORANGE};
    selection-color: {TEXT_BLACK};
}}
QScrollArea {{
    background-color: transparent;
    border: none;
}}
QScrollBar:vertical {{
    background-color: {BG_DARK};
    width: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background-color: {BORDER};
    border-radius: 4px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{
    background-color: {TEXT_DARK};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QFrame#separator {{
    background-color: {BORDER};
    max-height: 1px;
}}
QFrame#changePanel {{
    background-color: {ORANGE_LIGHT};
    border-radius: 5px;
}}
QDialog {{
    background-color: {BG_DARK};
}}
QDialogButtonBox QPushButton {{
    min-width: 80px;
}}
QListWidget {{
    background-color: {BG_PANEL};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 5px;
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
    color: {TEXT_BLACK};
}}
QListWidget::item:hover {{
    background-color: #3E3E42;
}}
"""


# -- Utility Functions --------------------------------------------------------

def svg_to_pixmap(svg_str: str, color: str, size: int = 16) -> QPixmap:
    """Convert SVG string to QPixmap with specified color."""
    svg_data = svg_str.format(color=color).encode('utf-8')
    renderer = QSvgRenderer(QByteArray(svg_data))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap


def svg_to_icon(svg_str: str, color: str, size: int = 16) -> QIcon:
    """Convert SVG string to QIcon with specified color."""
    return QIcon(svg_to_pixmap(svg_str, color, size))


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


# -- Collapsible Section Widget -----------------------------------------------

class CollapsibleSection(QWidget):
    """A collapsible section with header and content area."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._expanded = True
        self._title = title

        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header button
        self._header = QPushButton()
        self._header.setObjectName("sectionToggle")
        self._header.setCursor(Qt.PointingHandCursor)
        self._header.clicked.connect(self.toggle)
        self._update_header()
        layout.addWidget(self._header)

        # Content container
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setSpacing(8)
        self._content_layout.setContentsMargins(0, 8, 0, 8)
        layout.addWidget(self._content)

    def _update_header(self):
        """Update header text and icon."""
        chevron = "▼" if self._expanded else "▶"
        self._header.setText(f"  {chevron}  {self._title}")
        self._header.setStyleSheet(f"""
            QPushButton#sectionToggle {{
                background-color: transparent;
                border: none;
                padding: 8px 4px;
                text-align: left;
                color: {TEXT_PRIMARY};
                font-size: 12px;
                font-weight: 500;
                letter-spacing: 1px;
            }}
            QPushButton#sectionToggle:hover {{
                background-color: rgba(255, 180, 99, 0.1);
            }}
        """)

    def toggle(self):
        """Toggle expanded/collapsed state."""
        self._expanded = not self._expanded
        self._content.setVisible(self._expanded)
        self._update_header()

    def set_expanded(self, expanded: bool):
        """Set expanded state."""
        self._expanded = expanded
        self._content.setVisible(expanded)
        self._update_header()

    def content_layout(self) -> QVBoxLayout:
        """Return the content layout for adding widgets."""
        return self._content_layout

    def add_widget(self, widget: QWidget):
        """Add a widget to the content area."""
        self._content_layout.addWidget(widget)

    def add_layout(self, layout):
        """Add a layout to the content area."""
        self._content_layout.addLayout(layout)


# -- Actions Section Widget ---------------------------------------------------
# Uses inline inputs instead of modal dialogs to avoid macOS crash with QInputDialog.

class ActionsSection(QWidget):
    """Quick actions with inline inputs (no modal dialogs)."""

    new_branch_requested = Signal(str)   # branch name
    switch_branch_requested = Signal(str)
    merge_branch_requested = Signal(str)
    push_requested = Signal()
    pull_requested = Signal()
    status_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(0, 0, 0, 0)

        # New Branch: inline input
        new_row = QHBoxLayout()
        self._new_input = QLineEdit()
        self._new_input.setPlaceholderText("New branch name...")
        self._new_input.setStyleSheet(f"""
            QLineEdit {{ background-color: {BG_INPUT}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER}; border-radius: 4px; padding: 6px; }}
        """)
        new_row.addWidget(self._new_input)
        self._new_btn = QPushButton("Create")
        self._new_btn.setObjectName("primaryBtn")
        self._new_btn.clicked.connect(self._on_new_branch_click)
        new_row.addWidget(self._new_btn)
        layout.addLayout(new_row)

        # Switch Branch: combo + button
        switch_row = QHBoxLayout()
        self._switch_combo = QComboBox()
        self._switch_combo.setMinimumWidth(120)
        switch_row.addWidget(self._switch_combo)
        self._switch_btn = QPushButton("Switch")
        self._switch_btn.clicked.connect(self._on_switch_click)
        switch_row.addWidget(self._switch_btn)
        layout.addLayout(switch_row)

        # Merge Branch: combo + button
        merge_row = QHBoxLayout()
        self._merge_combo = QComboBox()
        self._merge_combo.setMinimumWidth(120)
        merge_row.addWidget(self._merge_combo)
        self._merge_btn = QPushButton("Merge")
        self._merge_btn.clicked.connect(self._on_merge_click)
        merge_row.addWidget(self._merge_btn)
        layout.addLayout(merge_row)

        # Push, Pull, Status
        btn_row = QHBoxLayout()
        self._push_btn = QPushButton("Push")
        self._push_btn.clicked.connect(self.push_requested.emit)
        self._pull_btn = QPushButton("Pull")
        self._pull_btn.clicked.connect(self.pull_requested.emit)
        self._status_btn = QPushButton("Status")
        self._status_btn.clicked.connect(self.status_requested.emit)
        btn_row.addWidget(self._push_btn)
        btn_row.addWidget(self._pull_btn)
        btn_row.addWidget(self._status_btn)
        layout.addLayout(btn_row)

    def _on_new_branch_click(self):
        _debug("ActionsSection._on_new_branch_click")
        name = self._new_input.text().strip()
        if name:
            self.new_branch_requested.emit(name)
            self._new_input.clear()

    def _on_switch_click(self):
        _debug("ActionsSection._on_switch_click")
        target = self._switch_combo.currentText()
        if target:
            self.switch_branch_requested.emit(target)

    def _on_merge_click(self):
        _debug("ActionsSection._on_merge_click")
        target = self._merge_combo.currentText()
        if target:
            self.merge_branch_requested.emit(target)

    def set_branches(self, branches: list, current: str):
        """Populate switch/merge combos. Call after list_branches."""
        self._switch_combo.clear()
        self._switch_combo.addItems(branches or [])
        self._merge_combo.clear()
        merge_targets = [b for b in (branches or []) if b != current]
        self._merge_combo.addItems(merge_targets)


# -- Change Item Widget -------------------------------------------------------

class ChangeItemWidget(QWidget):
    """A single change item with icon and name."""

    def __init__(self, category: str, name: str, details: str = "", parent=None):
        super().__init__(parent)
        self.category = category
        
        layout = QHBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(8, 4, 8, 4)

        # Icon
        icon_label = QLabel()
        if category == "audio":
            icon_label.setPixmap(svg_to_pixmap(SVG_AUDIO, ORANGE_DARK, 16))
        elif category == "video":
            icon_label.setPixmap(svg_to_pixmap(SVG_VIDEO, ORANGE_DARK, 16))
        elif category == "color":
            icon_label.setPixmap(svg_to_pixmap(SVG_COLOR, ORANGE_DARK, 16))
        icon_label.setFixedSize(16, 16)
        layout.addWidget(icon_label)

        # Name
        name_label = QLabel(name)
        name_label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px;")
        layout.addWidget(name_label)

        layout.addStretch()


# -- Changes Section Widget ---------------------------------------------------

class ChangesSection(QWidget):
    """The CHANGES section with commit input and file list."""

    commit_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._changes = {"audio": [], "video": [], "color": []}

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(0, 0, 0, 0)

        # Commit message input row
        input_row = QHBoxLayout()
        input_row.setSpacing(8)

        self._message_input = QLineEdit()
        self._message_input.setPlaceholderText("Commit message...")
        self._message_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {BG_INPUT};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER};
                border-radius: 3px;
                padding: 8px 12px;
            }}
            QLineEdit:focus {{
                border-color: {ORANGE};
            }}
        """)
        input_row.addWidget(self._message_input, stretch=1)

        # Sparkle button (AI assist placeholder)
        sparkle_btn = QPushButton()
        sparkle_btn.setIcon(svg_to_icon(SVG_SPARKLE, TEXT_DARK, 16))
        sparkle_btn.setFixedSize(36, 36)
        sparkle_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {BG_PANEL};
                border: 1px solid {BORDER};
                border-radius: 3px;
            }}
            QPushButton:hover {{
                border-color: {ORANGE};
            }}
        """)
        sparkle_btn.setToolTip("AI-assisted commit message")
        input_row.addWidget(sparkle_btn)

        layout.addLayout(input_row)

        # Commit button with dropdown
        commit_row = QHBoxLayout()
        commit_row.setSpacing(0)

        self._commit_btn = QPushButton("Commit")
        self._commit_btn.setObjectName("primaryBtn")
        self._commit_btn.clicked.connect(self._on_commit)
        self._commit_btn.setStyleSheet(f"""
            QPushButton#primaryBtn {{
                background-color: {ORANGE};
                color: {TEXT_BLACK};
                border: none;
                border-radius: 5px 0 0 5px;
                padding: 10px 24px;
                font-weight: 600;
            }}
            QPushButton#primaryBtn:hover {{
                background-color: {ORANGE_HOVER};
            }}
        """)
        commit_row.addWidget(self._commit_btn, stretch=1)

        dropdown_btn = QPushButton("▼")
        dropdown_btn.setFixedWidth(36)
        dropdown_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {ORANGE};
                color: {TEXT_BLACK};
                border: none;
                border-left: 1px solid rgba(0,0,0,0.15);
                border-radius: 0 5px 5px 0;
                padding: 10px 8px;
                font-size: 10px;
            }}
            QPushButton:hover {{
                background-color: {ORANGE_HOVER};
            }}
        """)
        commit_row.addWidget(dropdown_btn)

        layout.addLayout(commit_row)

        # Changes sub-header
        changes_header = QLabel("Changes")
        changes_header.setStyleSheet(f"""
            color: {TEXT_PRIMARY};
            font-size: 11px;
            font-weight: 500;
            padding-top: 8px;
        """)
        layout.addWidget(changes_header)

        # Changes list container
        self._changes_container = QWidget()
        self._changes_layout = QVBoxLayout(self._changes_container)
        self._changes_layout.setSpacing(2)
        self._changes_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._changes_container)

        layout.addStretch()

    def _on_commit(self):
        msg = self._message_input.text().strip()
        if not msg:
            msg = "save version"
        self.commit_requested.emit(msg)
        self._message_input.clear()

    def set_changes(self, changes: dict):
        """Update the displayed changes."""
        self._changes = changes

        # Clear existing items
        while self._changes_layout.count():
            child = self._changes_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        # Add new items by category
        for category in ["video", "audio", "color"]:
            items = changes.get(category, [])
            for item in items:
                name = item.get("name", item.get("id", "Unknown"))
                widget = ChangeItemWidget(category, name)
                self._changes_layout.addWidget(widget)

        if not any(changes.values()):
            no_changes = QLabel("No changes")
            no_changes.setStyleSheet(f"color: {TEXT_DARK}; font-size: 12px; padding: 8px;")
            self._changes_layout.addWidget(no_changes)

    def get_message(self) -> str:
        return self._message_input.text().strip()


# -- Merge Feedback Section Widget --------------------------------------------

class MergeFeedbackSection(QWidget):
    """The MERGE FEEDBACK section with two branch panels."""

    merge_requested = Signal(str, str)  # branch_a, branch_b

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(0, 0, 0, 0)

        # Two-panel grid
        panels_layout = QHBoxLayout()
        panels_layout.setSpacing(8)

        # Left panel (branch one)
        self._left_panel = self._create_branch_panel("branch-one")
        panels_layout.addWidget(self._left_panel)

        # Right panel (branch two)
        self._right_panel = self._create_branch_panel("branch-two")
        panels_layout.addWidget(self._right_panel)

        layout.addLayout(panels_layout)

    def _create_branch_panel(self, default_name: str) -> QWidget:
        """Create a branch comparison panel."""
        panel = QFrame()
        panel.setObjectName("changePanel")
        panel.setStyleSheet(f"""
            QFrame#changePanel {{
                background-color: {ORANGE_LIGHT};
                border-radius: 5px;
                padding: 8px;
            }}
        """)

        panel_layout = QVBoxLayout(panel)
        panel_layout.setSpacing(8)
        panel_layout.setContentsMargins(8, 8, 8, 8)

        # Branch selector
        branch_combo = QComboBox()
        branch_combo.addItem(default_name)
        branch_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {ORANGE};
                color: {TEXT_BLACK};
                border: none;
                border-radius: 15px;
                padding: 6px 16px;
                font-size: 12px;
                font-weight: 600;
            }}
        """)
        panel_layout.addWidget(branch_combo)

        # Summary area (placeholder)
        summary = QFrame()
        summary.setMinimumHeight(100)
        summary.setStyleSheet(f"""
            QFrame {{
                background-color: {ORANGE_LIGHT};
                border: none;
                border-radius: 3px;
            }}
        """)
        panel_layout.addWidget(summary)

        return panel

    def set_branches(self, branches: list):
        """Update available branches in both dropdowns."""
        for panel in [self._left_panel, self._right_panel]:
            combo = panel.findChild(QComboBox)
            if combo:
                current = combo.currentText()
                combo.clear()
                combo.addItems(branches)
                if current in branches:
                    combo.setCurrentText(current)


# -- Commit Graph Section Widget ----------------------------------------------

class CommitNode(QWidget):
    """A single commit node in the graph."""

    def __init__(self, commit: dict, parent=None):
        super().__init__(parent)
        self.commit = commit

        layout = QHBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(0, 4, 0, 4)

        # Timeline line and node
        node_widget = QWidget()
        node_widget.setFixedWidth(32)
        node_layout = QVBoxLayout(node_widget)
        node_layout.setSpacing(0)
        node_layout.setContentsMargins(0, 0, 0, 0)

        # Node circle with category icon
        category = commit.get("category", "video")
        node_label = QLabel()
        node_label.setFixedSize(24, 24)
        node_label.setAlignment(Qt.AlignCenter)
        
        if category == "audio":
            node_label.setPixmap(svg_to_pixmap(SVG_AUDIO, ORANGE_DARK, 16))
        elif category == "video":
            node_label.setPixmap(svg_to_pixmap(SVG_VIDEO, ORANGE_DARK, 16))
        elif category == "color":
            node_label.setPixmap(svg_to_pixmap(SVG_COLOR, ORANGE_DARK, 16))
        
        node_label.setStyleSheet(f"""
            QLabel {{
                background-color: {ORANGE_LIGHT};
                border: 2px solid {ORANGE_DARK};
                border-radius: 12px;
            }}
        """)
        node_layout.addWidget(node_label, alignment=Qt.AlignHCenter)

        layout.addWidget(node_widget)

        # Commit info
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        # Branch tag
        branch = commit.get("branch", "main")
        branch_label = QLabel(branch)
        branch_label.setStyleSheet(f"""
            QLabel {{
                background-color: {ORANGE};
                color: {TEXT_BLACK};
                border-radius: 10px;
                padding: 2px 12px;
                font-size: 11px;
                font-weight: 600;
            }}
        """)
        branch_label.setFixedWidth(branch_label.sizeHint().width() + 16)
        info_layout.addWidget(branch_label)

        # Commit message
        message = commit.get("message", "No message")
        msg_label = QLabel(message)
        msg_label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px;")
        msg_label.setWordWrap(True)
        info_layout.addWidget(msg_label)

        layout.addLayout(info_layout, stretch=1)


class CommitGraphSection(QWidget):
    """The GRAPH section with vertical commit timeline."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._commits = []

        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        # Scroll area for commits
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self._commits_container = QWidget()
        self._commits_layout = QVBoxLayout(self._commits_container)
        self._commits_layout.setSpacing(0)
        self._commits_layout.setContentsMargins(8, 0, 8, 0)
        self._commits_layout.addStretch()

        scroll.setWidget(self._commits_container)
        layout.addWidget(scroll)

    def set_commits(self, commits: list):
        """Update the displayed commits."""
        self._commits = commits

        # Clear existing items (except stretch)
        while self._commits_layout.count() > 1:
            child = self._commits_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        # Add new commit nodes
        for i, commit in enumerate(commits):
            node = CommitNode(commit)
            self._commits_layout.insertWidget(i, node)

            # Add connecting line if not last
            if i < len(commits) - 1:
                line = QFrame()
                line.setFixedWidth(2)
                line.setFixedHeight(20)
                line.setStyleSheet(f"background-color: {ORANGE_DARK};")
                
                line_container = QWidget()
                line_layout = QHBoxLayout(line_container)
                line_layout.setContentsMargins(15, 0, 0, 0)
                line_layout.addWidget(line)
                line_layout.addStretch()
                
                self._commits_layout.insertWidget(i * 2 + 1, line_container)


# -- Main Window --------------------------------------------------------------

class GiteoPanel(QMainWindow):
    """Main Giteo panel window (VIT Design)."""

    _append_log_signal = Signal(str, str)

    def __init__(self, ipc, project_dir):
        super().__init__()
        self.ipc = ipc
        self.project_dir = project_dir
        self._threads = []
        self._collapsed = False

        self.setWindowTitle("vit")
        self.setStyleSheet(STYLESHEET)

        # Frameless, always on top
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint
        )

        # Position: left edge of screen, full height
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self._panel_width = 380
        self._tab_width = 52
        self._screen_geo = screen
        self.setGeometry(screen.x(), screen.y(), self._panel_width, screen.height())

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Main content area
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(12)
        content_layout.setContentsMargins(16, 12, 16, 12)

        # Header
        header = QHBoxLayout()
        header.setSpacing(8)

        # Logo
        logo_label = QLabel()
        logo_label.setPixmap(svg_to_pixmap(SVG_LOGO, ORANGE, 24))
        logo_label.setFixedSize(24, 24)
        header.addWidget(logo_label)

        # Title
        title = QLabel("vit")
        title.setObjectName("titleLabel")
        header.addWidget(title)

        header.addStretch()

        # Branch label
        self.branch_label = QLabel("BRANCH: —")
        self.branch_label.setObjectName("branchLabel")
        header.addWidget(self.branch_label)

        # Collapse chevron
        self._chevron_btn = QPushButton("▶")
        self._chevron_btn.setFixedSize(28, 28)
        self._chevron_btn.setCursor(Qt.PointingHandCursor)
        self._chevron_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {ORANGE};
                color: {TEXT_BLACK};
                border: none;
                border-radius: 14px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {ORANGE_HOVER};
            }}
        """)
        self._chevron_btn.clicked.connect(self.toggle_panel)
        header.addWidget(self._chevron_btn)

        content_layout.addLayout(header)

        # Separator
        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFrameShape(QFrame.HLine)
        content_layout.addWidget(sep)

        # Scroll area for sections
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        sections_widget = QWidget()
        sections_layout = QVBoxLayout(sections_widget)
        sections_layout.setSpacing(8)
        sections_layout.setContentsMargins(0, 0, 0, 0)

        # ACTIONS section
        self._actions_section = CollapsibleSection("ACTIONS")
        self._actions_widget = ActionsSection()
        self._actions_widget.new_branch_requested.connect(self.on_new_branch)
        self._actions_widget.switch_branch_requested.connect(self.on_switch_branch)
        self._actions_widget.merge_branch_requested.connect(self.on_merge_branch)
        self._actions_widget.push_requested.connect(self.on_push)
        self._actions_widget.pull_requested.connect(self.on_pull)
        self._actions_widget.status_requested.connect(self.on_status)
        self._actions_section.add_widget(self._actions_widget)
        sections_layout.addWidget(self._actions_section)

        # STATUS / LOG section
        self._log_section = CollapsibleSection("LOG")
        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setMaximumHeight(120)
        self._log_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {BG_INPUT};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER};
                border-radius: 5px;
                padding: 8px;
                font-family: "SF Mono", "Monaco", "Consolas", monospace;
                font-size: 11px;
            }}
        """)
        self._log_section.add_widget(self._log_text)
        sections_layout.addWidget(self._log_section)

        # CHANGES section
        self._changes_section = CollapsibleSection("CHANGES")
        self._changes_widget = ChangesSection()
        self._changes_widget.commit_requested.connect(self.on_save)
        self._changes_section.add_widget(self._changes_widget)
        sections_layout.addWidget(self._changes_section)

        # MERGE FEEDBACK section
        self._merge_section = CollapsibleSection("MERGE FEEDBACK")
        self._merge_widget = MergeFeedbackSection()
        self._merge_section.add_widget(self._merge_widget)
        sections_layout.addWidget(self._merge_section)

        # GRAPH section
        self._graph_section = CollapsibleSection("GRAPH")
        self._graph_widget = CommitGraphSection()
        self._graph_section.add_widget(self._graph_widget)
        sections_layout.addWidget(self._graph_section)

        sections_layout.addStretch()

        scroll.setWidget(sections_widget)
        content_layout.addWidget(scroll, stretch=1)

        main_layout.addWidget(content, stretch=1)

        # Tab for collapsed state
        self._tab = QWidget()
        self._tab.setFixedWidth(self._tab_width)
        self._tab.setStyleSheet(f"background-color: {BG_DARK};")
        tab_layout = QVBoxLayout(self._tab)
        tab_layout.setContentsMargins(4, 12, 4, 12)

        tab_btn = QPushButton("◀")
        tab_btn.setFixedSize(32, 48)
        tab_btn.setCursor(Qt.PointingHandCursor)
        tab_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {ORANGE};
                color: {TEXT_BLACK};
                border: none;
                border-radius: 4px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {ORANGE_HOVER};
            }}
        """)
        tab_btn.clicked.connect(self.toggle_panel)
        tab_layout.addWidget(tab_btn)
        tab_layout.addStretch()

        self._tab.setVisible(False)
        main_layout.addWidget(self._tab)

        # Initial data load
        self._append_log("Giteo panel ready.")
        self.refresh_branches_list()  # populates branch label + switch/merge combos
        self.refresh_changes()
        self.refresh_commits()

    def _run_async(self, request, callback):
        """Run IPC request. Uses QTimer to defer to event loop (avoids QThread crash on macOS)."""
        _debug(f"_run_async action={request.get('action', '?')}")

        def do_request():
            _debug(f"do_request starting for {request.get('action', '?')}")
            try:
                result = self.ipc.send(request)
                _debug(f"do_request got result ok={result.get('ok')}")
                callback(result)
            except Exception as e:
                _debug(f"do_request EXCEPTION: {e}\n{traceback.format_exc()}")
                self._append_log(f"Error: {e}")

        QTimer.singleShot(0, do_request)

    def _append_log(self, msg: str):
        try:
            self._log_text.append(msg)
            sb = self._log_text.verticalScrollBar()
            if sb:
                sb.setValue(sb.maximum())
        except Exception as e:
            _debug(f"_append_log EXCEPTION: {e}")

    def refresh_branch(self):
        self._run_async({"action": "get_branch"}, self._on_branch_result)

    def refresh_branches_list(self):
        """Fetch full branch list and update combos + label."""
        self._run_async({"action": "list_branches"}, self._on_branches_list_result)

    def _on_branch_result(self, result):
        if result.get("ok"):
            branch = result.get("branch", "?")
            self.branch_label.setText(f"BRANCH: {branch}")

    def _on_branches_list_result(self, result):
        if result.get("ok"):
            branches = result.get("branches", [])
            current = result.get("current", "?")
            self.branch_label.setText(f"BRANCH: {current}")
            self._actions_widget.set_branches(branches, current)

    def refresh_changes(self):
        self._run_async({"action": "get_changes"}, self._on_changes_result)

    def _on_changes_result(self, result):
        if result.get("ok"):
            changes = result.get("changes", {})
            self._changes_widget.set_changes(changes)
        # If action not implemented yet, show empty
        elif "Unknown action" in result.get("error", ""):
            self._changes_widget.set_changes({})

    def refresh_commits(self):
        self._run_async({"action": "get_commit_history", "limit": 10}, self._on_commits_result)

    def _on_commits_result(self, result):
        if result.get("ok"):
            commits = result.get("commits", [])
            self._graph_widget.set_commits(commits)
        elif "Unknown action" in result.get("error", ""):
            # Show placeholder commits for now
            self._graph_widget.set_commits([
                {"message": "Initial commit", "branch": "main", "category": "video"},
            ])

    def on_save(self, message: str):
        """Handle commit request from Changes section."""
        _debug(f"on_save(message={repr(message)})")
        if not message:
            message = "save version"
        self._run_async({"action": "save", "message": message}, self._on_save_result)

    def _on_save_result(self, result):
        if result.get("ok"):
            self._append_log(f"Saved. {result.get('message', result.get('hash', ''))}")
            self.refresh_branch()
            self.refresh_changes()
            self.refresh_commits()
        else:
            self._append_log(f"Save failed: {result.get('error', '?')}")

    def on_new_branch(self, name: str):
        """Called with inline input value (no dialog)."""
        _debug(f"on_new_branch(name={repr(name)})")
        if not name or not name.strip():
            return
        name = name.strip()
        _debug("on_new_branch: about to _append_log")
        self._append_log(f"Creating branch '{name}'...")
        _debug("on_new_branch: about to _run_async")
        self._run_async({"action": "new_branch", "name": name}, self._on_new_branch_result)
        _debug("on_new_branch: _run_async called")

    def _on_new_branch_result(self, result):
        if result.get("ok"):
            self._append_log(f"Switched to '{result.get('branch', '')}'.")
            self.refresh_branches_list()
            self.refresh_commits()
        else:
            self._append_log(f"Error: {result.get('error', '?')}")

    def on_switch_branch(self, target: str):
        """Called with combo selection (no dialog)."""
        _debug(f"on_switch_branch(target={repr(target)})")
        if not target:
            return
        self._append_log(f"Switching to '{target}'...")
        self._run_async({"action": "switch_branch", "branch": target}, self._on_switch_result)

    def _on_switch_result(self, result):
        if result.get("ok"):
            self._append_log(f"Switched. Timeline restored." if result.get("restored") else "Switched.")
            self.refresh_branches_list()
            self.refresh_changes()
            self.refresh_commits()
        else:
            self._append_log(f"Error: {result.get('error', '?')}")

    def on_merge_branch(self, target: str):
        """Called with combo selection (no dialog)."""
        _debug(f"on_merge_branch(target={repr(target)})")
        if not target:
            return
        current = self.branch_label.text().replace("BRANCH: ", "").strip()
        self._append_log(f"Merging '{target}' into '{current}'...")
        self._run_async({"action": "merge", "branch": target}, self._on_merge_result)

    def _on_merge_result(self, result):
        if result.get("ok"):
            self._append_log(f"Merged '{result.get('branch', '')}'.")
            if result.get("issues"):
                self._append_log(result["issues"])
            self.refresh_branches_list()
            self.refresh_changes()
            self.refresh_commits()
        else:
            self._append_log(f"Merge failed: {result.get('error', '?')}")

    def on_push(self):
        self._append_log("Pushing...")
        self._run_async({"action": "push"}, self._on_push_result)

    def _on_push_result(self, result):
        if result.get("ok"):
            self._append_log(f"Pushed {result.get('branch', '')}. {result.get('output', '')}")
        else:
            self._append_log(f"Push failed: {result.get('error', '?')}")

    def on_pull(self):
        self._append_log("Pulling...")
        self._run_async({"action": "pull"}, self._on_pull_result)

    def _on_pull_result(self, result):
        if result.get("ok"):
            self._append_log(f"Pulled {result.get('branch', '')}. Timeline restored.")
            self.refresh_branch()
            self.refresh_changes()
            self.refresh_commits()
        else:
            self._append_log(f"Pull failed: {result.get('error', '?')}")

    def on_status(self):
        self._run_async({"action": "status"}, self._on_status_result)

    def _on_status_result(self, result):
        if result.get("ok"):
            self._append_log(f"Branch: {result.get('branch', '')}")
            self._append_log(result.get("status", ""))
            self._append_log("Recent:\n" + (result.get("log", "") or ""))
        else:
            self._append_log(f"Error: {result.get('error', '?')}")

    def toggle_panel(self):
        """Slide the panel in/out from the left edge."""
        screen = self._screen_geo
        anim = QPropertyAnimation(self, b"geometry")
        anim.setDuration(200)
        anim.setEasingCurve(QEasingCurve.InOutQuad)

        if self._collapsed:
            anim.setStartValue(QRect(
                screen.x() - self._panel_width + self._tab_width,
                screen.y(), self._panel_width, screen.height()
            ))
            anim.setEndValue(QRect(
                screen.x(), screen.y(), self._panel_width, screen.height()
            ))
            self._tab.setVisible(False)
            self._collapsed = False
        else:
            anim.setStartValue(QRect(
                screen.x(), screen.y(), self._panel_width, screen.height()
            ))
            anim.setEndValue(QRect(
                screen.x() - self._panel_width + self._tab_width,
                screen.y(), self._panel_width, screen.height()
            ))
            self._tab.setVisible(True)
            self._collapsed = True

        self._anim = anim
        anim.start()

    def closeEvent(self, event):
        self.ipc.close()
        for thread, worker in self._threads:
            thread.quit()
            thread.wait(1000)
        event.accept()


# -- Entry Point --------------------------------------------------------------

def main():
    _debug("main() starting")
    parser = argparse.ArgumentParser(description="Giteo PySide6 Panel (VIT)")
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    _debug(f"project_dir={args.project_dir} port={args.port}")

    app = QApplication(sys.argv)
    app.setApplicationName("vit")
    _debug("QApplication created")

    ipc = IPCClient(args.port)
    _debug("IPCClient connected")
    window = GiteoPanel(ipc, args.project_dir)
    _debug("GiteoPanel created")
    window.show()
    _debug("window.show() done, entering event loop")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
