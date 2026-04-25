# PhotoAI Caption Studio — Claude Code Instructions

## Project Overview

A local-first AI photo captioning desktop app. Drag a folder of RAW or JPEG photos onto the floating window → the app extracts embedded preview JPEGs from RAW files, sends them to a local Ollama vision model for captioning, and writes structured IPTC + XMP metadata back to the original files.

**Key design constraints:**
- All processing is local — no cloud, no API keys
- Never overwrites existing captions — always appends
- Crash-safe: SQLite job tracking means any interrupted batch resumes on relaunch
- Target OS: macOS + Linux

## Running the App

```bash
# Prerequisites
brew install exiftool          # macOS
ollama pull gemma3:12b         # or any vision model

# Install Python deps
pip install -r requirements.txt

# Launch
python main.py
```

Settings are stored at `~/.photoai/settings.toml` (created on first save).
Job history is at `~/.photoai/jobs.db` (SQLite).

## Architecture

```
main.py
└── FloatingWindow (PyQt6, always-on-top, frameless)
    ├── DropZonePage        — 220×200 idle state, accepts folder drops
    ├── ProgressPanel       — expands to 360×480 during batch
    └── SettingsDialog      — reads/writes ~/.photoai/settings.toml

BatchWorker (QThread)         — never block the UI thread
├── scan_folder()             — finds RAW + JPG, skips @eaDir/#recycle
├── job_db.py (SQLite/WAL)    — pending → running → done/error state machine
├── exiftool.py               — subprocess wrapper around system/bundled exiftool
│   ├── extract_preview_jpeg() — exiftool -b -JpgFromRaw (fallback: -PreviewImage)
│   ├── read_existing_iptc()   — exiftool -json
│   └── write_iptc()           — exiftool -overwrite_original
└── captioner.py              — ollama.chat() with structured JSON prompt
```

## Critical Files

| File | Role |
|---|---|
| `app/core/agent.py` | Main pipeline orchestrator (QThread worker) |
| `app/core/exiftool.py` | ExifTool read/write — all metadata logic here |
| `app/core/captioner.py` | Ollama vision call + JSON parsing + keyword dedup |
| `app/core/job_db.py` | SQLite job tracker — crash recovery lives here |
| `app/models.py` | `ImageJob`, `BatchJob`, `Settings` dataclasses |
| `app/ui/floating_window.py` | Main window — drag-and-drop, thread wiring |
| `app/ui/settings_dialog.py` | Settings persistence (TOML) + model picker |

## Key Patterns & Gotchas

### ExifTool binary resolution
`exiftool.py` looks for a bundled binary at `bin/exiftool` first, then falls back to system PATH. For development, system exiftool is fine. For distribution, `build_mac.sh`/`build_linux.sh` bundle it.

### RAW preview extraction
```python
# exiftool extracts the camera-embedded JPEG — no demosaicing needed
exiftool -b -JpgFromRaw file.CR3 > preview.jpg
# Fallback for older RAW formats:
exiftool -b -PreviewImage file.CR3 > preview.jpg
```
Extracted previews go to a `tempfile.TemporaryDirectory` that is cleaned up after each batch.

### Ollama model names
The model field in settings is free-text. Common working vision models:
- `gemma3:12b` — fast, recommended
- `gemma3:27b` — best quality
- `llava:13b` — reliable baseline
- `qwen2.5vl:7b` — strong at text in images

Query available models: `GET http://localhost:11434/api/tags`

### Caption append logic
```python
# In exiftool.py write_iptc()
if existing_caption:
    final = f"{existing_caption.strip()} [AI: {new_caption}]"
else:
    final = new_caption
```
Separator configurable in `Settings.append_separator`.

### Keyword deduplication
Keywords are lowercased for dedup comparison but stored with original casing. Blocked terms: `photo, image, photography, picture, photograph, camera`.

### PyQt6 threading
- `BatchWorker` is a `QObject` moved to a `QThread` (NOT a QThread subclass — that pattern is incorrect in Qt6)
- All UI updates happen via `pyqtSignal` — never touch widgets from the worker thread
- SQLite uses WAL journal mode so UI reads don't block worker writes

### Synology metadata
`scan_folder()` in `agent.py` skips dirs named `@eaDir` and `#recycle` — Synology NAS metadata that would otherwise appear in `glob()` results.

### Settings TOML
- Python 3.11+: uses stdlib `tomllib` (read) + custom write
- Python 3.10: falls back to `tomli` package (add to requirements if needed)
- Settings file is gitignored — never commit credentials

## IPTC Fields Written

| ExifTool Tag | Behaviour |
|---|---|
| `IPTC:Caption-Abstract` | Append to existing, or write fresh |
| `IPTC:Keywords` | Merge + deduplicate with existing |
| `IPTC:By-line` | Always write from settings |
| `IPTC:CopyrightNotice` | Always write; `%Y` → current year |
| `IPTC:Credit` | Always write from settings |
| `IPTC:City` | Only write if not already set |
| `IPTC:Country-PrimaryLocationName` | Only write if not already set |
| `XMP:Description` | Mirror of caption (Lightroom/Capture One compat) |
| `XMP:Subject` | Mirror of keywords |
| `XMP:Creator` | Mirror of artist |
| `XMP:Rights` | Mirror of copyright |

## Testing Approach

There is no test suite yet. Manual verification steps:

```bash
# 1. Drop a folder → confirm batch runs and files are processed
exiftool -IPTC:all -XMP:all your_file.CR3

# 2. Drop same folder again → confirm 'skipped' for already-done files

# 3. Kill mid-batch → relaunch → confirm resume prompt appears

# 4. File with existing caption → confirm append not replace

# 5. Check error handling — drop a folder with a corrupt RAW
#    → confirm error row in UI, other files continue processing
```

## Packaging

```bash
# macOS → dist/PhotoAI.app + PhotoAI-mac.dmg
bash build_mac.sh

# Linux → dist/PhotoAI/
bash build_linux.sh
```

GitHub Actions (`.github/workflows/release.yml`) builds both automatically on `git tag v*` push.

## Adding a New AI Backend

To add Claude API or OpenAI-compatible endpoints:
1. Add a `backend` field to `Settings` (`"ollama"` | `"claude"` | `"openai"`)
2. Add backend-specific logic in `captioner.py` behind an `if settings.backend == ...` branch
3. Expose model/key fields in `SettingsDialog`

The `generate_caption(image_path, model, host)` signature is the interface to keep stable.

## Known Issues / Future Work

- No test suite — add pytest + mock ExifTool for unit tests
- Settings UI has no live preview of what the copyright string will look like with `%Y` expanded
- Large RAW files (>50MB) can make preview extraction slow — consider async progress for that step
- No Windows support yet (PyQt6 + ExifTool work on Windows, build script needed)
- Model picker dropdown requires Ollama to be running at settings-open time
