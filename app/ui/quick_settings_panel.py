"""
QuickSettingsPanel — right column of the main window.

Per-shoot AI controls that used to require opening the Settings dialog.
Changes write to disk immediately via save_settings().
Deep identity/location/publication/contact fields remain in SettingsDialog.
"""
from __future__ import annotations

import copy
from typing import List

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFrame,
    QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QScrollArea, QSizePolicy,
    QSlider, QToolButton, QVBoxLayout, QWidget,
)

from app.core.captioner import (
    CLAUDE_MODELS, GEMINI_MODELS, OPENAI_MODELS, list_available_models,
)
from app.models import Settings
from app.ui.settings_dialog import save_settings

BACKENDS = ["ollama", "gemini", "claude", "openai"]
BACKEND_LABELS = ["Ollama (local)", "Google Gemini", "Anthropic Claude", "OpenAI / ChatGPT"]

_KW_LABELS = {
    1: "Minimal (2–4)",
    2: "Concise (4–6)",
    3: "Standard (5–8)",
    4: "Rich (8–12)",
    5: "Exhaustive (12–20)",
}
_DESC_LABELS = {
    1: "Brief (1 sentence)",
    2: "Concise (1–2)",
    3: "Standard (2–4)",
    4: "Detailed (4–6)",
    5: "Exhaustive (6–8)",
}


class QuickSettingsPanel(QWidget):
    """Right column: live-saving per-shoot settings."""

    settings_changed = pyqtSignal(object)  # emits Settings

    def __init__(self, settings: Settings, available_models: List[str], parent=None):
        super().__init__(parent)
        self._base_settings = copy.copy(settings)
        self._ollama_models = available_models
        self._updating = False
        self._build_ui(settings)

    # ── Build ─────────────────────────────────────────────────────────

    @staticmethod
    def _lbl(text: str) -> QLabel:
        """Small grey section label."""
        l = QLabel(text)
        l.setStyleSheet("color: #888; font-size: 11px;")
        return l

    def _build_ui(self, s: Settings) -> None:
        # Outer scroll area so the panel works on small screens
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        # Prevent the content widget from expanding wider than the scroll area
        content.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        scroll.setWidget(content)

        # ── Header ────────────────────────────────────────────────────
        hdr = QLabel("Quick Settings")
        hdr.setStyleSheet(
            "color: #888; font-size: 11px; font-weight: bold; letter-spacing: 1px;"
        )
        layout.addWidget(hdr)

        # ── Backend ───────────────────────────────────────────────────
        layout.addWidget(self._lbl("Backend"))
        self._backend_combo = QComboBox()
        self._backend_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._backend_combo.addItems(BACKEND_LABELS)
        current_idx = BACKENDS.index(s.backend) if s.backend in BACKENDS else 0
        self._backend_combo.setCurrentIndex(current_idx)
        layout.addWidget(self._backend_combo)

        # ── Model ─────────────────────────────────────────────────────
        layout.addWidget(self._lbl("Model"))
        model_row = QWidget()
        model_row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        model_layout = QHBoxLayout(model_row)
        model_layout.setContentsMargins(0, 0, 0, 0)
        model_layout.setSpacing(4)

        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        # Critical: allow the combo to shrink to any width; text is still readable
        self._model_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._model_combo.setMinimumContentsLength(1)
        self._model_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._refresh_model_list(s.backend, current_model=self._model_for(s))

        self._refresh_btn = QToolButton()
        self._refresh_btn.setText("⟳")
        self._refresh_btn.setFixedWidth(26)
        self._refresh_btn.setToolTip("Refresh Ollama model list")
        self._refresh_btn.clicked.connect(self._on_refresh_models)
        self._refresh_btn.setVisible(s.backend == "ollama")

        model_layout.addWidget(self._model_combo, 1)
        model_layout.addWidget(self._refresh_btn)
        layout.addWidget(model_row)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep1)

        # ── Verbosity sliders ─────────────────────────────────────────
        # Keyword verbosity: label row + slider row
        layout.addWidget(self._lbl("Keywords"))
        self._kw_lbl = QLabel(_KW_LABELS[getattr(s, "keyword_verbosity", 3)])
        self._kw_lbl.setStyleSheet("color: #cdd6f4; font-size: 11px;")
        self._kw_slider = QSlider(Qt.Orientation.Horizontal)
        self._kw_slider.setRange(1, 5)
        self._kw_slider.setValue(getattr(s, "keyword_verbosity", 3))
        self._kw_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._kw_slider.setTickInterval(1)
        self._kw_slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._kw_slider.valueChanged.connect(
            lambda v: self._kw_lbl.setText(_KW_LABELS[v])
        )
        layout.addWidget(self._kw_lbl)
        layout.addWidget(self._kw_slider)

        # Description verbosity
        layout.addWidget(self._lbl("Description"))
        self._desc_lbl = QLabel(_DESC_LABELS[getattr(s, "description_verbosity", 3)])
        self._desc_lbl.setStyleSheet("color: #cdd6f4; font-size: 11px;")
        self._desc_slider = QSlider(Qt.Orientation.Horizontal)
        self._desc_slider.setRange(1, 5)
        self._desc_slider.setValue(getattr(s, "description_verbosity", 3))
        self._desc_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._desc_slider.setTickInterval(1)
        self._desc_slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._desc_slider.valueChanged.connect(
            lambda v: self._desc_lbl.setText(_DESC_LABELS[v])
        )
        layout.addWidget(self._desc_lbl)
        layout.addWidget(self._desc_slider)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep2)

        # ── Context hint ──────────────────────────────────────────────
        layout.addWidget(self._lbl("Context hint"))
        self._context_edit = QPlainTextEdit()
        self._context_edit.setPlainText(s.context_hint)
        self._context_edit.setPlaceholderText(
            "e.g. Wedding at Waimea Valley, Oahu.\nLate afternoon golden hour."
        )
        self._context_edit.setMaximumHeight(76)
        self._context_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(self._context_edit)

        # ── Seed keywords ─────────────────────────────────────────────
        layout.addWidget(self._lbl("Keyword seeds"))
        self._seeds_edit = QLineEdit(getattr(s, "user_keywords", ""))
        self._seeds_edit.setPlaceholderText("diamond head, golden hour, surf photography")
        self._seeds_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(self._seeds_edit)

        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.HLine)
        sep3.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep3)

        # ── Behaviour checkboxes ──────────────────────────────────────
        self._recursive_check = QCheckBox("Scan subfolders recursively")
        self._recursive_check.setChecked(s.recursive_scan)
        layout.addWidget(self._recursive_check)

        self._skip_done_check = QCheckBox("Skip already-processed files")
        self._skip_done_check.setChecked(s.skip_already_done)
        layout.addWidget(self._skip_done_check)

        # Push everything to top
        layout.addStretch(1)

        # ── Wire change signals ───────────────────────────────────────
        self._backend_combo.currentIndexChanged.connect(self._on_backend_changed)
        self._model_combo.currentTextChanged.connect(self._on_any_change)
        self._kw_slider.valueChanged.connect(self._on_any_change)
        self._desc_slider.valueChanged.connect(self._on_any_change)
        self._context_edit.textChanged.connect(self._on_any_change)
        self._seeds_edit.textChanged.connect(self._on_any_change)
        self._recursive_check.stateChanged.connect(self._on_any_change)
        self._skip_done_check.stateChanged.connect(self._on_any_change)

    # ── Slots ─────────────────────────────────────────────────────────

    def _on_backend_changed(self, idx: int) -> None:
        backend = BACKENDS[idx]
        current = self._model_combo.currentText()
        self._refresh_model_list(backend, current_model=current)
        self._refresh_btn.setVisible(backend == "ollama")
        self._on_any_change()

    def _on_refresh_models(self) -> None:
        host = self._base_settings.ollama_host
        models = list_available_models(host)
        if models:
            current = self._model_combo.currentText()
            self._ollama_models = models
            self._updating = True
            self._model_combo.clear()
            self._model_combo.addItems(models)
            idx = self._model_combo.findText(current)
            if idx >= 0:
                self._model_combo.setCurrentIndex(idx)
            else:
                self._model_combo.setCurrentText(current)
            self._updating = False

    def _on_any_change(self, *_) -> None:
        if self._updating:
            return
        s = self._current_settings()
        save_settings(s)
        self.settings_changed.emit(s)

    # ── Public interface ──────────────────────────────────────────────

    def refresh_from_settings(self, settings: Settings) -> None:
        """Sync all controls from a freshly loaded Settings (e.g. after SettingsDialog closes)."""
        self._updating = True
        self._base_settings = copy.copy(settings)

        backend_idx = BACKENDS.index(settings.backend) if settings.backend in BACKENDS else 0
        self._backend_combo.setCurrentIndex(backend_idx)
        self._refresh_model_list(settings.backend, current_model=self._model_for(settings))
        self._kw_slider.setValue(getattr(settings, "keyword_verbosity", 3))
        self._desc_slider.setValue(getattr(settings, "description_verbosity", 3))
        self._context_edit.setPlainText(settings.context_hint)
        self._seeds_edit.setText(getattr(settings, "user_keywords", ""))
        self._recursive_check.setChecked(settings.recursive_scan)
        self._skip_done_check.setChecked(settings.skip_already_done)
        self._updating = False

    # ── Helpers ───────────────────────────────────────────────────────

    def _model_for(self, s: Settings) -> str:
        backend = s.backend
        if backend == "gemini":   return s.gemini_model
        if backend == "claude":   return s.claude_model
        if backend == "openai":   return s.openai_model
        return s.ollama_model

    def _refresh_model_list(self, backend: str, current_model: str = "") -> None:
        self._updating = True
        self._model_combo.clear()
        if backend == "ollama":
            models = self._ollama_models or [current_model]
        elif backend == "gemini":
            models = GEMINI_MODELS
        elif backend == "claude":
            models = CLAUDE_MODELS
        else:
            models = OPENAI_MODELS
        self._model_combo.addItems(models)
        idx = self._model_combo.findText(current_model)
        if idx >= 0:
            self._model_combo.setCurrentIndex(idx)
        elif current_model:
            self._model_combo.setCurrentText(current_model)
        self._updating = False

    def _current_settings(self) -> Settings:
        """Build a Settings by overlaying quick-panel fields onto _base_settings."""
        s = copy.copy(self._base_settings)
        backend_idx = self._backend_combo.currentIndex()
        s.backend = BACKENDS[backend_idx]
        model_text = self._model_combo.currentText().strip()
        if s.backend == "ollama":   s.ollama_model  = model_text
        elif s.backend == "gemini": s.gemini_model  = model_text
        elif s.backend == "claude": s.claude_model  = model_text
        else:                       s.openai_model  = model_text
        s.keyword_verbosity     = self._kw_slider.value()
        s.description_verbosity = self._desc_slider.value()
        s.context_hint          = self._context_edit.toPlainText().strip()
        s.user_keywords         = self._seeds_edit.text().strip()
        s.recursive_scan        = self._recursive_check.isChecked()
        s.skip_already_done     = self._skip_done_check.isChecked()
        return s
