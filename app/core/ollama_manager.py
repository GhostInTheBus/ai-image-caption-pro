"""
Manages the bundled Ollama server process.

Resolution order for the ollama binary:
  1. PyInstaller bundle: <_MEIPASS>/bin/ollama
  2. Source tree: bin/ollama next to main.py
  3. System PATH (homebrew / manual install)

Lifecycle:
  ensure_running() — starts ollama serve if the API is not already responding.
                     Safe to call repeatedly; no-ops if already up.
  stop()           — terminates only the process WE started.
  has_any_vision_model() — True if at least one vision-capable model is pulled.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

_managed_process: Optional[subprocess.Popen] = None

OLLAMA_HOST = "http://localhost:11434"

# Models we know are vision-capable — used to filter list_local_models()
_VISION_PREFIXES = (
    "gemma3", "llava", "qwen2.5vl", "moondream",
    "minicpm", "bakllava", "cogvlm", "phi3",
)


# ── Binary resolution ─────────────────────────────────────────────────────────

def find_binary() -> Optional[str]:
    """Return path to the ollama binary, or None if not found."""
    if hasattr(sys, "_MEIPASS"):
        bundled = Path(sys._MEIPASS) / "bin" / "ollama"
        if bundled.exists():
            return str(bundled)
    project_root = Path(__file__).parent.parent.parent
    local = project_root / "bin" / "ollama"
    if local.exists():
        return str(local)
    return shutil.which("ollama")


# ── Server lifecycle ──────────────────────────────────────────────────────────

def is_responsive() -> bool:
    """Return True if the Ollama API is already answering on localhost."""
    try:
        import urllib.request
        urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=2)
        return True
    except Exception:
        return False


def ensure_running() -> bool:
    """
    Start the Ollama server if it is not already responding.
    Blocks up to 15 s waiting for the server to become ready.
    Returns True if the server is responsive after this call.
    """
    global _managed_process

    if is_responsive():
        return True

    binary = find_binary()
    if not binary:
        return False

    try:
        _managed_process = subprocess.Popen(
            [binary, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False

    for _ in range(30):
        time.sleep(0.5)
        if is_responsive():
            return True

    return False


def stop() -> None:
    """Terminate the Ollama process we started (no-op if we didn't start it)."""
    global _managed_process
    if _managed_process and _managed_process.poll() is None:
        _managed_process.terminate()
        try:
            _managed_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _managed_process.kill()
    _managed_process = None


# ── Model queries ─────────────────────────────────────────────────────────────

def list_local_models() -> list[str]:
    """Return names of all locally available models."""
    try:
        import urllib.request
        with urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=5) as r:
            data = json.loads(r.read())
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def has_any_vision_model() -> bool:
    """True if at least one vision-capable model is available locally."""
    models = list_local_models()
    for name in models:
        base = name.split(":")[0].lower()
        if any(base.startswith(p) for p in _VISION_PREFIXES):
            return True
    # If models exist but aren't in our known list, assume they're usable
    return bool(models)
