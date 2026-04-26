"""
Core data models for PhotoAI Caption Studio.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass
class ImageJob:
    """Represents a single image file to be captioned."""
    file_path: Path
    batch_id: str
    status: JobStatus = JobStatus.PENDING
    error_msg: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    @property
    def job_id(self) -> str:
        """Stable ID derived from the absolute file path."""
        return hashlib.sha1(str(self.file_path.resolve()).encode()).hexdigest()

    @property
    def is_raw(self) -> bool:
        return self.file_path.suffix.lower() in {
            ".cr3", ".cr2", ".arw", ".nef", ".nrw",
            ".dng", ".raf", ".orf", ".rw2"
        }

    @property
    def is_psd(self) -> bool:
        return self.file_path.suffix.lower() in {".psd", ".psb"}

    @property
    def needs_preview(self) -> bool:
        """True for any format that requires preview extraction before AI captioning."""
        return self.is_raw or self.is_psd

    @property
    def display_name(self) -> str:
        return self.file_path.name


@dataclass
class BatchJob:
    """Represents a folder drop — a collection of ImageJobs."""
    batch_id: str          # folder path hash
    folder_path: Path
    total: int = 0
    done: int = 0
    errors: int = 0
    skipped: int = 0
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def pending(self) -> int:
        return max(0, self.total - self.done - self.errors - self.skipped)

    @property
    def progress_pct(self) -> float:
        if self.total == 0:
            return 0.0
        return (self.done + self.errors + self.skipped) / self.total * 100


@dataclass
class Settings:
    """User settings persisted to ~/.photoai/settings.toml."""
    artist_name: str = ""
    copyright_notice: str = ""
    credit_line: str = ""
    default_city: str = ""
    default_state_province: str = ""
    default_sublocation: str = ""
    default_country: str = ""
    default_country_code: str = ""

    # Publication / stationery
    headline: str = ""
    source: str = ""
    instructions: str = ""
    job_identifier: str = ""

    # Contact
    contact_email: str = ""
    contact_phone: str = ""
    contact_url: str = ""

    # ── AI backend ────────────────────────────────────────────────────────────
    backend: str = "ollama"             # "ollama" | "gemini" | "claude" | "openai"

    # Ollama (local)
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "gemma3:4b"

    # Google Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    # Anthropic Claude
    claude_api_key: str = ""
    claude_model: str = "claude-haiku-4-5-20251001"

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Context hint — appended to the AI prompt for every image in the batch
    context_hint: str = ""             # e.g. "Shot in Kyoto, Japan, spring 2024"
    context_file: str = ""             # path to a global .md brief (style, gear, voice)

    caption_mode: str = "amend"          # "amend" = append to existing | "replace" = overwrite
    append_separator: str = "\n\n"      # separator when appending AI caption to existing
    max_keywords: int = 10              # legacy — now derived from keyword_verbosity internally
    keyword_verbosity: int = 3          # 1=minimal … 5=exhaustive (controls LLM keyword count range)
    description_verbosity: int = 3      # 1=brief … 5=exhaustive (controls LLM sentence count)
    user_keywords: str = ""             # comma-separated seeds always merged into output
    recursive_scan: bool = False        # scan subfolders
    skip_already_done: bool = True      # skip files already processed in this session

    def copyright_year_notice(self) -> str:
        """Returns copyright with current year if %Y placeholder present."""
        import datetime as dt
        return self.copyright_notice.replace("%Y", str(dt.date.today().year))
