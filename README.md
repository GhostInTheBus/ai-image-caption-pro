# AI Image Caption Pro

**Local AI photo captioning — drag a folder, get IPTC metadata.**

AI Image Caption Pro is a macOS desktop app that looks at your photos, generates captions and keywords using a local or cloud AI vision model, and writes structured IPTC/XMP metadata directly into your files — the same fields that Lightroom, Capture One, and photo libraries read natively.

---

## Features

- **Drag & drop** — drop any folder onto the window, processing starts immediately
- **RAW + JPEG** — reads embedded previews from CR3, ARW, NEF, DNG, RAF, ORF, RW2, and all common JPEG variants; no demosaicing, no quality loss
- **Multiple AI backends** — Ollama (fully local), Google Gemini, Anthropic Claude, OpenAI GPT-4o
- **Amend or replace** — choose whether AI captions are appended to existing metadata or replace it
- **Strict observational captions** — the AI describes only what is visually present; no assumptions about activities or context
- **Crash-safe** — SQLite job tracking means any interrupted batch resumes automatically on next launch
- **Menu bar icon** — app lives in the menu bar; closing the window doesn't quit, so long batches run uninterrupted
- **Per-batch context hints** — tell the AI where or when photos were taken to improve keyword accuracy

---

## Requirements

| Requirement | Notes |
|---|---|
| macOS 13+ | Apple Silicon and Intel supported |
| Python 3.11+ | 3.13 recommended |
| Ollama | Only needed for local AI backend |
| ExifTool | Bundled in the prebuilt app; install via Homebrew for development |

Cloud backends (Gemini, Claude, OpenAI) require only an API key — no local model needed.

---

## Installation

### Prebuilt app (recommended)

1. Download `AI-Image-Caption-Pro-mac.dmg` from the [latest release](../../releases/latest)
2. Open the DMG, drag the app to Applications
3. First launch: right-click → **Open** (app is not notarized — it's open source, build it yourself if you prefer)

### From source

```bash
# Prerequisites
brew install exiftool
pip install -r requirements.txt

# Launch
python main.py
```

### Setting up Ollama (local AI backend)

Ollama must be installed and running before the app can use local models.

```bash
# Install
brew install ollama         # macOS
# or: curl -fsSL https://ollama.com/install.sh | sh  (Linux)

# Pull a vision model (do this once)
ollama pull gemma3:12b      # fast, recommended
ollama pull gemma3:27b      # best quality, slower
ollama pull llava:13b       # reliable baseline
ollama pull qwen2.5vl:7b    # strong at text in images

# Start the server (runs in the background)
ollama serve
```

By default Ollama listens on `localhost:11434`. To use it from a remote machine (e.g. a NAS or another computer on your network), bind it to all interfaces:

```bash
OLLAMA_HOST=0.0.0.0 ollama serve
```

Then open Settings in the app and change **Ollama Host** to `http://your-machine-ip:11434`.

---

## Quick Start

1. Launch Iris — a small floating window appears in the corner of your screen
2. Open **Settings** (⚙ icon) — choose your AI backend and fill in your name and copyright
3. Drag any folder of photos onto the window
4. Watch captions and keywords appear in your files in real time
5. If you close mid-batch, relaunch — Iris will offer to resume

---

## AI Backends

| Backend | Privacy | Cost | Setup |
|---|---|---|---|
| **Ollama** (default) | 100% local, no data leaves your machine | Free | Install Ollama + pull a model |
| **Google Gemini** | Cloud | Pay-per-use | Add API key in Settings |
| **Anthropic Claude** | Cloud | Pay-per-use | Add API key in Settings |
| **OpenAI GPT-4o** | Cloud | Pay-per-use | Add API key in Settings |

Switch backends in Settings without losing any job history. The Ollama backend works fully offline once the model is downloaded.

---

## IPTC Fields Written

| Field | Behavior |
|---|---|
| `IPTC:Caption-Abstract` | AI-generated; amends or replaces existing (configurable) |
| `IPTC:Keywords` | AI-generated; merged and deduplicated with existing keywords |
| `IPTC:By-line` | Written from Settings (your name) |
| `IPTC:CopyrightNotice` | Written from Settings; `%Y` expands to current year |
| `IPTC:Credit` | Written from Settings |
| `IPTC:City` | Written from Settings only if field is not already set |
| `IPTC:Country-PrimaryLocationName` | Written from Settings only if field is not already set |
| `XMP:Description` | Mirror of caption (Lightroom / Capture One compatibility) |
| `XMP:Subject` | Mirror of keywords |
| `XMP:Creator` | Mirror of artist |
| `XMP:Rights` | Mirror of copyright |

---

## Supported Formats

**RAW:** `.cr3` `.cr2` `.nef` `.arw` `.dng` `.orf` `.rw2` `.raf`

**JPEG:** `.jpg` `.jpeg`

Iris extracts the camera-embedded JPEG preview for vision processing — the original RAW file is never decoded or modified beyond metadata.

---

## Settings

Settings are stored at `~/.photoai/settings.toml` and job history at `~/.photoai/jobs.db`.

| Setting | Description |
|---|---|
| AI Backend | Ollama / Gemini / Claude / OpenAI |
| Ollama Host | Default `http://localhost:11434` |
| Model | Dropdown of installed models (Ollama) or curated list (cloud) |
| API Key | For cloud backends |
| Caption Mode | **Amend** (append to existing) or **Replace** (overwrite) |
| Artist / Credit | Written to `By-line` and `Credit` IPTC fields |
| Copyright | Supports `%Y` for year substitution |
| City / Country | Written to files that don't already have location metadata |
| Max Keywords | Number of keywords to generate per file |
| Context Hint | Optional per-batch context (e.g. "coastal wedding, June 2025") |
| Recursive Scan | Whether to process subfolders |
| Skip Already Done | Skip files already processed in a previous batch |

---

## Building from Source

```bash
# macOS — produces Iris-mac.dmg (requires create-dmg)
brew install create-dmg
bash build_mac.sh

# Linux — produces dist/PhotoAI/
bash build_linux.sh
```

The macOS build runs entirely in `/tmp` to avoid codesign issues on external volumes (a macOS Sequoia constraint). The finished `.app` path is printed at the end and saved to `/tmp/photoai_last_build.txt`.

---

## Project Structure

```
main.py                     Entry point, QApplication subclass
app/
  core/
    agent.py                Batch orchestrator (QThread worker)
    captioner.py            AI vision calls — Ollama, Gemini, Claude, OpenAI
    exiftool.py             ExifTool subprocess wrapper (read/write metadata)
    job_db.py               SQLite job tracker (crash recovery)
  ui/
    floating_window.py      Main window — drag-and-drop, thread wiring
    progress_panel.py       Per-file progress rows
    settings_dialog.py      Settings UI + TOML persistence
    tray.py                 macOS menu bar icon
  models.py                 Settings, ImageJob, BatchJob dataclasses
assets/                     Icons and images
bin/                        Bundled exiftool (populated at build time)
build_mac.sh                PyInstaller macOS build script
build_linux.sh              PyInstaller Linux build script
AIImageCaptionPro.spec                PyInstaller spec (used by build_mac.sh)
```

---

## Adding a New AI Backend

1. Add backend fields to `Settings` in `app/models.py`
2. Add a `_generate_<backend>()` function in `app/core/captioner.py`
3. Wire it into the `generate_caption()` dispatcher
4. Add UI fields in `app/ui/settings_dialog.py`

The `generate_caption(image_path, settings)` signature is the stable interface.

---

## Contributing

Issues and pull requests welcome. A few pointers:

- There is no test suite yet — manual verification steps are in `CLAUDE.md`
- All UI work must stay off the worker thread — use `pyqtSignal` for cross-thread communication
- ExifTool is the only metadata tool; don't introduce a Pillow or exiv2 dependency

---

## About

VibeCoded by a professional photographer and tech enthusiast. Built with AI assistance — because tools should work for you, not the other way around.

Issues and pull requests welcome.
