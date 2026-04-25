"""
AI Image Caption Pro — entry point.

Usage:
    python main.py
    # or after PyInstaller packaging:
    open "dist/AI Image Caption Pro.app"
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from PyQt6.QtCore import QEvent, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from app.ui.floating_window import FloatingWindow
from app.ui.tray import TrayIcon


class PhotoApp(QApplication):
    """
    Custom QApplication that intercepts macOS file-open events so dragging
    a folder onto the dock icon (or opening via Finder) starts a batch.
    """
    folder_opened = pyqtSignal(Path)

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.FileOpen:
            path = Path(event.file())
            if path.is_dir():
                self.folder_opened.emit(path)
            return True
        return super().event(event)


def main() -> None:
    app = PhotoApp(sys.argv)
    app.setApplicationName("AI Image Caption Pro")
    app.setApplicationDisplayName("AI Image Caption Pro")
    app.setOrganizationName("AI Image Caption Pro")
    app.setQuitOnLastWindowClosed(False)   # keep alive when window hidden via tray

    icon_path = Path(__file__).parent / "assets" / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = FloatingWindow()
    window.show()

    # Menu bar / tray icon — primary access point so window is never "lost"
    tray = TrayIcon(window, icon_path)

    # Wire tray status updates from the window
    window.status_changed.connect(tray.set_status)
    window.batch_finished.connect(
        lambda done, errors: tray.notify(
            "AI Image Caption Pro",
            f"{done} file{'s' if done != 1 else ''} captioned"
            + (f", {errors} errors" if errors else ""),
        )
    )

    # Dock / Finder drops
    app.folder_opened.connect(window._start_batch)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
