"""
Floating drop zone — the main app window.

Behavior:
  • Small always-on-top window in "drop zone" state
  • Accepts folder drag-and-drop
  • Expands to progress panel while a batch is running
  • Collapses back to drop zone when complete
  • Frameless: draggable by clicking anywhere on the title bar area
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import (
    QEvent, QPoint, QSize, Qt, QThread, pyqtSignal, pyqtSlot,
)
from PyQt6.QtGui import QColor, QDragEnterEvent, QDropEvent, QPalette
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from app.core.agent import BatchWorker, make_batch_id, scan_folder
from app.core.captioner import list_available_models
from app.models import Settings
from app.ui.progress_panel import ProgressPanel
from app.ui.settings_dialog import SettingsDialog, load_settings, save_settings

DROP_ZONE_SIZE = QSize(220, 200)


class FloatingWindow(QWidget):
    """Main application window."""

    # Emitted so the tray icon can update its tooltip / send notifications
    status_changed  = pyqtSignal(str)          # e.g. "Processing 12 files…"
    batch_finished  = pyqtSignal(int, int)     # done, errors

    def __init__(self):
        super().__init__()
        self.settings: Settings = load_settings()
        self._drag_origin: Optional[QPoint] = None
        self._worker: Optional[BatchWorker] = None
        self._thread: Optional[QThread] = None

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
        self.setFixedSize(DROP_ZONE_SIZE)

        # Dark-ish palette
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

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(22, 22)
        close_btn.setStyleSheet(
            "background: transparent; border: none; color: #888; font-size: 14px;"
            "padding: 0;"
        )
        close_btn.setToolTip("Hide to menu bar")
        close_btn.clicked.connect(self.hide)
        tbl.addWidget(close_btn)

        root.addWidget(title_bar)

        # Stacked pages: [0] drop zone, [1] progress panel
        self._stack = QStackedWidget()
        root.addWidget(self._stack, 1)

        # Page 0: drop zone
        self._drop_page = self._build_drop_page()
        self._stack.addWidget(self._drop_page)

        # Page 1: progress — created fresh per batch
        self._progress_panel: Optional[ProgressPanel] = None

    def _build_drop_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_lbl = QLabel("📂")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet("font-size: 48px;")
        layout.addWidget(icon_lbl)

        hint = QLabel("Drop a photo folder here")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("color: #888; font-size: 14px;")
        layout.addWidget(hint)

        hint2 = QLabel("RAW + JPG supported")
        hint2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint2.setStyleSheet("color: #555; font-size: 12px;")
        layout.addWidget(hint2)

        # Bottom toolbar
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

    # ── Re-raise when app comes back into focus ───────────────────────────────

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
            urls = event.mimeData().urls()
            if urls and Path(urls[0].toLocalFile()).is_dir():
                event.acceptProposedAction()
                self.setStyleSheet(self.styleSheet().replace("#1e1e2e", "#1a1a2e"))
                return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:
        # Restore normal background
        self.setStyleSheet(self.styleSheet().replace("#1a1a2e", "#1e1e2e"))

    def dropEvent(self, event: QDropEvent) -> None:
        self.setStyleSheet(self.styleSheet().replace("#1a1a2e", "#1e1e2e"))
        urls = event.mimeData().urls()
        if not urls:
            return
        folder = Path(urls[0].toLocalFile())
        if not folder.is_dir():
            return
        self._start_batch(folder)

    # ── Batch lifecycle ───────────────────────────────────────────────────────

    def _start_batch(self, folder: Path, force: bool = False) -> None:
        if self._thread and self._thread.isRunning():
            QMessageBox.information(self, "Busy", "A batch is already running. Stop it first.")
            return

        # Quick scan to get file count for progress panel header
        files = scan_folder(folder, self.settings.recursive_scan)
        if not files:
            QMessageBox.warning(self, "No Images", f"No image files found in:\n{folder}")
            return

        # If every file is already done and skip_already_done is on, offer reprocess
        if self.settings.skip_already_done and not force:
            from app.core.job_db import init_db, is_done
            from app.models import ImageJob
            init_db()
            batch_id = make_batch_id(folder)
            all_done = all(
                is_done(ImageJob(file_path=f, batch_id=batch_id).job_id)
                for f in files
            )
            if all_done:
                reply = QMessageBox.question(
                    self, "Already Processed",
                    f"All {len(files)} files in '{folder.name}' were already captioned.\n\n"
                    "Reprocess them anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    self._start_batch(folder, force=True)
                return

        # Build progress panel
        self._progress_panel = ProgressPanel(
            folder_name=folder.name,
            total=len(files),
            parent=self,
        )
        self._progress_panel.pause_clicked.connect(self._toggle_pause)
        self._progress_panel.stop_clicked.connect(self._stop_batch)
        self._progress_panel.close_clicked.connect(self._collapse_to_drop_zone)

        # Pre-populate file rows
        for f in files:
            self._progress_panel.add_file(f.name)

        # Swap to progress page
        if self._stack.count() > 1:
            self._stack.removeWidget(self._stack.widget(1))
        self._stack.addWidget(self._progress_panel)
        self._stack.setCurrentIndex(1)
        self.setFixedSize(360, 480)

        # If forced reprocess, reset DB state for this batch
        if force:
            from app.core.job_db import reset_batch_for_reprocess
            reset_batch_for_reprocess(make_batch_id(folder))

        # Worker thread
        self._worker = BatchWorker(folder=folder, settings=self.settings)
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

    def _collapse_to_drop_zone(self) -> None:
        self._stack.setCurrentIndex(0)
        self.setFixedSize(DROP_ZONE_SIZE)

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
        from app.core.job_db import get_recent_batches

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
                table.horizontalHeader().setSectionResizeMode(
                    col, QHeaderView.ResizeMode.ResizeToContents
                )
            table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            table.verticalHeader().setVisible(False)
            table.setAlternatingRowColors(True)

            for row, b in enumerate(batches):
                name = Path(b["folder_path"]).name
                date = (b["created_at"] or "")[:16]
                done = str(b["done"] or 0)
                err  = str(b["errors"] or 0)
                skip = str(b["skipped"] or 0)
                for col, val in enumerate([name, date, done, err, skip]):
                    item = QTableWidgetItem(val)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    table.setItem(row, col, item)

            layout.addWidget(table)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)

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
            f"{len(incomplete)} unfinished batch(es) detected from a previous run.\n"
            "Resume processing?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            for batch_id in incomplete:
                folder = job_db.get_batch_folder(batch_id)
                if folder and folder.exists():
                    self._start_batch(folder)
                    break   # one at a time

    # ── Window dragging (frameless) ───────────────────────────────────────────

    def _title_mouse_press(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def _title_mouse_move(self, event) -> None:
        if self._drag_origin and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_origin)

    def _title_mouse_release(self, event) -> None:
        self._drag_origin = None
