"""
AppStatusBar — bottom strip of the main window.

Embeds a progress bar, pause/stop buttons, and a log toggle
inside a QStatusBar via addPermanentWidget.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QSizePolicy, QStatusBar, QToolButton, QWidget,
)


class AppStatusBar(QStatusBar):
    """Bottom strip: status text + progress + controls."""

    pause_clicked = pyqtSignal()
    stop_clicked  = pyqtSignal()
    log_clicked   = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizeGripEnabled(True)
        self._build()

    def _build(self) -> None:
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(6, 2, 4, 2)
        row.setSpacing(8)

        # Status text
        self._status_lbl = QLabel("Idle")
        self._status_lbl.setMinimumWidth(160)
        self._status_lbl.setStyleSheet("color: #888; font-size: 12px;")
        row.addWidget(self._status_lbl)

        # Progress bar (hidden when idle)
        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedHeight(12)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._progress_bar.setVisible(False)
        row.addWidget(self._progress_bar, 1)

        # Count label ("12 / 34")
        self._count_lbl = QLabel("")
        self._count_lbl.setMinimumWidth(70)
        self._count_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._count_lbl.setStyleSheet("color: #888; font-size: 12px;")
        self._count_lbl.setVisible(False)
        row.addWidget(self._count_lbl)

        # Pause button
        self._pause_btn = QPushButton("⏸  Pause")
        self._pause_btn.setFixedSize(82, 22)
        self._pause_btn.setVisible(False)
        self._pause_btn.clicked.connect(self.pause_clicked)
        row.addWidget(self._pause_btn)

        # Stop button
        self._stop_btn = QPushButton("■  Stop")
        self._stop_btn.setFixedSize(70, 22)
        self._stop_btn.setStyleSheet("color: #c62828;")
        self._stop_btn.setVisible(False)
        self._stop_btn.clicked.connect(self.stop_clicked)
        row.addWidget(self._stop_btn)

        # Log toggle
        self._log_btn = QToolButton()
        self._log_btn.setText("📋")
        self._log_btn.setToolTip("Batch history / undo")
        self._log_btn.setFixedSize(32, 26)
        self._log_btn.setStyleSheet("font-size: 15px;")
        self._log_btn.clicked.connect(self.log_clicked)
        row.addWidget(self._log_btn)

        self.addPermanentWidget(container, 1)

    # ── Public interface ──────────────────────────────────────────────

    def set_running(self, total: int) -> None:
        self._progress_bar.setRange(0, max(total, 1))
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(True)
        self._count_lbl.setText(f"0 / {total}")
        self._count_lbl.setVisible(True)
        self._pause_btn.setText("⏸  Pause")
        self._pause_btn.setVisible(True)
        self._stop_btn.setVisible(True)
        self._status_lbl.setText("Starting…")

    def update_progress(self, done: int, total: int) -> None:
        self._progress_bar.setMaximum(max(total, 1))
        self._progress_bar.setValue(done)
        self._count_lbl.setText(f"{done} / {total}")

    def set_paused(self, paused: bool) -> None:
        self._pause_btn.setText("▶  Resume" if paused else "⏸  Pause")

    def set_status(self, msg: str) -> None:
        truncated = msg[:80] + "…" if len(msg) > 80 else msg
        self._status_lbl.setText(truncated)

    def set_complete(self, done: int, errors: int, skipped: int, total: int) -> None:
        self._progress_bar.setValue(total)
        self._pause_btn.setVisible(False)
        self._stop_btn.setVisible(False)
        parts = [f"{done} done"]
        if errors:  parts.append(f"{errors} error{'s' if errors != 1 else ''}")
        if skipped: parts.append(f"{skipped} skipped")
        self._status_lbl.setText("Complete — " + ", ".join(parts))
        self._count_lbl.setText(f"{total} / {total}")

    def set_idle(self) -> None:
        self._progress_bar.setVisible(False)
        self._count_lbl.setVisible(False)
        self._pause_btn.setVisible(False)
        self._stop_btn.setVisible(False)
        self._status_lbl.setText("Idle")
