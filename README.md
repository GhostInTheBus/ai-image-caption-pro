# AI Image Caption Pro

**Local AI photo captioning — drag a folder, get IPTC metadata.**

AI Image Caption Pro is a macOS desktop app that looks at your photos, generates captions and keywords using a local or cloud AI vision model, and writes structured IPTC/XMP metadata directly into your files — the same fields that Lightroom, Capture One, Photo Mechanic, and photo libraries read natively.

---

## Features

- **Drag & drop** — drop any folder or individual files onto the window; processing starts immediately
- **RAW + JPEG + PSD** — reads embedded previews from CR3, CR2, ARW, NEF, DNG, RAF, ORF, RW2, PSB/PSD, and all JPEG variants; the original file is never decoded or degraded
- **XMP sidecar files** — automatically written alongside RAW files so Photo Mechanic shows metadata instantly without a manual refresh (Cmd+R)
- **Multiple AI backends** — Ollama (fully local, no API key), Google Gemini, Anthropic Claude, OpenAI GPT-4o
- **AI brief** — write a `.md` file describing your photography style, gear, subjects, and vocabulary; the app reads it for every caption request. Drop a `context.md` in any shoot folder for per-folder overrides
- **Verbosity control** — separate sliders for keyword count (Minimal → Exhaustive) and description length (Brief → Exhaustive)
- **Seed keywords** — provide comma-separated keywords that are always merged into every caption's keyword list, regardless of what the AI generates
- **Amend or replace** — append AI captions to existing metadata, or replace outright
- **Strict observational captions** — the AI describes only what is visually present; no guessing at occasion, relationship, or intent
- **Crash-safe** — SQLite job tracking means any interrupted batch resumes automatically on next launch
- **Menu bar icon** — app lives in the menu bar; closing the window doesn't quit, so long batches run uninterrupted

---

## Requirements

| Requirement | Notes |
|---|---|
| macOS 13+ | Apple Silicon and Intel supported |
| Python 3.11+ | 3.13 recommended |
| ExifTool | Bundled in the prebuilt app; `brew install exiftool` for development |
| Ollama | Only needed for the local AI backend |

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
brew install exiftool fswatch
pip install -r requirements.txt

# Launch with auto-restart on code changes (recommended for development)
bash dev.sh

# Or launch directly
python main.py
```

### Setting up Ollama (local AI backend)

```bash
# Install
brew install ollama

# Pull a vision model (do this once)
ollama pull gemma3:12b      # fast, recommended
ollama pull gemma3:27b      # best quality, slower
ollama pull llava:13b       # reliable baseline
ollama pull qwen2.5vl:7b    # strong at text in images

# Start the server
ollama serve
```

By default Ollama listens on `localhost:11434`. To use it from another machine on your network:

```bash
OLLAMA_HOST=0.0.0.0 ollama serve
```

Then open Settings in the app and set **Ollama Host** to `http://your-machine-ip:11434`.

---

## Supported Formats

| Type | Extensions |
|---|---|
| Canon RAW | `.cr3` `.cr2` |
| Sony RAW | `.arw` |
| Nikon RAW | `.nef` `.nrw` |
| Adobe DNG | `.dng` |
| Fujifilm RAW | `.raf` |
| Olympus RAW | `.orf` |
| Panasonic RAW | `.rw2` |
| Adobe Photoshop | `.psd` `.psb` |
| JPEG | `.jpg` `.jpeg` |

RAW and PSD files have a preview JPEG extracted before being sent to the AI — the original pixel data is never touched.

---

## AI Brief

Create a `.md` file that describes your photography context — the app includes it in every caption prompt:

```markdown
# Wasteland Weekend 2024

Post-apocalyptic festival in the California desert. Subjects include:
- custom-built Mad Max vehicles and art cars
- costumed performers in dystopian gear
- fire performance and nighttime installations

Style: documentary. Vocabulary: post-apocalyptic, Wasteland Weekend, diesel punk.
```

Set the path in **Settings → AI brief (.md)**. Drop a `context.md` file into any shoot folder to override per-folder.

---

## Photo Mechanic Compatibility

For RAW files, the app writes both:
1. **Embedded XMP** — directly into the RAW file via ExifTool
2. **XMP sidecar** — a `.xmp` file alongside the RAW (e.g. `photo.cr2` → `photo.xmp`)

Photo Mechanic reads sidecar files instantly. Without the sidecar, PM requires a manual **Cmd+R** metadata refresh to see embedded RAW XMP changes.

PSD files have XMP embedded directly — PM reads these without a sidecar.

---

## Settings

Settings are stored at `~/.photoai/settings.toml` and job history at `~/.photoai/jobs.db`.

| Setting | Description |
|---|---|
| AI Backend | Ollama / Gemini / Claude / OpenAI |
| Ollama Host | Default `http://localhost:11434` |
| Model | Dropdown of installed models (Ollama) or curated list (cloud) |
| API Key | For cloud backends |
| Keyword detail | Slider 1–5: Minimal (2–4 kw) → Exhaustive (12–20 kw) |
| Description length | Slider 1–5: Brief (1 sentence) → Exhaustive (6–8 sentences) |
| Caption Mode | **Amend** (append to existing) or **Replace** (overwrite) |
| Artist / Credit / Copyright | Written to every file; `%Y` expands to current year |
| Location defaults | City, state, country — only written if not already present |
| Publication fields | Headline, Source, Instructions, Job ID |
| Contact fields | Email, phone, URL — written as XMP-iptcCore contact fields |
| AI brief (.md) | Path to a global photographer brief; per-folder `context.md` auto-detected |
| Always-include keywords | Comma-separated keywords guaranteed in every output |
| Recursive scan | Process subfolders |
| Skip already done | Skip files processed in a previous batch |

---

## Building from Source

```bash
# macOS — produces AI-Image-Caption-Pro-mac.dmg
brew install create-dmg
bash build_mac.sh

# Linux — produces dist/AI Image Caption Pro/
bash build_linux.sh
```

GitHub Actions (`.github/workflows/release.yml`) builds both automatically on `git tag v*` push.

---

## Project Structure

```
main.py                       Entry point, QApplication subclass
app/
  core/
    agent.py                  Batch orchestrator (QThread worker)
    captioner.py              AI vision calls — Ollama, Gemini, Claude, OpenAI
    exiftool.py               ExifTool wrapper (read/write metadata, XMP sidecar)
    job_db.py                 SQLite job tracker (crash recovery)
  ui/
    floating_window.py        Main window — drag-and-drop, thread wiring
    progress_panel.py         Per-file progress rows with inline error display
    settings_dialog.py        Settings UI + TOML persistence
    tray.py                   macOS menu bar icon
  models.py                   Settings, ImageJob, BatchJob dataclasses
assets/                       Icons and images
bin/                          Bundled exiftool (populated at build time)
dev.sh                        Development watcher (auto-restart on .py changes)
build_mac.sh                  PyInstaller macOS build script
build_linux.sh                PyInstaller Linux build script
```

---

## Adding a New AI Backend

1. Add backend fields to `Settings` in `app/models.py`
2. Add a `_generate_<backend>()` function in `app/core/captioner.py`
3. Wire it into the `generate_caption()` dispatcher
4. Add UI fields in `app/ui/settings_dialog.py`

The `generate_caption(image_path, settings, context_md)` signature is the stable interface.

---

## Contributing

Issues and pull requests welcome.

- No test suite yet — manual verification steps are in `CLAUDE.md`
- All UI updates must go through `pyqtSignal` — never touch widgets from the worker thread
- ExifTool is the only metadata dependency; no Pillow or exiv2

---

## About

VibeCoded by a professional photographer and tech enthusiast. Built with AI assistance — because tools should work for you, not the other way around.
