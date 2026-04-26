"""
Progress panel — the expanded view shown during batch processing.

Displayed as a QWidget inside the floating window when a batch is running.
Shows per-file status rows, an overall progress bar, and pause/stop controls.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

# Status icons as unicode — no image deps
ICON_RUNNING  = "⟳"
ICON_DONE     = "✓"
ICON_ERROR    = "✗"
ICON_SKIPPED  = "→"
ICON_PENDING  = "·"


class FileRow(QWidget):
    """One row in the file list: icon + filename + status."""

    def __init__(self, filename: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        self.icon_label = QLabel(ICON_PENDING)
        self.icon_label.setFixedWidth(18)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.name_label = QLabel(filename)
        self.name_label.setFont(QFont("monospace", 13))
        self.name_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.name_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        layout.addWidget(self.icon_label)
        layout.addWidget(self.name_label)

    def set_running(self) -> None:
        self.icon_label.setText(ICON_RUNNING)
        self.icon_label.setStyleSheet("color: #f0a500;")

    def set_done(self) -> None:
        self.icon_label.setText(ICON_DONE)
        self.icon_label.setStyleSheet("color: #4caf50;")

    def set_error(self, msg: str = "") -> None:
        self.icon_label.setText(ICON_ERROR)
        self.icon_label.setStyleSheet("color: #f44336;")
        if msg:
            self.name_label.setToolTip(msg)

    def set_skipped(self) -> None:
        self.icon_label.setText(ICON_SKIPPED)
        self.icon_label.setStyleSheet("color: #888888;")


class ProgressPanel(QWidget):
    """
    Expanded progress view.

    Signals:
      pause_clicked  — user wants to pause/resume
      stop_clicked   — user wants to stop the batch
    """

    pause_clicked = pyqtSignal()
    stop_clicked  = pyqtSignal()
    close_clicked = pyqtSignal()   # emitted when user clicks "← Back" after batch ends

    def __init__(self, folder_name: str, total: int, parent=None):
        super().__init__(parent)
        self.total = total
        self._rows: dict[str, FileRow] = {}
        self._paused = False

        self.setMinimumWidth(340)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Header
        header = QLabel(f"<b>{folder_name}</b>")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, max(total, 1))
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v / %m  (%p%)")
        layout.addWidget(self.progress_bar)

        # Status line
        self.status_label = QLabel("Initializing…")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("color: #888; font-size: 13px;")
        layout.addWidget(self.status_label)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep)

        # Scrollable file list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumHeight(180)

        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(0)
        self._list_layout.addStretch(1)

        scroll.setWidget(self._list_widget)
        layout.addWidget(scroll, 1)

        # Buttons
        btn_row = QHBoxLayout()

        self.back_btn = QPushButton("← Back")
        self.back_btn.setFixedHeight(28)
        self.back_btn.setToolTip("Return to drop zone (batch keeps running)")
        self.back_btn.clicked.connect(self._on_back)

        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setFixedHeight(28)
        self.pause_btn.clicked.connect(self._on_pause)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setFixedHeight(28)
        self.stop_btn.setStyleSheet("color: #c62828;")
        self.stop_btn.clicked.connect(self.stop_clicked)

        btn_row.addWidget(self.back_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.pause_btn)
        btn_row.addWidget(self.stop_btn)
        layout.addLayout(btn_row)

    def _on_back(self) -> None:
        self.close_clicked.emit()  # navigate back; batch keeps running

    def _on_pause(self) -> None:
        self._paused = not self._paused
        self.pause_btn.setText("Resume" if self._paused else "Pause")
        self.pause_clicked.emit()

    def add_file(self, filename: str) -> None:
        """Add a file row to the list (call at scan time)."""
        if filename in self._rows:
            return
        row = FileRow(filename)
        # Insert before the stretch at the end
        count = self._list_layout.count()
        self._list_layout.insertWidget(count - 1, row)
        self._rows[filename] = row

    def set_running(self, filename: str) -> None:
        self._ensure_row(filename).set_running()
        self.status_label.setText(f"Processing: {filename}")

    def set_done(self, filename: str) -> None:
        self._ensure_row(filename).set_done()

    def set_error(self, filename: str, msg: str = "") -> None:
        self._ensure_row(filename).set_error(msg)

    def set_skipped(self, filename: str) -> None:
        self._ensure_row(filename).set_skipped()

    def update_progress(self, done: int, total: int) -> None:
        self.progress_bar.setMaximum(max(total, 1))
        self.progress_bar.setValue(done)

    def set_status(self, msg: str) -> None:
        self.status_label.setText(msg)

    def set_complete(self, done: int, errors: int, skipped: int, total: int) -> None:
        self.progress_bar.setValue(total)
        parts = [f"{done} done"]
        if errors:
            parts.append(f"{errors} errors")
        if skipped:
            parts.append(f"{skipped} skipped")
        self.status_label.setText("Complete — " + ", ".join(parts))
        self.pause_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.back_btn.setToolTip("Return to drop zone")

    def _ensure_row(self, filename: str) -> FileRow:
        if filename not in self._rows:
            self.add_file(filename)
        return self._rows[filename]
