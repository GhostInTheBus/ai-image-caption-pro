"""
Settings dialog — persistent IPTC defaults and AI backend configuration.
Reads/writes ~/.photoai/settings.toml via tomllib (stdlib 3.11+) / tomli fallback.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QCheckBox, QMessageBox,
    QPushButton, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from app.models import Settings
from app.core.captioner import GEMINI_MODELS, CLAUDE_MODELS, OPENAI_MODELS

SETTINGS_PATH = Path.home() / ".photoai" / "settings.toml"

BACKENDS = ["ollama", "gemini", "claude", "openai"]
BACKEND_LABELS = ["Ollama (local)", "Google Gemini", "Anthropic Claude", "OpenAI / ChatGPT"]


# ── TOML read/write ───────────────────────────────────────────────────────────

def _read_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        if sys.version_info >= (3, 11):
            import tomllib
            with open(path, "rb") as f:
                return tomllib.load(f)
        else:
            import tomli
            with open(path, "rb") as f:
                return tomli.load(f)
    except Exception:
        return {}


def _write_toml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for key, val in data.items():
        if isinstance(val, str):
            escaped = val.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{key} = "{escaped}"')
        elif isinstance(val, bool):
            lines.append(f'{key} = {"true" if val else "false"}')
        elif isinstance(val, int):
            lines.append(f'{key} = {val}')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── Settings persistence ──────────────────────────────────────────────────────

def load_settings() -> Settings:
    data = _read_toml(SETTINGS_PATH)
    s = Settings()
    for field_name in Settings.__dataclass_fields__:
        if field_name in data:
            setattr(s, field_name, data[field_name])
    return s


def save_settings(s: Settings) -> None:
    data = {}
    for field_name in Settings.__dataclass_fields__:
        data[field_name] = getattr(s, field_name)
    _write_toml(SETTINGS_PATH, data)


# ── Dialog ────────────────────────────────────────────────────────────────────

class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, available_models: List[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Photo Caption Pro — Settings")
        self.setMinimumWidth(480)
        self.settings = settings

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ── Identity ──────────────────────────────────────────────────────────
        identity_group = QGroupBox("Photographer Identity (written to every file)")
        form = QFormLayout(identity_group)

        self.artist_edit = QLineEdit(settings.artist_name)
        self.artist_edit.setPlaceholderText("e.g. Alex Rivera")
        form.addRow("Artist Name:", self.artist_edit)

        self.copyright_edit = QLineEdit(settings.copyright_notice)
        self.copyright_edit.setPlaceholderText("e.g. © %Y Alex Rivera  (use %Y for current year)")
        form.addRow("Copyright:", self.copyright_edit)

        self.credit_edit = QLineEdit(settings.credit_line)
        self.credit_edit.setPlaceholderText("e.g. Alex Rivera Photography")
        form.addRow("Credit Line:", self.credit_edit)

        layout.addWidget(identity_group)

        # ── Location defaults ─────────────────────────────────────────────────
        loc_group = QGroupBox("Location Defaults (only written if not already set)")
        loc_form = QFormLayout(loc_group)

        self.city_edit = QLineEdit(settings.default_city)
        self.city_edit.setPlaceholderText("e.g. Rochester  (leave blank to skip)")
        loc_form.addRow("City:", self.city_edit)

        self.country_edit = QLineEdit(settings.default_country)
        self.country_edit.setPlaceholderText("e.g. United States")
        loc_form.addRow("Country:", self.country_edit)

        layout.addWidget(loc_group)

        # ── AI Backend ────────────────────────────────────────────────────────
        ai_group = QGroupBox("AI Backend")
        ai_layout = QVBoxLayout(ai_group)

        # Backend selector row
        backend_row = QHBoxLayout()
        backend_row.addWidget(QLabel("Backend:"))
        self.backend_combo = QComboBox()
        self.backend_combo.addItems(BACKEND_LABELS)
        current_idx = BACKENDS.index(settings.backend) if settings.backend in BACKENDS else 0
        self.backend_combo.setCurrentIndex(current_idx)
        backend_row.addWidget(self.backend_combo, 1)
        ai_layout.addLayout(backend_row)

        # Stacked panels — one per backend
        self._backend_stack = QStackedWidget()
        self._backend_stack.addWidget(self._build_ollama_panel(settings, available_models))
        self._backend_stack.addWidget(self._build_api_panel("gemini", settings))
        self._backend_stack.addWidget(self._build_api_panel("claude", settings))
        self._backend_stack.addWidget(self._build_api_panel("openai", settings))
        self._backend_stack.setCurrentIndex(current_idx)
        ai_layout.addWidget(self._backend_stack)

        self.backend_combo.currentIndexChanged.connect(self._backend_stack.setCurrentIndex)

        # Keywords (shared across all backends)
        kw_row = QFormLayout()
        self.max_kw_spin = QSpinBox()
        self.max_kw_spin.setRange(1, 9999)
        self.max_kw_spin.setValue(settings.max_keywords)
        self.max_kw_spin.setSuffix(" keywords max")
        kw_row.addRow("Keywords:", self.max_kw_spin)
        ai_layout.addLayout(kw_row)

        layout.addWidget(ai_group)

        # ── Context hint ──────────────────────────────────────────────────────
        ctx_group = QGroupBox("Context Hint (optional — added to every caption prompt)")
        ctx_form = QFormLayout(ctx_group)
        self.context_edit = QLineEdit(settings.context_hint)
        self.context_edit.setPlaceholderText(
            "e.g. Shot in Kyoto, Japan. Spring cherry blossom season, 2024."
        )
        ctx_form.addRow("Context:", self.context_edit)
        layout.addWidget(ctx_group)

        # ── Behaviour ─────────────────────────────────────────────────────────
        behaviour_group = QGroupBox("Behaviour")
        b_form = QFormLayout(behaviour_group)

        caption_row = QHBoxLayout()
        self.caption_mode_combo = QComboBox()
        self.caption_mode_combo.addItem("Amend — append to existing caption", "amend")
        self.caption_mode_combo.addItem("Replace — overwrite existing caption", "replace")
        mode_idx = 0 if getattr(settings, "caption_mode", "amend") == "amend" else 1
        self.caption_mode_combo.setCurrentIndex(mode_idx)
        caption_row.addWidget(self.caption_mode_combo)
        b_form.addRow("Caption mode:", caption_row)

        self.recursive_check = QCheckBox("Scan subfolders recursively")
        self.recursive_check.setChecked(settings.recursive_scan)
        b_form.addRow(self.recursive_check)

        self.skip_done_check = QCheckBox("Skip files already processed in previous runs")
        self.skip_done_check.setChecked(settings.skip_already_done)
        b_form.addRow(self.skip_done_check)

        layout.addWidget(behaviour_group)

        # ── Buttons ───────────────────────────────────────────────────────────
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ── Backend panel builders ────────────────────────────────────────────────

    def _build_ollama_panel(self, settings: Settings, available_models: List[str]) -> QWidget:
        panel = QWidget()
        form = QFormLayout(panel)
        form.setContentsMargins(0, 4, 0, 0)

        self.host_edit = QLineEdit(settings.ollama_host)
        form.addRow("Host:", self.host_edit)

        model_row = QWidget()
        model_row_layout = QHBoxLayout(model_row)
        model_row_layout.setContentsMargins(0, 0, 0, 0)

        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        if available_models:
            self.model_combo.addItems(available_models)
        idx = self.model_combo.findText(settings.ollama_model)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        else:
            self.model_combo.setCurrentText(settings.ollama_model)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setFixedWidth(70)
        refresh_btn.setToolTip("Query Ollama for available models")
        refresh_btn.clicked.connect(self._refresh_models)

        model_row_layout.addWidget(self.model_combo, 1)
        model_row_layout.addWidget(refresh_btn)
        form.addRow("Model:", model_row)

        return panel

    def _build_api_panel(self, backend: str, settings: Settings) -> QWidget:
        """Build the key + model panel for Gemini, Claude, or OpenAI."""
        panel = QWidget()
        form = QFormLayout(panel)
        form.setContentsMargins(0, 4, 0, 0)

        if backend == "gemini":
            key_val = settings.gemini_api_key
            model_val = settings.gemini_model
            models = GEMINI_MODELS
            hint = "Get a free key at aistudio.google.com"
        elif backend == "claude":
            key_val = settings.claude_api_key
            model_val = settings.claude_model
            models = CLAUDE_MODELS
            hint = "Get a key at console.anthropic.com"
        else:  # openai
            key_val = settings.openai_api_key
            model_val = settings.openai_model
            models = OPENAI_MODELS
            hint = "Get a key at platform.openai.com"

        key_edit = QLineEdit(key_val)
        key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        key_edit.setPlaceholderText(hint)
        form.addRow("API Key:", key_edit)

        model_combo = QComboBox()
        model_combo.addItems(models)
        idx = model_combo.findText(model_val)
        if idx >= 0:
            model_combo.setCurrentIndex(idx)
        else:
            model_combo.setCurrentText(model_val)
        form.addRow("Model:", model_combo)

        # Store refs for _save()
        setattr(self, f"_{backend}_key_edit", key_edit)
        setattr(self, f"_{backend}_model_combo", model_combo)

        return panel

    # ── Refresh Ollama models ─────────────────────────────────────────────────

    def _refresh_models(self) -> None:
        from app.core.captioner import list_available_models
        host = self.host_edit.text().strip()
        models = list_available_models(host)
        if not models:
            QMessageBox.warning(self, "Ollama", f"No models found at {host}.\nIs Ollama running?")
            return
        current = self.model_combo.currentText()
        self.model_combo.clear()
        self.model_combo.addItems(models)
        idx = self.model_combo.findText(current)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        else:
            self.model_combo.setCurrentText(current)

    # ── Save ──────────────────────────────────────────────────────────────────

    def _save(self) -> None:
        self.settings.artist_name      = self.artist_edit.text().strip()
        self.settings.copyright_notice = self.copyright_edit.text().strip()
        self.settings.credit_line      = self.credit_edit.text().strip()
        self.settings.default_city     = self.city_edit.text().strip()
        self.settings.default_country  = self.country_edit.text().strip()
        self.settings.context_hint     = self.context_edit.text().strip()
        self.settings.max_keywords     = self.max_kw_spin.value()
        self.settings.caption_mode      = self.caption_mode_combo.currentData()
        self.settings.recursive_scan   = self.recursive_check.isChecked()
        self.settings.skip_already_done = self.skip_done_check.isChecked()

        idx = self.backend_combo.currentIndex()
        self.settings.backend = BACKENDS[idx]

        # Ollama
        self.settings.ollama_host  = self.host_edit.text().strip()
        self.settings.ollama_model = self.model_combo.currentText().strip()

        # Cloud backends
        self.settings.gemini_api_key  = self._gemini_key_edit.text().strip()
        self.settings.gemini_model    = self._gemini_model_combo.currentText().strip()
        self.settings.claude_api_key  = self._claude_key_edit.text().strip()
        self.settings.claude_model    = self._claude_model_combo.currentText().strip()
        self.settings.openai_api_key  = self._openai_key_edit.text().strip()
        self.settings.openai_model    = self._openai_model_combo.currentText().strip()

        save_settings(self.settings)
        self.accept()
