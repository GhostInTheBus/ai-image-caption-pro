"""
Settings dialog — persistent IPTC defaults (identity, location, publication, contact).

Per-shoot AI settings (backend, model, verbosity, context, seeds) live in
QuickSettingsPanel and are not shown here.

Reads/writes ~/.photoai/settings.toml via tomllib (stdlib 3.11+) / tomli fallback.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit,
    QScrollArea, QToolButton, QVBoxLayout, QWidget,
)

from app.models import Settings

SETTINGS_PATH = Path.home() / ".photoai" / "settings.toml"


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
            escaped = val.replace("\\", "\\\\").replace('"', '\\"').replace('\n', '\\n').replace('\r', '')
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
    """
    Deep settings only: photographer identity, location defaults,
    publication info, and contact fields.

    AI backend, verbosity, and context settings are controlled
    via QuickSettingsPanel in the main window's right column.
    """

    @staticmethod
    def _key_row(edit: QLineEdit) -> QWidget:
        """Wrap a password QLineEdit with a show/hide toggle button."""
        container = QWidget()
        h = QHBoxLayout(container)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        h.addWidget(edit, 1)
        btn = QToolButton()
        btn.setText("👁")
        btn.setFixedWidth(28)
        btn.setCheckable(True)
        btn.setToolTip("Show / hide key")
        def _toggle(checked, e=edit):
            e.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            )
        btn.toggled.connect(_toggle)
        h.addWidget(btn)
        return container

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(500)
        self.resize(540, 680)
        self.settings = settings

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(12)
        layout.setContentsMargins(12, 12, 12, 4)

        # ── API Keys ──────────────────────────────────────────────────
        api_group = QGroupBox("API Keys & Backends")
        api_form = QFormLayout(api_group)
        api_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        api_note = QLabel(
            "Keys are stored in plain text in ~/.photoai/settings.toml — "
            "do not use this app on a shared machine without restricting file permissions."
        )
        api_note.setWordWrap(True)
        api_note.setStyleSheet("color: #888; font-size: 11px;")
        api_form.addRow(api_note)

        self.ollama_host_edit = QLineEdit(settings.ollama_host)
        self.ollama_host_edit.setPlaceholderText("http://localhost:11434")
        api_form.addRow("Ollama host:", self.ollama_host_edit)

        self.gemini_key_edit = QLineEdit(settings.gemini_api_key)
        self.gemini_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.gemini_key_edit.setPlaceholderText("AIza…  (aistudio.google.com)")
        api_form.addRow("Gemini API key:", self._key_row(self.gemini_key_edit))

        self.claude_key_edit = QLineEdit(settings.claude_api_key)
        self.claude_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.claude_key_edit.setPlaceholderText("sk-ant-…  (console.anthropic.com)")
        api_form.addRow("Claude API key:", self._key_row(self.claude_key_edit))

        self.openai_key_edit = QLineEdit(settings.openai_api_key)
        self.openai_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.openai_key_edit.setPlaceholderText("sk-…  (platform.openai.com)")
        api_form.addRow("OpenAI API key:", self._key_row(self.openai_key_edit))

        layout.addWidget(api_group)

        # ── Identity ──────────────────────────────────────────────────
        identity_group = QGroupBox("Photographer Identity (written to every file)")
        form = QFormLayout(identity_group)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

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

        # ── Location defaults ─────────────────────────────────────────
        loc_group = QGroupBox("Location Defaults (only written if not already set)")
        loc_form = QFormLayout(loc_group)
        loc_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.sublocation_edit = QLineEdit(settings.default_sublocation)
        self.sublocation_edit.setPlaceholderText("e.g. Waimea Valley, Diamond Head Crater")
        loc_form.addRow("Sublocation:", self.sublocation_edit)

        self.city_edit = QLineEdit(settings.default_city)
        self.city_edit.setPlaceholderText("e.g. Honolulu")
        loc_form.addRow("City:", self.city_edit)

        self.state_edit = QLineEdit(settings.default_state_province)
        self.state_edit.setPlaceholderText("e.g. Hawaii")
        loc_form.addRow("State / Province:", self.state_edit)

        self.country_edit = QLineEdit(settings.default_country)
        self.country_edit.setPlaceholderText("e.g. United States")
        loc_form.addRow("Country:", self.country_edit)

        self.country_code_edit = QLineEdit(settings.default_country_code)
        self.country_code_edit.setPlaceholderText("e.g. USA  (ISO 3-letter code)")
        self.country_code_edit.setMaxLength(3)
        loc_form.addRow("Country Code:", self.country_code_edit)

        layout.addWidget(loc_group)

        # ── Publication / IPTC stationery ─────────────────────────────
        pub_group = QGroupBox("Publication Info (written to every file if set)")
        pub_form = QFormLayout(pub_group)
        pub_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.headline_edit = QLineEdit(settings.headline)
        self.headline_edit.setPlaceholderText("e.g. Wasteland Weekend 2024")
        pub_form.addRow("Headline:", self.headline_edit)

        self.job_id_edit = QLineEdit(settings.job_identifier)
        self.job_id_edit.setPlaceholderText("e.g. WED-2024-0412 or assignment number")
        pub_form.addRow("Job / Assignment ID:", self.job_id_edit)

        # Caption format
        sep_val = getattr(settings, "append_separator", "\n\n").replace("\n", "\\n")
        self.separator_edit = QLineEdit(sep_val)
        self.separator_edit.setPlaceholderText("e.g.  \\n\\n--\\n\\n  (use \\n for newline)")
        self.separator_edit.setToolTip(
            "Text inserted between the original caption and the AI caption.\n"
            "Use \\n for a newline. Default: \\n\\n"
        )
        pub_form.addRow("Caption separator:", self.separator_edit)

        sep_hint = QLabel("Use \\n for newline. Only applies when amending existing captions.")
        sep_hint.setStyleSheet("color: #888; font-size: 11px;")
        pub_form.addRow("", sep_hint)

        ai_label_val = getattr(settings, "caption_ai_label", "[ai]")
        self.ai_label_edit = QLineEdit(ai_label_val)
        self.ai_label_edit.setPlaceholderText("e.g.  [ai]  — leave blank to disable")
        pub_form.addRow("AI caption label:", self.ai_label_edit)

        layout.addWidget(pub_group)

        # ── Accessibility fields ───────────────────────────────────────
        acc_group = QGroupBox("Accessibility (IPTC Photo Metadata 2021)")
        acc_form = QFormLayout(acc_group)
        acc_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.alt_text_edit = QLineEdit(getattr(settings, "alt_text", ""))
        self.alt_text_edit.setPlaceholderText("Leave blank to use the AI caption automatically")
        acc_form.addRow("Alt text:", self.alt_text_edit)

        alt_hint = QLabel("Written to XMP-iptcExt:AltTextAccessibility. Used by CMS and screen readers.")
        alt_hint.setWordWrap(True)
        alt_hint.setStyleSheet("color: #888; font-size: 11px;")
        acc_form.addRow("", alt_hint)

        self.ext_desc_edit = QLineEdit(getattr(settings, "extended_description", ""))
        self.ext_desc_edit.setPlaceholderText("Optional longer description for accessibility")
        acc_form.addRow("Extended description:", self.ext_desc_edit)

        layout.addWidget(acc_group)

        # ── Contact ───────────────────────────────────────────────────
        contact_group = QGroupBox("Contact (embedded as XMP-iptcCore contact fields)")
        contact_form = QFormLayout(contact_group)
        contact_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.contact_email_edit = QLineEdit(settings.contact_email)
        self.contact_email_edit.setPlaceholderText("e.g. photo@example.com")
        contact_form.addRow("Email:", self.contact_email_edit)

        self.contact_phone_edit = QLineEdit(settings.contact_phone)
        self.contact_phone_edit.setPlaceholderText("e.g. +1-555-000-0000")
        contact_form.addRow("Phone:", self.contact_phone_edit)

        self.contact_url_edit = QLineEdit(settings.contact_url)
        self.contact_url_edit.setPlaceholderText("e.g. https://example.com")
        contact_form.addRow("Website:", self.contact_url_edit)

        layout.addWidget(contact_group)
        layout.addStretch()

        scroll.setWidget(content)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 8)
        outer.setSpacing(0)
        outer.addWidget(scroll, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        btn_wrapper = QWidget()
        btn_l = QVBoxLayout(btn_wrapper)
        btn_l.setContentsMargins(12, 4, 12, 0)
        btn_l.addWidget(buttons)
        outer.addWidget(btn_wrapper)

    def _save(self) -> None:
        self.settings.ollama_host            = self.ollama_host_edit.text().strip() or "http://localhost:11434"
        self.settings.gemini_api_key         = self.gemini_key_edit.text().strip()
        self.settings.claude_api_key         = self.claude_key_edit.text().strip()
        self.settings.openai_api_key         = self.openai_key_edit.text().strip()
        self.settings.artist_name            = self.artist_edit.text().strip()
        self.settings.copyright_notice       = self.copyright_edit.text().strip()
        self.settings.credit_line            = self.credit_edit.text().strip()
        self.settings.default_sublocation    = self.sublocation_edit.text().strip()
        self.settings.default_city           = self.city_edit.text().strip()
        self.settings.default_state_province = self.state_edit.text().strip()
        self.settings.default_country        = self.country_edit.text().strip()
        self.settings.default_country_code   = self.country_code_edit.text().strip().upper()
        self.settings.headline               = self.headline_edit.text().strip()
        self.settings.job_identifier         = self.job_id_edit.text().strip()
        self.settings.append_separator       = self.separator_edit.text().replace("\\n", "\n")
        self.settings.caption_ai_label       = self.ai_label_edit.text().strip()
        self.settings.alt_text               = self.alt_text_edit.text().strip()
        self.settings.extended_description   = self.ext_desc_edit.text().strip()
        self.settings.contact_email          = self.contact_email_edit.text().strip()
        self.settings.contact_phone          = self.contact_phone_edit.text().strip()
        self.settings.contact_url            = self.contact_url_edit.text().strip()

        save_settings(self.settings)
        self.accept()
