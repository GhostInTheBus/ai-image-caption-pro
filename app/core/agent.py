"""
BatchAgent — the main orchestration pipeline.

Runs in a QThread (worker thread) so the UI stays responsive.
Emits Qt signals for progress updates.

Pipeline per image:
  scan → pending → extract preview → read existing IPTC →
  generate caption → merge metadata → write IPTC → mark done
"""
from __future__ import annotations

import hashlib
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Callable, List, Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from app.core import exiftool, job_db
from app.core.captioner import generate_caption
from app.models import BatchJob, ImageJob, JobStatus, Settings

# ── File type filtering ───────────────────────────────────────────────────────

RAW_EXTENSIONS = {
    ".cr3", ".cr2", ".arw", ".nef", ".nrw",
    ".dng", ".raf", ".orf", ".rw2",
}
JPEG_EXTENSIONS = {".jpg", ".jpeg"}
PSD_EXTENSIONS = {".psd", ".psb"}
IMAGE_EXTENSIONS = RAW_EXTENSIONS | JPEG_EXTENSIONS | PSD_EXTENSIONS

# Synology metadata dirs to skip
SKIP_DIRS = {"@eaDir", "#recycle", ".Spotlight-V100", ".Trashes"}


def scan_folder(folder: Path, recursive: bool = False) -> List[Path]:
    """Return all image files in folder, skipping Synology metadata dirs and macOS resource forks."""
    files: List[Path] = []
    glob = "**/*" if recursive else "*"
    for path in sorted(folder.glob(glob)):
        if any(skip in path.parts for skip in SKIP_DIRS):
            continue
        if path.name.startswith("._"):  # macOS AppleDouble resource fork files
            continue
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            files.append(path)
    return files


def make_batch_id(folder: Path) -> str:
    return hashlib.sha1(str(folder.resolve()).encode()).hexdigest()[:16]


# ── Worker thread ─────────────────────────────────────────────────────────────

class BatchWorker(QObject):
    """
    Runs in a QThread. All heavy work happens here so PyQt6 UI stays responsive.

    Signals:
      job_started(filename)       — emitted when a file begins processing
      job_done(filename)          — emitted on successful write
      job_error(filename, msg)    — emitted on failure
      job_skipped(filename)       — emitted when file already done
      batch_complete(done, errors, skipped, total)
      progress(done_count, total_count)
      status_msg(message)         — generic status text for UI
    """

    job_started  = pyqtSignal(str)
    job_done     = pyqtSignal(str)
    job_error    = pyqtSignal(str, str)
    job_skipped  = pyqtSignal(str)
    batch_complete = pyqtSignal(int, int, int, int)   # done, errors, skipped, total
    progress     = pyqtSignal(int, int)
    status_msg   = pyqtSignal(str)

    def __init__(
        self,
        folder: Path,
        settings: Settings,
        resume: bool = False,
        files: Optional[List[Path]] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.folder = folder
        self.settings = settings
        self.resume = resume
        self._files = files  # explicit file list; if set, skips folder scan
        self._stop_requested = False
        self._pause_requested = False

    def stop(self) -> None:
        self._stop_requested = True

    def pause(self) -> None:
        self._pause_requested = True

    def resume_processing(self) -> None:
        self._pause_requested = False

    def run(self) -> None:
        """Entry point — called by QThread.started signal."""
        job_db.init_db()
        job_db.reset_interrupted_jobs()

        batch_id = make_batch_id(self.folder)

        if self._files is not None:
            image_files = self._files
            self.status_msg.emit(f"Processing {len(image_files)} file(s)…")
        else:
            self.status_msg.emit(f"Scanning {self.folder.name}…")
            image_files = scan_folder(self.folder, self.settings.recursive_scan)

        if not image_files:
            self.status_msg.emit("No image files found.")
            self.batch_complete.emit(0, 0, 0, 0)
            return

        batch = BatchJob(
            batch_id=batch_id,
            folder_path=self.folder,
            total=len(image_files),
        )
        jobs = [ImageJob(file_path=f, batch_id=batch_id) for f in image_files]
        job_db.create_batch(batch, jobs)

        self.status_msg.emit(f"Found {len(image_files)} images. Starting…")

        done = errors = skipped = 0
        total = len(image_files)

        with tempfile.TemporaryDirectory(prefix="photoai_") as tmp_dir:
            tmp_path = Path(tmp_dir)

            for job in jobs:
                # Check pause / stop
                while self._pause_requested and not self._stop_requested:
                    QThread.msleep(200)
                if self._stop_requested:
                    self.status_msg.emit("Stopped by user.")
                    break

                # Skip if already done (re-dropped folder or resume)
                if self.settings.skip_already_done and job_db.is_done(job.job_id):
                    skipped += 1
                    self.job_skipped.emit(job.display_name)
                    self.progress.emit(done + errors + skipped, total)
                    continue

                self.job_started.emit(job.display_name)
                job_db.mark_running(job.job_id)

                try:
                    self._process_image(job, tmp_path)
                    job_db.mark_done(job.job_id)
                    done += 1
                    self.job_done.emit(job.display_name)
                except Exception as e:
                    msg = str(e)
                    # Print full stack trace to terminal so dev.sh output shows root cause
                    print(f"\n[ERROR] {job.display_name}: {msg}", file=sys.stderr)
                    traceback.print_exc(file=sys.stderr)
                    print("", file=sys.stderr, flush=True)
                    job_db.mark_error(job.job_id, msg)
                    errors += 1
                    self.job_error.emit(job.display_name, msg)

                self.progress.emit(done + errors + skipped, total)

        self.batch_complete.emit(done, errors, skipped, total)

    def _process_image(self, job: ImageJob, tmp_dir: Path) -> tuple[str, list[str]]:
        """
        Full pipeline for one image:
          1. Get a JPEG for the AI to look at
          2. Read existing IPTC
          3. Generate caption + keywords via Ollama
          4. Write merged IPTC back to original file
        """
        s = self.settings

        # Step 1: get preview JPEG
        self.status_msg.emit(f"[1/4] Extracting preview — {job.display_name}")
        if job.needs_preview:
            preview_path = exiftool.extract_preview_jpeg(job.file_path, tmp_dir)
        else:
            preview_path = job.file_path   # JPEGs go straight to AI
        self.status_msg.emit(f"[2/4] Reading existing metadata — {job.display_name}")

        # Step 2: read existing metadata
        existing_caption = exiftool.read_existing_caption(job.file_path)
        existing_keywords = exiftool.read_existing_keywords(job.file_path)

        # Step 3: generate caption — load global brief + per-folder context.md
        self.status_msg.emit(f"[3/4] Sending to AI ({s.backend}) — {job.display_name}")
        context_parts: list[str] = []
        global_brief = getattr(s, "context_file", "")
        if global_brief:
            p = Path(global_brief)
            if p.exists():
                context_parts.append(p.read_text(encoding="utf-8"))
        folder_brief = job.file_path.parent / "context.md"
        if folder_brief.exists():
            context_parts.append(folder_brief.read_text(encoding="utf-8"))
        context_md = "\n\n---\n\n".join(context_parts)
        if context_md:
            print(f"[context] {job.display_name}: loaded {len(context_md)} chars from {len(context_parts)} source(s)", flush=True)
        else:
            print(f"[context] {job.display_name}: no context brief found", flush=True)

        caption, keywords = generate_caption(
            image_path=preview_path, settings=s, context_md=context_md
        )
        self.status_msg.emit(f"[4/4] Writing metadata — {job.display_name}")

        # Step 4: write IPTC to original file
        amend = getattr(s, "caption_mode", "amend") == "amend"
        iptc_kwargs = dict(
            artist_name=s.artist_name,
            copyright_notice=s.copyright_year_notice(),
            credit_line=s.credit_line,
            headline=s.headline,
            source=s.source,
            instructions=s.instructions,
            job_identifier=s.job_identifier,
            city=s.default_city,
            state_province=s.default_state_province,
            sublocation=s.default_sublocation,
            country=s.default_country,
            country_code=s.default_country_code,
            contact_email=s.contact_email,
            contact_phone=s.contact_phone,
            contact_url=s.contact_url,
            append_separator=s.append_separator,
        )

        exiftool.write_iptc(
            file_path=job.file_path,
            caption=caption,
            keywords=keywords,
            existing_caption=existing_caption if amend else None,
            existing_keywords=existing_keywords,
            **iptc_kwargs,
        )

        # Verify the write actually persisted — reads back the file immediately after
        verified = exiftool.verify_write(job.file_path)
        # XMP fields are used for RAW formats that don't support IPTC natively
        written_caption = (
            verified.get("Caption-Abstract")
            or verified.get("IPTC:Caption-Abstract")
            or verified.get("Description")
            or verified.get("XMP:Description")
            or ""
        )
        written_kw = (
            verified.get("Keywords")
            or verified.get("IPTC:Keywords")
            or verified.get("Subject")
            or verified.get("XMP:Subject")
            or []
        )
        if isinstance(written_kw, str):
            written_kw = [written_kw]
        if not written_caption.strip() and not written_kw:
            raise RuntimeError(
                f"exiftool reported success but no caption or keywords found in "
                f"{job.file_path.name} after write. File may be read-only or on an "
                f"unsupported filesystem."
            )
        kw_count = len(written_kw)
        self.status_msg.emit(
            f"✓ {job.display_name}: {len(written_caption)} char caption, {kw_count} keyword(s)"
        )

        # Write XMP sidecar for RAW files — Photo Mechanic reads these instantly
        # without needing a manual Cmd+R metadata refresh (embedded RAW XMP requires it)
        if job.is_raw:
            exiftool.write_xmp_sidecar(
                raw_path=job.file_path,
                caption=written_caption,   # use verified caption (includes existing + [ai])
                keywords=keywords,
                artist=s.artist_name,
                copyright_notice=s.copyright_year_notice(),
            )

        # If a sidecar JPG exists alongside a RAW or PSD, write to that too
        if job.needs_preview:
            for ext in (".jpg", ".JPG", ".jpeg", ".JPEG"):
                sidecar = job.file_path.with_suffix(ext)
                if sidecar.exists():
                    sidecar_existing_caption = exiftool.read_existing_caption(sidecar)
                    sidecar_existing_kw = exiftool.read_existing_keywords(sidecar)
                    exiftool.write_iptc(
                        file_path=sidecar,
                        caption=caption,
                        keywords=keywords,
                        existing_caption=sidecar_existing_caption if amend else None,
                        existing_keywords=sidecar_existing_kw,
                        **iptc_kwargs,
                    )

        return caption, keywords
