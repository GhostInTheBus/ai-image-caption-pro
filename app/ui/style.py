"""
Centralised stylesheet for AI Image Caption Pro.

All UI files import APP_STYLE — no palette colours are defined anywhere else.
Palette: Catppuccin Mocha (https://github.com/catppuccin/catppuccin)
"""

APP_STYLE: str = """
    /* ── Base ───────────────────────────────────────────────────────── */
    QMainWindow, QWidget {
        background-color: #1e1e2e;
        color: #cdd6f4;
        font-family: -apple-system, 'Segoe UI', sans-serif;
        font-size: 13px;
    }
    QDialog {
        background: #1e1e2e;
        color: #cdd6f4;
    }
    QLabel  { color: #cdd6f4; }
    QCheckBox { color: #cdd6f4; }

    /* ── Toolbar ─────────────────────────────────────────────────────── */
    QToolBar {
        background: #181825;
        border-bottom: 1px solid #313244;
        spacing: 4px;
        padding: 3px 8px;
    }
    QToolBar::separator {
        background: #313244;
        width: 1px;
        margin: 4px 4px;
    }

    /* ── Tool buttons (toolbar icons) ───────────────────────────────── */
    QToolButton {
        background: transparent;
        border: none;
        color: #cdd6f4;
        padding: 2px 7px;
        border-radius: 3px;
        font-size: 13px;
    }
    QToolButton:hover  { background: #313244; }
    QToolButton:pressed { background: #45475a; }

    /* ── Push buttons ───────────────────────────────────────────────── */
    QPushButton {
        background: #313244;
        color: #cdd6f4;
        border: 1px solid #45475a;
        border-radius: 4px;
        padding: 4px 10px;
    }
    QPushButton:hover   { background: #45475a; }
    QPushButton:pressed { background: #585b70; }
    QPushButton:disabled { color: #585b70; border-color: #313244; }

    /* ── Progress bar ───────────────────────────────────────────────── */
    QProgressBar {
        border: 1px solid #45475a;
        border-radius: 3px;
        background: #313244;
        text-align: center;
        color: #cdd6f4;
    }
    QProgressBar::chunk { background: #89b4fa; border-radius: 3px; }

    /* ── Status bar ─────────────────────────────────────────────────── */
    QStatusBar {
        background: #181825;
        border-top: 1px solid #313244;
        color: #cdd6f4;
    }
    QStatusBar QLabel {
        color: #888;
        font-size: 12px;
        padding: 0 4px;
    }

    /* ── Splitter ───────────────────────────────────────────────────── */
    QSplitter::handle {
        background: #313244;
    }
    QSplitter::handle:horizontal {
        width: 3px;
    }
    QSplitter::handle:vertical {
        height: 3px;
    }
    QSplitter::handle:hover {
        background: #45475a;
    }

    /* ── Scroll areas / scroll bars ─────────────────────────────────── */
    QScrollArea { border: none; background: transparent; }
    QScrollBar:vertical {
        background: #1e1e2e;
        width: 8px;
        border-radius: 4px;
    }
    QScrollBar::handle:vertical {
        background: #45475a;
        border-radius: 4px;
        min-height: 20px;
    }
    QScrollBar::handle:vertical:hover { background: #585b70; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    QScrollBar:horizontal {
        background: #1e1e2e;
        height: 8px;
        border-radius: 4px;
    }
    QScrollBar::handle:horizontal {
        background: #45475a;
        border-radius: 4px;
        min-width: 20px;
    }
    QScrollBar::handle:horizontal:hover { background: #585b70; }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

    /* ── Form inputs ────────────────────────────────────────────────── */
    QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {
        background: #313244;
        border: 1px solid #45475a;
        border-radius: 3px;
        padding: 3px 6px;
        color: #cdd6f4;
    }
    QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {
        border-color: #89b4fa;
    }
    QComboBox::drop-down {
        border: none;
        width: 20px;
    }
    QComboBox QAbstractItemView {
        background: #313244;
        border: 1px solid #45475a;
        selection-background-color: #45475a;
        color: #cdd6f4;
    }

    /* ── Sliders ────────────────────────────────────────────────────── */
    QSlider::groove:horizontal {
        height: 4px;
        background: #45475a;
        border-radius: 2px;
    }
    QSlider::handle:horizontal {
        background: #89b4fa;
        border: none;
        width: 14px;
        height: 14px;
        margin: -5px 0;
        border-radius: 7px;
    }
    QSlider::sub-page:horizontal { background: #89b4fa; border-radius: 2px; }

    /* ── Group boxes ────────────────────────────────────────────────── */
    QGroupBox {
        border: 1px solid #45475a;
        border-radius: 4px;
        margin-top: 8px;
        color: #cdd6f4;
    }
    QGroupBox::title { subcontrol-origin: margin; left: 8px; }

    /* ── List / table widgets ───────────────────────────────────────── */
    QListWidget, QTableWidget {
        background: #181825;
        border: 1px solid #313244;
        border-radius: 3px;
        color: #cdd6f4;
        font-size: 12px;
    }
    QListWidget::item { padding: 2px 4px; }
    QListWidget::item:selected,
    QTableWidget::item:selected { background: #313244; }
    QHeaderView::section {
        background: #181825;
        border: none;
        border-bottom: 1px solid #313244;
        border-right: 1px solid #313244;
        color: #888;
        padding: 3px 6px;
        font-size: 12px;
    }

    /* ── Frames ─────────────────────────────────────────────────────── */
    QFrame[frameShape="4"],
    QFrame[frameShape="5"] {
        color: #313244;
    }
"""
