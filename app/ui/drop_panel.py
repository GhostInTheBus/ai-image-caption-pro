"""
DropPanel — left column of the main window.

Always-visible drop target + Start / Undo / Clear controls.
Emits signals upward; owns no thread state.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)


class DropPanel(QWidget):
    """Left column: drop zone + batch controls."""

    start_clicked = pyqtSignal()
    undo_clicked  = pyqtSignal()
    clear_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._staged_folder: Optional[Path] = None
        self._staged_files: Optional[list[Path]] = None
        self._build_ui()

    # ── Build ─────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(8)

        # Drop target visual
        self._drop_target = QLabel()
        self._drop_target.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._drop_target.setText("📂\n\nDrop photos or\na folder here\n\nRAW · JPEG · PSD")
        self._drop_target.setWordWrap(True)
        self._drop_target.setMinimumHeight(140)
        self._drop_target.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._drop_target.setStyleSheet(
            "QLabel {"
            "  border: 2px dashed #45475a;"
            "  border-radius: 8px;"
            "  color: #585b70;"
            "  font-size: 13px;"
            "  padding: 16px;"
            "}"
        )
        layout.addWidget(self._drop_target, 1)

        # File count label (hidden when no files staged)
        self._count_lbl = QLabel()
        self._count_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._count_lbl.setStyleSheet("color: #888; font-size: 12px;")
        self._count_lbl.setVisible(False)
        layout.addWidget(self._count_lbl)

        # Force-reprocess checkbox (hidden until files staged)
        self._force_check = QCheckBox("Re-process already-captioned")
        self._force_check.setChecked(False)
        self._force_check.setStyleSheet("color: #888; font-size: 11px;")
        self._force_check.setVisible(False)
        layout.addWidget(self._force_check)

        # Button strip
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self._clear_btn = QPushButton("← Clear")
        self._clear_btn.setFixedHeight(28)
        self._clear_btn.setVisible(False)
        self._clear_btn.clicked.connect(self.clear_clicked)

        self._start_btn = QPushButton("▶  Start")
        self._start_btn.setFixedHeight(32)
        self._start_btn.setEnabled(False)
        self._start_btn.setStyleSheet(
            "QPushButton {"
            "  background: #1a472a; color: #a6e3a1;"
            "  border: 1px solid #a6e3a1; border-radius: 4px;"
            "  font-size: 14px; font-weight: bold;"
            "}"
            "QPushButton:hover { background: #1e5c35; }"
            "QPushButton:disabled { background: #1e1e2e; color: #45475a; border-color: #313244; }"
        )
        self._start_btn.clicked.connect(self.start_clicked)

        btn_row.addWidget(self._clear_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._start_btn)
        layout.addLayout(btn_row)

        # Undo button (shown only after batch completes with done > 0)
        self._undo_btn = QPushButton("↩  Undo Last Batch")
        self._undo_btn.setFixedHeight(28)
        self._undo_btn.setVisible(False)
        self._undo_btn.setStyleSheet(
            "QPushButton { color: #f9e2af; border-color: #f9e2af; }"
            "QPushButton:hover { background: #3d3621; }"
            "QPushButton:disabled { color: #585b70; border-color: #313244; }"
        )
        self._undo_btn.setToolTip("Restore all files in the last batch to their pre-AI metadata")
        self._undo_btn.clicked.connect(self.undo_clicked)
        layout.addWidget(self._undo_btn)

        # State label
        self._state_lbl = QLabel("Idle — drop files to begin")
        self._state_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._state_lbl.setStyleSheet("color: #585b70; font-size: 11px;")
        layout.addWidget(self._state_lbl)

    # ── Public interface (called by MainWindow) ───────────────────────

    def stage_files(self, folder: Path, file_list: list[Path]) -> None:
        self._staged_folder = folder
        self._staged_files = file_list
        n = len(file_list)
        self._count_lbl.setText(f"{n} file{'s' if n != 1 else ''} ready")
        self._count_lbl.setVisible(True)
        self._force_check.setVisible(True)
        self._clear_btn.setVisible(True)
        self._start_btn.setEnabled(True)
        self._undo_btn.setVisible(False)
        self._state_lbl.setText(f"{folder.name}")
        self._state_lbl.setStyleSheet("color: #89b4fa; font-size: 11px; font-weight: bold;")

    def clear_staged(self) -> None:
        self._staged_folder = None
        self._staged_files = None
        self._count_lbl.setVisible(False)
        self._force_check.setVisible(False)
        self._force_check.setChecked(False)
        self._clear_btn.setVisible(False)
        self._start_btn.setEnabled(False)
        self._undo_btn.setVisible(False)
        self._state_lbl.setText("Idle — drop files to begin")
        self._state_lbl.setStyleSheet("color: #585b70; font-size: 11px;")

    def set_batch_running(self, running: bool) -> None:
        self._start_btn.setEnabled(False)
        self._clear_btn.setVisible(False)
        self._force_check.setVisible(False)
        self._undo_btn.setVisible(False)
        self._state_lbl.setText("Running…")
        self._state_lbl.setStyleSheet("color: #f0a500; font-size: 11px;")

    def set_batch_paused(self, paused: bool) -> None:
        if paused:
            self._state_lbl.setText("Paused")
            self._state_lbl.setStyleSheet("color: #888; font-size: 11px;")
        else:
            self._state_lbl.setText("Running…")
            self._state_lbl.setStyleSheet("color: #f0a500; font-size: 11px;")

    def set_batch_complete(self, done: int, errors: int) -> None:
        # Re-enable Start so the user can re-run the same files (e.g. after a partial stop)
        self._start_btn.setEnabled(True)
        self._clear_btn.setVisible(True)
        self._force_check.setVisible(True)   # show re-process checkbox again
        parts = [f"{done} done"]
        if errors:
            parts.append(f"{errors} error{'s' if errors != 1 else ''}")
        self._state_lbl.setText("Complete — " + ", ".join(parts))
        self._state_lbl.setStyleSheet("color: #4caf50; font-size: 11px;")
        if done > 0:
            self._undo_btn.setVisible(True)
            self._undo_btn.setEnabled(True)

    def set_batch_undone(self) -> None:
        """Called after undo completes — re-enables Start so the user can re-run."""
        self._start_btn.setEnabled(True)
        self._force_check.setVisible(True)
        self._undo_btn.setVisible(False)
        self._state_lbl.setText("Undone — ready to re-run")
        self._state_lbl.setStyleSheet("color: #888; font-size: 11px;")

    def force_reprocess_requested(self) -> bool:
        return self._force_check.isChecked()

    def set_drag_highlight(self, on: bool) -> None:
        if on:
            self._drop_target.setStyleSheet(
                "QLabel {"
                "  border: 2px dashed #89b4fa;"
                "  border-radius: 8px;"
                "  background: #1a243a;"
                "  color: #89b4fa;"
                "  font-size: 13px;"
                "  padding: 16px;"
                "}"
            )
        else:
            self._drop_target.setStyleSheet(
                "QLabel {"
                "  border: 2px dashed #45475a;"
                "  border-radius: 8px;"
                "  color: #585b70;"
                "  font-size: 13px;"
                "  padding: 16px;"
                "}"
            )
