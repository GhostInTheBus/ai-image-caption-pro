"""
MainWindow — full persistent QMainWindow replacing FloatingWindow.

Three-column QSplitter layout:
  Left   — DropPanel    (drop zone + Start / Undo / Clear)
  Center — QueuePanel   (file list + caption preview)
  Right  — QuickSettingsPanel (per-shoot AI controls, collapsible)

Bottom — AppStatusBar (progress bar + Pause / Stop / Log)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QEvent, QSize, Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QIcon
from PyQt6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox,
    QHBoxLayout, QHeaderView, QLabel, QMainWindow,
    QMessageBox, QPushButton, QSizePolicy,
    QSplitter, QTableWidget, QTableWidgetItem,
    QToolButton, QVBoxLayout, QWidget,
)

from app.core.agent import BatchWorker, IMAGE_EXTENSIONS, make_batch_id, scan_folder
from app.core.captioner import list_available_models
from app.core.exiftool import restore_iptc
from app.models import Settings
from app.ui.drop_panel import DropPanel
from app.ui.queue_panel import QueuePanel
from app.ui.quick_settings_panel import QuickSettingsPanel
from app.ui.settings_dialog import SettingsDialog, load_settings, save_settings
from app.ui.status_bar import AppStatusBar
from app.ui.style import APP_STYLE

# Regex to detect the "done" status line emitted by agent.py:283
# e.g. "✓ DSC_0042.CR3: 312 char caption, 8 keyword(s)"
_DONE_RE = re.compile(r"^✓ ([^:]+):(.+)$")


class MainWindow(QMainWindow):
    """Main application window."""

    status_changed = pyqtSignal(str)
    batch_finished = pyqtSignal(int, int)

    def __init__(self):
        super().__init__()
        self.settings: Settings = load_settings()

        self._worker: Optional[BatchWorker] = None
        self._thread: Optional[QThread] = None
        self._staged_folder: Optional[Path] = None
        self._staged_files: Optional[list[Path]] = None
        self._current_batch_id: Optional[str] = None
        self._last_status_by_file: dict[str, str] = {}

        self._right_panel_collapsed: bool = False
        self._right_panel_width: int = 320

        self._setup_window()
        self._build_ui()
        self._check_for_resume()
        QApplication.instance().applicationStateChanged.connect(self._on_app_state_changed)

    # ── Window setup ──────────────────────────────────────────────────

    def _setup_window(self) -> None:
        self.setWindowTitle("AI Image Caption Pro")
        self.setMinimumSize(860, 520)
        self.resize(1100, 680)
        self.setAcceptDrops(True)
        self.setStyleSheet(APP_STYLE)

        icon_path = Path(__file__).parent.parent.parent / "assets" / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

    # ── UI construction ───────────────────────────────────────────────

    def _build_ui(self) -> None:
        # ── Toolbar ───────────────────────────────────────────────────
        toolbar = self.addToolBar("Main")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setObjectName("MainToolBar")
        toolbar.setIconSize(QSize(24, 24))
        toolbar.setFixedHeight(42)

        title_lbl = QLabel("📷  AI Image Caption Pro")
        title_lbl.setStyleSheet(
            "font-weight: bold; font-size: 14px; color: #89b4fa; padding: 0 8px; background: transparent;"
        )
        toolbar.addWidget(title_lbl)

        toolbar.addSeparator()

        backend_prefix = QLabel("Backend:")
        backend_prefix.setStyleSheet("color: #888; font-size: 12px; background: transparent;")
        toolbar.addWidget(backend_prefix)

        self._toolbar_backend_lbl = QLabel(self.settings.backend)
        self._toolbar_backend_lbl.setStyleSheet(
            "color: #cdd6f4; font-size: 12px; padding-right: 4px; background: transparent;"
        )
        toolbar.addWidget(self._toolbar_backend_lbl)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        spacer.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        toolbar.addWidget(spacer)

        self._collapse_btn = QToolButton()
        self._collapse_btn.setText("⊟")
        self._collapse_btn.setToolTip("Collapse / expand Quick Settings panel")
        self._collapse_btn.setFixedSize(34, 34)
        self._collapse_btn.setStyleSheet("font-size: 18px;")
        self._collapse_btn.clicked.connect(self._toggle_right_panel)
        toolbar.addWidget(self._collapse_btn)

        settings_btn = QToolButton()
        settings_btn.setText("⚙")
        settings_btn.setToolTip("Settings — identity, location, publication, contact")
        settings_btn.setFixedSize(34, 34)
        settings_btn.setStyleSheet("font-size: 18px;")
        settings_btn.clicked.connect(self._open_settings)
        toolbar.addWidget(settings_btn)

        # ── Three-column splitter ──────────────────────────────────────
        available_models = list_available_models(self.settings.ollama_host)

        self._drop_panel = DropPanel(parent=self)
        self._queue_panel = QueuePanel(parent=self)
        self._quick_panel = QuickSettingsPanel(
            settings=self.settings,
            available_models=available_models,
            parent=self,
        )
        # Prevent child panels from intercepting drag events
        self._drop_panel.setAcceptDrops(False)
        self._queue_panel.setAcceptDrops(False)
        self._quick_panel.setAcceptDrops(False)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.addWidget(self._drop_panel)
        self._splitter.addWidget(self._queue_panel)
        self._splitter.addWidget(self._quick_panel)
        self._splitter.setSizes([200, 580, 320])
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setStretchFactor(2, 0)

        # ── Log drawer (hidden by default) ────────────────────────────
        self._log_drawer = _LogDrawer(parent=self)
        self._log_drawer.setVisible(False)
        self._log_drawer.undo_requested.connect(self._undo_specific_batch)

        # ── Central widget: splitter + log drawer ─────────────────────
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self._splitter, 1)
        central_layout.addWidget(self._log_drawer, 0)
        self.setCentralWidget(central)

        # ── Status bar ─────────────────────────────────────────────────
        self._status_bar = AppStatusBar(parent=self)
        self.setStatusBar(self._status_bar)

        # ── Signal wiring ─────────────────────────────────────────────
        self._drop_panel.start_clicked.connect(self._start_from_staging)
        self._drop_panel.undo_clicked.connect(self._undo_batch)
        self._drop_panel.clear_clicked.connect(self._cancel_staging)

        self._status_bar.pause_clicked.connect(self._toggle_pause)
        self._status_bar.stop_clicked.connect(self._stop_batch)
        self._status_bar.log_clicked.connect(self._toggle_log_drawer)

        self._quick_panel.settings_changed.connect(self._on_quick_settings_changed)
        self._queue_panel.files_removed.connect(self._on_files_removed)

    # ── Drag-and-drop (handled at QMainWindow level) ──────────────────

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                p = Path(url.toLocalFile())
                if p.is_dir() or (p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS):
                    event.acceptProposedAction()
                    self._drop_panel.set_drag_highlight(True)
                    return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._drop_panel.set_drag_highlight(False)

    def dropEvent(self, event: QDropEvent) -> None:
        self._drop_panel.set_drag_highlight(False)
        if self._thread and self._thread.isRunning():
            QMessageBox.information(self, "Busy", "A batch is already running. Stop it first.")
            return

        urls = event.mimeData().urls()
        if not urls:
            return

        folders: list[Path] = []
        loose_files: list[Path] = []
        for url in urls:
            p = Path(url.toLocalFile())
            if p.is_dir():
                folders.append(p)
            elif p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS:
                loose_files.append(p)

        if folders:
            folder = folders[0]
            file_list = scan_folder(folder, self.settings.recursive_scan)
        elif loose_files:
            folder = loose_files[0].parent
            file_list = loose_files
        else:
            return

        if not file_list:
            QMessageBox.warning(self, "No Images", f"No image files found in:\n{folder}")
            return

        self._stage_files(folder, file_list)

    # ── Staging ───────────────────────────────────────────────────────

    def _stage_files(self, folder: Path, file_list: list[Path]) -> None:
        self._staged_folder = folder
        self._staged_files = file_list
        self._drop_panel.stage_files(folder, file_list)
        self._queue_panel.set_folder(folder.name, len(file_list))
        for f in file_list:
            self._queue_panel.add_file(f.name)

    def _cancel_staging(self) -> None:
        self._staged_folder = None
        self._staged_files = None
        self._drop_panel.clear_staged()
        self._queue_panel.clear()

    def _on_files_removed(self, filenames: list) -> None:
        """Remove files from the staged list when the user deletes them from the queue."""
        if not self._staged_files:
            return
        name_set = set(filenames)
        self._staged_files = [f for f in self._staged_files if f.name not in name_set]
        # Update the left panel's count label
        self._drop_panel.stage_files(
            self._staged_folder, self._staged_files
        ) if self._staged_files else self._cancel_staging()

    def _start_from_staging(self) -> None:
        if not self._staged_folder or not self._staged_files:
            return
        force = self._drop_panel.force_reprocess_requested()
        self._launch_batch(
            folder=self._staged_folder,
            file_list=self._staged_files,
            force=force,
        )

    # ── Batch lifecycle ───────────────────────────────────────────────

    def _launch_batch(self, folder: Path, file_list: list[Path], force: bool = False) -> None:
        self._current_batch_id = make_batch_id(folder)
        self._last_status_by_file.clear()

        if force:
            from app.core.job_db import reset_batch_for_reprocess
            reset_batch_for_reprocess(self._current_batch_id)

        self._drop_panel.set_batch_running(True)
        self._status_bar.set_running(len(file_list))

        self._worker = BatchWorker(folder=folder, settings=self.settings, files=file_list)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.job_started.connect(self._on_job_started)
        self._worker.job_done.connect(self._on_job_done)
        self._worker.job_error.connect(self._on_job_error)
        self._worker.job_skipped.connect(self._on_job_skipped)
        self._worker.progress.connect(self._on_progress)
        self._worker.status_msg.connect(self._on_status)
        self._worker.batch_complete.connect(self._on_batch_complete)

        self._thread.start()

    def _toggle_pause(self) -> None:
        if self._worker:
            if self._worker._pause_requested:
                self._worker.resume_processing()
                self._status_bar.set_paused(False)
                self._drop_panel.set_batch_paused(False)
            else:
                self._worker.pause()
                self._status_bar.set_paused(True)
                self._drop_panel.set_batch_paused(True)

    def _stop_batch(self) -> None:
        if self._worker:
            self._worker.stop()

    # ── Worker signal slots ───────────────────────────────────────────

    @pyqtSlot(str)
    def _on_job_started(self, filename: str) -> None:
        self._queue_panel.set_running(filename)

    @pyqtSlot(str)
    def _on_job_done(self, filename: str) -> None:
        self._queue_panel.set_done(filename)
        cached = self._last_status_by_file.get(filename, "")
        self._queue_panel.update_caption_preview(filename, cached)

    @pyqtSlot(str, str)
    def _on_job_error(self, filename: str, msg: str) -> None:
        self._queue_panel.set_error(filename, msg)

    @pyqtSlot(str)
    def _on_job_skipped(self, filename: str) -> None:
        self._queue_panel.set_skipped(filename)

    @pyqtSlot(int, int)
    def _on_progress(self, done: int, total: int) -> None:
        self._queue_panel.update_progress(done, total)
        self._status_bar.update_progress(done, total)

    @pyqtSlot(str)
    def _on_status(self, msg: str) -> None:
        self._status_bar.set_status(msg)
        self.status_changed.emit(msg)
        # Cache the completion line so caption preview can display it
        m = _DONE_RE.match(msg)
        if m:
            filename = m.group(1).strip()
            detail   = m.group(2).strip()
            self._last_status_by_file[filename] = detail

    @pyqtSlot(int, int, int, int)
    def _on_batch_complete(self, done: int, errors: int, skipped: int, total: int) -> None:
        self._status_bar.set_complete(done, errors, skipped, total)
        self._drop_panel.set_batch_complete(done, errors)
        self._queue_panel.set_batch_complete()
        if self._thread:
            self._thread.quit()
            self._thread.wait()
        self.status_changed.emit("Idle")
        self.batch_finished.emit(done, errors)

    # ── Right panel collapse ──────────────────────────────────────────

    def _toggle_right_panel(self) -> None:
        sizes = self._splitter.sizes()
        if self._right_panel_collapsed:
            sizes[2] = self._right_panel_width
            self._splitter.setSizes(sizes)
            self._quick_panel.setVisible(True)
            self._collapse_btn.setText("⊟")
            self._right_panel_collapsed = False
        else:
            self._right_panel_width = max(sizes[2], 220)
            self._quick_panel.setVisible(False)
            sizes[2] = 0
            self._splitter.setSizes(sizes)
            self._collapse_btn.setText("⊞")
            self._right_panel_collapsed = True

    # ── Undo ─────────────────────────────────────────────────────────

    def _undo_batch(self) -> None:
        """Undo the current batch (triggered from DropPanel ↩ button)."""
        self._undo_specific_batch(self._current_batch_id)

    def _undo_specific_batch(self, batch_id: Optional[str]) -> None:
        if not batch_id:
            return
        from app.core import job_db

        originals = job_db.get_batch_originals(batch_id)
        if not originals:
            QMessageBox.information(self, "Undo", "No original metadata found for this batch.\n(May already have been restored.)")
            return

        # Disable undo button to prevent double-undo
        self._drop_panel._undo_btn.setEnabled(False)
        self._status_bar.set_status(f"Undoing {len(originals)} file(s)…")

        failed = 0
        for item in originals:
            try:
                restore_iptc(
                    file_path=Path(item["file_path"]),
                    original_caption=item["original_caption"] or None,
                    original_keywords=item["original_keywords"],
                )
            except Exception as e:
                failed += 1
                print(f"[undo error] {item['file_path']}: {e}", file=sys.stderr)

        restored = len(originals) - failed
        msg = f"Undone — {restored} file(s) restored."
        if failed:
            msg += f"  ({failed} failed — see terminal)"
        self._status_bar.set_status(msg)
        self._drop_panel.set_batch_undone()

    # ── Quick settings ────────────────────────────────────────────────

    def _on_quick_settings_changed(self, new_settings) -> None:
        self.settings = new_settings
        self._toolbar_backend_lbl.setText(new_settings.backend)

    # ── Settings dialog ───────────────────────────────────────────────

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, parent=self)
        if dlg.exec():
            self.settings = load_settings()
            self._quick_panel.refresh_from_settings(self.settings)
            self._toolbar_backend_lbl.setText(self.settings.backend)

    # ── Log drawer ────────────────────────────────────────────────────

    def _toggle_log_drawer(self) -> None:
        visible = not self._log_drawer.isVisible()
        self._log_drawer.setVisible(visible)
        if visible:
            self._log_drawer.refresh()

    # ── Auto-resume on launch ─────────────────────────────────────────

    def _check_for_resume(self) -> None:
        from app.core import job_db
        job_db.init_db()
        incomplete = job_db.get_all_incomplete_batches()
        if not incomplete:
            return
        reply = QMessageBox.question(
            self, "Resume Previous Batch?",
            f"{len(incomplete)} unfinished batch(es) detected from a previous run.\nResume processing?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            for batch_id in incomplete:
                folder = job_db.get_batch_folder(batch_id)
                if folder and folder.exists():
                    file_list = scan_folder(folder, self.settings.recursive_scan)
                    if file_list:
                        self._stage_files(folder, file_list)
                    break

    # ── App state ─────────────────────────────────────────────────────

    def _on_app_state_changed(self, state) -> None:
        if state == Qt.ApplicationState.ApplicationActive and self.isVisible():
            self.raise_()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            self.raise_()
        super().changeEvent(event)

    def closeEvent(self, event) -> None:
        if self._worker and self._thread and self._thread.isRunning():
            self._worker.stop()
            self._thread.quit()
            self._thread.wait(3000)
        super().closeEvent(event)


# ── Log Drawer ────────────────────────────────────────────────────────────────

class _LogDrawer(QWidget):
    """
    Inline batch history panel that slides up from below the splitter.
    Replaces the modal log dialog.
    """

    undo_requested = pyqtSignal(str)   # emits batch_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(240)
        self.setStyleSheet("background: #181825; border-top: 1px solid #313244;")
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 8)
        layout.setSpacing(6)

        # Header
        header = QHBoxLayout()
        title = QLabel("Batch History")
        title.setStyleSheet("font-weight: bold; color: #cdd6f4; font-size: 13px; background: transparent;")
        close_btn = QToolButton()
        close_btn.setText("✕")
        close_btn.setFixedSize(22, 22)
        close_btn.clicked.connect(self.hide)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(close_btn)
        layout.addLayout(header)

        # Table
        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(["Folder", "Date", "Done", "Errors", "Skipped", ""])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        for col in (2, 3, 4, 5):
            self._table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        layout.addWidget(self._table)

        # Bottom action buttons
        btn_row = QHBoxLayout()
        clear_err_btn = QPushButton("Clear Errors / Incomplete")
        clear_err_btn.setStyleSheet("color: #e57373;")
        clear_err_btn.clicked.connect(self._do_clear_incomplete)
        clear_all_btn = QPushButton("Clear All History")
        clear_all_btn.setStyleSheet("color: #e57373;")
        clear_all_btn.clicked.connect(self._do_clear_all)
        btn_row.addWidget(clear_err_btn)
        btn_row.addWidget(clear_all_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def refresh(self) -> None:
        from app.core.job_db import get_recent_batches
        batches = get_recent_batches(limit=20)
        self._table.setRowCount(len(batches))

        for row, b in enumerate(batches):
            name = Path(b["folder_path"]).name
            date = (b["created_at"] or "")[:16]
            done_count = b["done"] or 0
            for col, val in enumerate([name, date, str(done_count),
                                        str(b["errors"] or 0), str(b["skipped"] or 0)]):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._table.setItem(row, col, item)

            undo_btn = QPushButton("↩ Undo")
            undo_btn.setStyleSheet("color: #f9e2af; padding: 1px 5px;")
            undo_btn.setEnabled(done_count > 0)
            undo_btn.setToolTip("Restore all files in this batch to pre-AI metadata")
            batch_id = b["batch_id"]

            def _make_handler(bid, btn):
                def handler():
                    reply = QMessageBox.question(
                        self, "Undo Batch?",
                        f"Restore all files in this batch to their pre-AI metadata?\n\nThis cannot itself be undone.",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    )
                    if reply == QMessageBox.StandardButton.Yes:
                        btn.setEnabled(False)
                        self.undo_requested.emit(bid)
                return handler

            undo_btn.clicked.connect(_make_handler(batch_id, undo_btn))
            self._table.setCellWidget(row, 5, undo_btn)

    def _do_clear_incomplete(self) -> None:
        from app.core.job_db import clear_incomplete_jobs
        n = clear_incomplete_jobs()
        QMessageBox.information(self, "Cleared", f"Removed {n} incomplete job(s).")
        self.refresh()

    def _do_clear_all(self) -> None:
        reply = QMessageBox.question(
            self, "Clear All?",
            "This removes all job history. All files will be reprocessed on next drop.\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            from app.core.job_db import clear_all_jobs
            clear_all_jobs()
            self.refresh()
