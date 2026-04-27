"""
QueuePanel — center column of the main window.

Shows the per-file status list (reusing FileRow from progress_panel)
and a caption preview pane at the bottom.

Files can be click-selected (single or Ctrl/Cmd-click multi-select)
and removed from the pending queue via the Delete toolbar button
or the Delete / Backspace key.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from app.ui.progress_panel import FileRow


class QueuePanel(QWidget):
    """Center column: scrollable file list + caption preview."""

    # Emitted when the user removes files; list of filenames (str)
    files_removed = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: dict[str, FileRow] = {}
        self._selected: set[str] = set()
        self._batch_running: bool = False
        self._build_ui()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # ── Build ─────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Folder header bar ─────────────────────────────────────────
        header_bar = QWidget()
        header_bar.setFixedHeight(30)
        header_bar.setStyleSheet("background: #181825; border-bottom: 1px solid #313244;")
        header_layout = QHBoxLayout(header_bar)
        header_layout.setContentsMargins(10, 0, 6, 0)

        self._folder_lbl = QLabel("No files loaded")
        self._folder_lbl.setStyleSheet(
            "font-size: 13px; font-weight: bold; color: #89b4fa; background: transparent;"
        )
        self._count_lbl = QLabel("")
        self._count_lbl.setStyleSheet("color: #888; font-size: 12px; background: transparent;")
        self._count_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Delete selection button — hidden when nothing selected
        self._delete_btn = QPushButton("✕  Remove selected")
        self._delete_btn.setFixedHeight(22)
        self._delete_btn.setStyleSheet(
            "QPushButton { font-size: 11px; color: #f38ba8; background: #313244;"
            " border: 1px solid #f38ba8; border-radius: 3px; padding: 0 6px; }"
            "QPushButton:hover { background: #45475a; }"
        )
        self._delete_btn.setVisible(False)
        self._delete_btn.clicked.connect(self._remove_selected)

        header_layout.addWidget(self._folder_lbl, 1)
        header_layout.addWidget(self._count_lbl)
        header_layout.addSpacing(6)
        header_layout.addWidget(self._delete_btn)
        layout.addWidget(header_bar)

        # ── Scrollable file list ──────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 2, 0, 2)
        self._list_layout.setSpacing(0)
        self._list_layout.addStretch(1)

        self._scroll.setWidget(self._list_widget)
        layout.addWidget(self._scroll, 1)

        # ── Caption preview pane ──────────────────────────────────────
        preview = QFrame()
        preview.setFixedHeight(110)
        preview.setStyleSheet(
            "QFrame { background: #181825; border-top: 1px solid #313244; }"
        )
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(10, 6, 10, 6)
        preview_layout.setSpacing(3)

        self._preview_filename_lbl = QLabel("—")
        self._preview_filename_lbl.setStyleSheet(
            "color: #888; font-size: 11px; background: transparent;"
        )

        self._preview_caption_lbl = QLabel("")
        self._preview_caption_lbl.setWordWrap(True)
        self._preview_caption_lbl.setStyleSheet(
            "color: #cdd6f4; font-size: 12px; background: transparent;"
        )
        self._preview_caption_lbl.setMaximumHeight(54)   # ~3 lines at 12px
        self._preview_caption_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        self._preview_keywords_lbl = QLabel("")
        self._preview_keywords_lbl.setStyleSheet(
            "color: #888; font-size: 11px; font-style: italic; background: transparent;"
        )
        self._preview_keywords_lbl.setWordWrap(True)
        self._preview_keywords_lbl.setMaximumHeight(24)

        preview_layout.addWidget(self._preview_filename_lbl)
        preview_layout.addWidget(self._preview_caption_lbl, 1)
        preview_layout.addWidget(self._preview_keywords_lbl)
        layout.addWidget(preview)

    # ── Public interface ──────────────────────────────────────────────

    def set_folder(self, folder_name: str, total: int) -> None:
        self._folder_lbl.setText(folder_name)
        self._count_lbl.setText(f"0 / {total}")
        self._clear_rows()
        self._preview_filename_lbl.setText("—")
        self._preview_caption_lbl.setText("")
        self._preview_keywords_lbl.setText("")

    def add_file(self, filename: str) -> None:
        if filename in self._rows:
            return
        row = FileRow(filename)
        # Make each row click-selectable
        row.setProperty("filename", filename)
        row.mousePressEvent = lambda e, fn=filename: self._on_row_click(fn, e)
        count = self._list_layout.count()
        self._list_layout.insertWidget(count - 1, row)
        self._rows[filename] = row

    def set_running(self, filename: str) -> None:
        self._batch_running = True
        self._ensure_row(filename).set_running()
        # Clear preview for the new active file
        self._preview_filename_lbl.setText(filename)
        self._preview_caption_lbl.setText("Processing…")
        self._preview_caption_lbl.setStyleSheet(
            "color: #585b70; font-size: 12px; background: transparent;"
        )
        self._preview_keywords_lbl.setText("")
        # Auto-scroll to the active row
        row_widget = self._rows.get(filename)
        if row_widget:
            QTimer.singleShot(0, lambda: self._scroll.ensureWidgetVisible(row_widget))

    def set_done(self, filename: str) -> None:
        self._ensure_row(filename).set_done()

    def set_error(self, filename: str, msg: str = "") -> None:
        self._ensure_row(filename).set_error(msg)

    def set_skipped(self, filename: str) -> None:
        self._ensure_row(filename).set_skipped()

    def set_batch_complete(self) -> None:
        """Called when the batch finishes so deletion is re-enabled."""
        self._batch_running = False

    def update_progress(self, done: int, total: int) -> None:
        self._count_lbl.setText(f"{done} / {total}")

    def update_caption_preview(self, filename: str, status_line: str) -> None:
        """
        Populate the preview pane after a file completes.
        status_line is the cached status_msg, e.g.:
          "312 char caption, 8 keyword(s)"
        """
        self._preview_filename_lbl.setText(filename)
        self._preview_caption_lbl.setText(status_line or "Done")
        self._preview_caption_lbl.setStyleSheet(
            "color: #cdd6f4; font-size: 12px; background: transparent;"
        )
        self._preview_keywords_lbl.setText("")

    def clear(self) -> None:
        self._batch_running = False
        self._clear_rows()
        self._folder_lbl.setText("No files loaded")
        self._count_lbl.setText("")
        self._preview_filename_lbl.setText("—")
        self._preview_caption_lbl.setText("")
        self._preview_keywords_lbl.setText("")

    # ── Selection ─────────────────────────────────────────────────────

    def _on_row_click(self, filename: str, event) -> None:
        """Toggle selection; Ctrl/Cmd adds to selection, plain click is exclusive."""
        modifiers = event.modifiers()
        multi = bool(modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier))

        if multi:
            if filename in self._selected:
                self._selected.discard(filename)
            else:
                self._selected.add(filename)
        else:
            # Plain click: deselect all, select only this one
            prev = set(self._selected)
            self._selected = {filename}
            for fn in prev - {filename}:
                self._apply_row_style(fn, selected=False)

        self._apply_row_style(filename, filename in self._selected)
        self._update_delete_btn()

    def _apply_row_style(self, filename: str, selected: bool) -> None:
        row = self._rows.get(filename)
        if row:
            if selected:
                row.setStyleSheet("background: #313244; border-left: 3px solid #89b4fa;")
            else:
                row.setStyleSheet("")

    def _update_delete_btn(self) -> None:
        # Only allow deletion of pending (unstarted) files
        removable = self._removable_selected()
        self._delete_btn.setVisible(bool(removable))
        if removable:
            n = len(removable)
            self._delete_btn.setText(f"✕  Remove {n} file{'s' if n != 1 else ''}")

    def _removable_selected(self) -> list[str]:
        """Selected filenames that have not yet started processing (still show · icon)."""
        from app.ui.progress_panel import ICON_PENDING
        out = []
        for fn in self._selected:
            row = self._rows.get(fn)
            if row and row.icon_label.text() == ICON_PENDING:
                out.append(fn)
        return out

    def _remove_selected(self) -> None:
        removable = self._removable_selected()
        if not removable:
            return
        for fn in removable:
            row = self._rows.pop(fn, None)
            if row:
                self._list_layout.removeWidget(row)
                row.deleteLater()
            self._selected.discard(fn)
        self._update_delete_btn()
        self.files_removed.emit(removable)

    # ── Key handling ──────────────────────────────────────────────────

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._remove_selected()
        else:
            super().keyPressEvent(event)

    # ── Helpers ───────────────────────────────────────────────────────

    def _ensure_row(self, filename: str) -> FileRow:
        if filename not in self._rows:
            self.add_file(filename)
        return self._rows[filename]

    def _clear_rows(self) -> None:
        self._selected.clear()
        self._delete_btn.setVisible(False)
        for row in self._rows.values():
            self._list_layout.removeWidget(row)
            row.deleteLater()
        self._rows.clear()
