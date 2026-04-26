"""
Floating drop zone — the main app window.

Pages (QStackedWidget):
  0 — Drop zone    : idle, accepts drags
  1 — Staging      : files queued, waiting for Start button
  2 — Progress     : batch running
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import (
    QEvent, QPoint, Qt, QThread, pyqtSignal, pyqtSlot,
)
from PyQt6.QtGui import QColor, QDragEnterEvent, QDropEvent, QPalette
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from app.core.agent import BatchWorker, IMAGE_EXTENSIONS, make_batch_id, scan_folder
from app.core.captioner import list_available_models
from app.models import Settings
from app.ui.progress_panel import ProgressPanel
from app.ui.settings_dialog import SettingsDialog, load_settings, save_settings

MIN_W, MIN_H = 280, 240


class FloatingWindow(QWidget):
    """Main application window."""

    status_changed  = pyqtSignal(str)
    batch_finished  = pyqtSignal(int, int)

    def __init__(self):
        super().__init__()
        self.settings: Settings = load_settings()
        self._drag_origin: Optional[QPoint] = None
        self._worker: Optional[BatchWorker] = None
        self._thread: Optional[QThread] = None

        # Staged files waiting for Start button
        self._staged_folder: Optional[Path] = None
        self._staged_files: Optional[list[Path]] = None

        self._setup_window()
        self._build_ui()
        self._check_for_resume()
        QApplication.instance().applicationStateChanged.connect(self._on_app_state_changed)

    # ── Window setup ──────────────────────────────────────────────────────────

    def _setup_window(self) -> None:
        self.setWindowTitle("AI Image Caption Pro")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAcceptDrops(True)
        self.setMinimumSize(MIN_W, MIN_H)
        self.resize(MIN_W, MIN_H)

        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor("#1e1e2e"))
        pal.setColor(QPalette.ColorRole.WindowText, QColor("#cdd6f4"))
        self.setPalette(pal)
        self.setStyleSheet("""
            QWidget {
                background-color: #1e1e2e;
                color: #cdd6f4;
                font-family: -apple-system, 'Segoe UI', sans-serif;
                font-size: 13px;
            }
            QPushButton {
                background: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 4px;
                padding: 4px 10px;
            }
            QPushButton:hover { background: #45475a; }
            QProgressBar {
                border: 1px solid #45475a;
                border-radius: 3px;
                background: #313244;
                text-align: center;
                color: #cdd6f4;
            }
            QProgressBar::chunk { background: #89b4fa; border-radius: 3px; }
            QScrollArea { border: none; background: transparent; }
            QGroupBox {
                border: 1px solid #45475a;
                border-radius: 4px;
                margin-top: 8px;
                color: #cdd6f4;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; }
            QLineEdit, QComboBox, QSpinBox {
                background: #313244;
                border: 1px solid #45475a;
                border-radius: 3px;
                padding: 3px 6px;
                color: #cdd6f4;
            }
            QDialog { background: #1e1e2e; color: #cdd6f4; }
            QLabel { color: #cdd6f4; }
            QCheckBox { color: #cdd6f4; }
            QListWidget {
                background: #181825;
                border: 1px solid #313244;
                border-radius: 3px;
                color: #cdd6f4;
                font-size: 12px;
            }
            QListWidget::item { padding: 2px 4px; }
            QListWidget::item:selected { background: #313244; }
        """)

    # ── UI structure ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Title bar (draggable)
        title_bar = QWidget()
        title_bar.setFixedHeight(32)
        title_bar.setStyleSheet("background: #181825; border-bottom: 1px solid #313244;")
        title_bar.mousePressEvent   = self._title_mouse_press
        title_bar.mouseMoveEvent    = self._title_mouse_move
        title_bar.mouseReleaseEvent = self._title_mouse_release

        tbl = QHBoxLayout(title_bar)
        tbl.setContentsMargins(8, 0, 8, 0)
        title_lbl = QLabel("📷  AI Image Caption Pro")
        title_lbl.setStyleSheet("font-weight: bold; font-size: 14px; color: #89b4fa;")
        tbl.addWidget(title_lbl)
        tbl.addStretch()

        # Resize grip hint (top-right corner)
        grip_hint = QLabel("⌟")
        grip_hint.setStyleSheet("color: #45475a; font-size: 16px; padding-right: 2px;")
        grip_hint.setToolTip("Drag window edges to resize")
        tbl.addWidget(grip_hint)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(22, 22)
        close_btn.setStyleSheet(
            "background: transparent; border: none; color: #888; font-size: 14px; padding: 0;"
        )
        close_btn.setToolTip("Hide to menu bar")
        close_btn.clicked.connect(self.hide)
        tbl.addWidget(close_btn)

        root.addWidget(title_bar)

        self._stack = QStackedWidget()
        root.addWidget(self._stack, 1)

        # Page 0: drop zone
        self._drop_page = self._build_drop_page()
        self._stack.addWidget(self._drop_page)

        # Pages 1 & 2 are built dynamically per batch
        self._progress_panel: Optional[ProgressPanel] = None

    def _build_drop_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(6)

        icon_lbl = QLabel("📂")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet("font-size: 44px;")
        layout.addWidget(icon_lbl)

        hint = QLabel("Drop photos or a folder here")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("color: #888; font-size: 14px;")
        layout.addWidget(hint)

        hint2 = QLabel("RAW · JPEG · PSD supported")
        hint2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint2.setStyleSheet("color: #555; font-size: 12px;")
        layout.addWidget(hint2)

        # Batch-in-progress banner (hidden while idle)
        self._batch_status_btn = QPushButton("⟳  Batch in progress — tap to view")
        self._batch_status_btn.setStyleSheet(
            "background: #1e3a5f; color: #89b4fa; border: 1px solid #89b4fa;"
            "border-radius: 4px; padding: 5px 10px; font-size: 12px;"
        )
        self._batch_status_btn.clicked.connect(self._show_progress_panel)
        self._batch_status_btn.setVisible(False)
        layout.addWidget(self._batch_status_btn)

        toolbar = QWidget()
        tbl = QHBoxLayout(toolbar)
        tbl.setContentsMargins(8, 4, 8, 8)

        settings_btn = QPushButton("⚙ Settings")
        settings_btn.clicked.connect(self._open_settings)
        log_btn = QPushButton("📋 Log")
        log_btn.clicked.connect(self._open_log)

        tbl.addWidget(settings_btn)
        tbl.addStretch()
        tbl.addWidget(log_btn)

        layout.addStretch()
        layout.addWidget(toolbar)
        return page

    def _build_staging_page(self, folder: Path, file_list: list[Path]) -> QWidget:
        """Page shown after a drop, before the user clicks Start."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Header
        header = QHBoxLayout()
        folder_lbl = QLabel(f"<b>{folder.name}</b>")
        folder_lbl.setStyleSheet("font-size: 14px;")
        count_lbl = QLabel(f"{len(file_list)} file{'s' if len(file_list) != 1 else ''}")
        count_lbl.setStyleSheet("color: #888; font-size: 12px;")
        header.addWidget(folder_lbl)
        header.addStretch()
        header.addWidget(count_lbl)
        layout.addLayout(header)

        # File list
        file_list_widget = QListWidget()
        file_list_widget.setAlternatingRowColors(True)
        for f in file_list:
            item = QListWidgetItem(f.name)
            item.setToolTip(str(f))
            file_list_widget.addItem(item)
        layout.addWidget(file_list_widget, 1)

        # Force-reprocess checkbox (only shown if skip_already_done is on)
        self._force_reprocess_check = QCheckBox("Re-process files already captioned")
        self._force_reprocess_check.setChecked(False)
        self._force_reprocess_check.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(self._force_reprocess_check)

        # Buttons
        btn_row = QHBoxLayout()
        clear_btn = QPushButton("← Clear")
        clear_btn.clicked.connect(self._cancel_staging)

        start_btn = QPushButton("▶  Start")
        start_btn.setDefault(True)
        start_btn.setStyleSheet(
            "background: #1a472a; color: #a6e3a1; border: 1px solid #a6e3a1;"
            "border-radius: 4px; padding: 6px 16px; font-size: 14px; font-weight: bold;"
        )
        start_btn.clicked.connect(self._start_from_staging)

        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        btn_row.addWidget(start_btn)
        layout.addLayout(btn_row)

        return page

    # ── App state ─────────────────────────────────────────────────────────────

    def _on_app_state_changed(self, state) -> None:
        if state == Qt.ApplicationState.ApplicationActive and self.isVisible():
            self.raise_()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            self.raise_()
        super().changeEvent(event)

    # ── Drag and drop ─────────────────────────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                p = Path(url.toLocalFile())
                if p.is_dir() or (p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS):
                    event.acceptProposedAction()
                    self.setStyleSheet(self.styleSheet().replace("#1e1e2e", "#1a1a2e"))
                    return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self.setStyleSheet(self.styleSheet().replace("#1a1a2e", "#1e1e2e"))

    def dropEvent(self, event: QDropEvent) -> None:
        self.setStyleSheet(self.styleSheet().replace("#1a1a2e", "#1e1e2e"))
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

    # ── Staging ───────────────────────────────────────────────────────────────

    def _stage_files(self, folder: Path, file_list: list[Path]) -> None:
        """Show the staging page — user reviews files then clicks Start."""
        self._staged_folder = folder
        self._staged_files = file_list

        # Replace any existing staging page
        if self._stack.count() > 1:
            self._stack.removeWidget(self._stack.widget(1))
            if self._stack.count() > 1:
                self._stack.removeWidget(self._stack.widget(1))

        staging_page = self._build_staging_page(folder, file_list)
        self._stack.addWidget(staging_page)
        self._stack.setCurrentIndex(1)
        self.resize(max(self.width(), 320), max(self.height(), 360))

    def _cancel_staging(self) -> None:
        self._staged_folder = None
        self._staged_files = None
        self._stack.setCurrentIndex(0)
        self.resize(MIN_W, MIN_H)

    def _start_from_staging(self) -> None:
        if not self._staged_folder or not self._staged_files:
            return
        force = self._force_reprocess_check.isChecked()
        self._launch_batch(
            folder=self._staged_folder,
            file_list=self._staged_files,
            force=force,
        )

    # ── Batch lifecycle ───────────────────────────────────────────────────────

    def _launch_batch(
        self,
        folder: Path,
        file_list: list[Path],
        force: bool = False,
    ) -> None:
        """Wire up the worker and switch to the progress view."""
        # Build progress panel
        self._progress_panel = ProgressPanel(
            folder_name=folder.name,
            total=len(file_list),
            parent=self,
        )
        self._progress_panel.pause_clicked.connect(self._toggle_pause)
        self._progress_panel.stop_clicked.connect(self._stop_batch)
        self._progress_panel.close_clicked.connect(self._collapse_to_drop_zone)

        for f in file_list:
            self._progress_panel.add_file(f.name)

        # Replace stack pages 1+ with progress panel
        while self._stack.count() > 1:
            self._stack.removeWidget(self._stack.widget(1))
        self._stack.addWidget(self._progress_panel)
        self._stack.setCurrentIndex(1)
        self.resize(max(self.width(), 360), max(self.height(), 480))

        # If force, reset DB state
        if force:
            from app.core.job_db import reset_batch_for_reprocess
            reset_batch_for_reprocess(make_batch_id(folder))

        # Explicit file list passed so worker doesn't re-scan
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
            else:
                self._worker.pause()

    def _stop_batch(self) -> None:
        if self._worker:
            self._worker.stop()

    def _show_progress_panel(self) -> None:
        self._stack.setCurrentIndex(1)
        self.resize(max(self.width(), 360), max(self.height(), 480))

    def _collapse_to_drop_zone(self) -> None:
        self._stack.setCurrentIndex(0)
        running = bool(self._thread and self._thread.isRunning())
        self._batch_status_btn.setVisible(running)

    # ── Worker slots ──────────────────────────────────────────────────────────

    @pyqtSlot(str)
    def _on_job_started(self, filename: str) -> None:
        if self._progress_panel:
            self._progress_panel.set_running(filename)

    @pyqtSlot(str)
    def _on_job_done(self, filename: str) -> None:
        if self._progress_panel:
            self._progress_panel.set_done(filename)

    @pyqtSlot(str, str)
    def _on_job_error(self, filename: str, msg: str) -> None:
        if self._progress_panel:
            self._progress_panel.set_error(filename, msg)

    @pyqtSlot(str)
    def _on_job_skipped(self, filename: str) -> None:
        if self._progress_panel:
            self._progress_panel.set_skipped(filename)

    @pyqtSlot(int, int)
    def _on_progress(self, done: int, total: int) -> None:
        if self._progress_panel:
            self._progress_panel.update_progress(done, total)

    @pyqtSlot(str)
    def _on_status(self, msg: str) -> None:
        if self._progress_panel:
            self._progress_panel.set_status(msg)
        self.status_changed.emit(msg)

    @pyqtSlot(int, int, int, int)
    def _on_batch_complete(self, done: int, errors: int, skipped: int, total: int) -> None:
        if self._progress_panel:
            self._progress_panel.set_complete(done, errors, skipped, total)
        if self._thread:
            self._thread.quit()
            self._thread.wait()
        self._batch_status_btn.setVisible(False)
        self.status_changed.emit("Idle")
        self.batch_finished.emit(done, errors)

    # ── Settings & log ────────────────────────────────────────────────────────

    def _open_settings(self) -> None:
        models = list_available_models(self.settings.ollama_host)
        dlg = SettingsDialog(self.settings, models, parent=self)
        if dlg.exec():
            self.settings = load_settings()

    def _open_log(self) -> None:
        from PyQt6.QtWidgets import (
            QDialog, QTableWidget, QTableWidgetItem, QHeaderView, QDialogButtonBox,
        )
        from app.core.job_db import get_recent_batches, clear_all_jobs, clear_incomplete_jobs

        batches = get_recent_batches(limit=20)

        dlg = QDialog(self)
        dlg.setWindowTitle("Batch History")
        dlg.setMinimumSize(600, 340)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        if not batches:
            msg = QLabel("No batches recorded yet.\nDrop a folder onto the window to get started.")
            msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(msg)
        else:
            table = QTableWidget(len(batches), 5)
            table.setHorizontalHeaderLabels(["Folder", "Date", "Done", "Errors", "Skipped"])
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            for col in (2, 3, 4):
                table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
            table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            table.verticalHeader().setVisible(False)
            table.setAlternatingRowColors(True)

            for row, b in enumerate(batches):
                name = Path(b["folder_path"]).name
                date = (b["created_at"] or "")[:16]
                for col, val in enumerate([name, date, str(b["done"] or 0), str(b["errors"] or 0), str(b["skipped"] or 0)]):
                    item = QTableWidgetItem(val)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    table.setItem(row, col, item)

            layout.addWidget(table)

        btn_row = QHBoxLayout()
        clear_incomplete_btn = QPushButton("Clear Errors / Incomplete")
        clear_incomplete_btn.setStyleSheet("color: #e57373;")
        clear_all_btn = QPushButton("Clear All History")
        clear_all_btn.setStyleSheet("color: #e57373;")
        close_btn2 = QPushButton("Close")
        close_btn2.clicked.connect(dlg.accept)

        def do_clear_incomplete():
            n = clear_incomplete_jobs()
            QMessageBox.information(dlg, "Cleared", f"Removed {n} incomplete job(s).")
            dlg.accept()

        def do_clear_all():
            reply = QMessageBox.question(
                dlg, "Clear All?",
                "This removes all job history. All files will be reprocessed on next drop.\nContinue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                clear_all_jobs()
                dlg.accept()

        clear_incomplete_btn.clicked.connect(do_clear_incomplete)
        clear_all_btn.clicked.connect(do_clear_all)

        btn_row.addWidget(clear_incomplete_btn)
        btn_row.addWidget(clear_all_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn2)
        layout.addLayout(btn_row)
        dlg.exec()

    # ── Auto-resume on launch ─────────────────────────────────────────────────

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

    # ── Window dragging (frameless) ───────────────────────────────────────────

    def _title_mouse_press(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def _title_mouse_move(self, event) -> None:
        if self._drag_origin and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_origin)

    def _title_mouse_release(self, event) -> None:
        self._drag_origin = None
