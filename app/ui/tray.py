"""
macOS menu bar / system tray icon for AI Image Caption Pro.

Provides a persistent entry point in the menu bar so the app is never "lost".
Clicking the icon shows/hides the floating window.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon


class TrayIcon(QObject):
    def __init__(self, window, icon_path: Path, parent=None):
        super().__init__(parent)
        self._window = window

        icon = QIcon(str(icon_path)) if icon_path.exists() else QIcon()
        self._tray = QSystemTrayIcon(icon, parent=self)
        self._tray.setToolTip("AI Image Caption Pro")

        menu = QMenu()

        self._toggle_action = QAction("Hide AI Image Caption Pro")
        self._toggle_action.triggered.connect(self._toggle)
        menu.addAction(self._toggle_action)

        menu.addSeparator()

        quit_action = QAction("Quit AI Image Caption Pro")
        quit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(quit_action)

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_activated)
        self._tray.show()

    # ── Public API ────────────────────────────────────────────────────────────

    def set_status(self, text: str) -> None:
        self._tray.setToolTip(f"AI Image Caption Pro — {text}")

    def notify(self, title: str, message: str) -> None:
        self._tray.showMessage(
            title, message,
            QSystemTrayIcon.MessageIcon.Information,
            5000,
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _on_activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._toggle()

    def _toggle(self) -> None:
        if self._window.isVisible():
            self._window.hide()
            self._toggle_action.setText("Show AI Image Caption Pro")
        else:
            self._window.show()
            self._window.raise_()
            self._window.activateWindow()
            self._toggle_action.setText("Hide AI Image Caption Pro")
