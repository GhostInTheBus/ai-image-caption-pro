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
import tempfile
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
IMAGE_EXTENSIONS = RAW_EXTENSIONS | JPEG_EXTENSIONS

# Synology metadata dirs to skip
SKIP_DIRS = {"@eaDir", "#recycle", ".Spotlight-V100", ".Trashes"}


def scan_folder(folder: Path, recursive: bool = False) -> List[Path]:
    """Return all image files in folder, skipping Synology metadata dirs."""
    files: List[Path] = []
    glob = "**/*" if recursive else "*"
    for path in sorted(folder.glob(glob)):
        if any(skip in path.parts for skip in SKIP_DIRS):
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
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.folder = folder
        self.settings = settings
        self.resume = resume
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

        # Scan folder and register all jobs
        self.status_msg.emit(f"Scanning {self.folder.name}…")
        image_files = scan_folder(self.folder, self.settings.recursive_scan)

        if not image_files:
            self.status_msg.emit("No image files found in folder.")
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
        if job.is_raw:
            preview_path = exiftool.extract_preview_jpeg(job.file_path, tmp_dir)
        else:
            preview_path = job.file_path   # JPEGs go straight to Ollama

        # Step 2: read existing metadata
        existing_caption = exiftool.read_existing_caption(job.file_path)
        existing_keywords = exiftool.read_existing_keywords(job.file_path)

        # Step 3: generate caption
        caption, keywords = generate_caption(image_path=preview_path, settings=s)

        # Step 4: write IPTC to original file
        amend = getattr(s, "caption_mode", "amend") == "amend"
        exiftool.write_iptc(
            file_path=job.file_path,
            caption=caption,
            keywords=keywords,
            artist_name=s.artist_name,
            copyright_notice=s.copyright_year_notice(),
            credit_line=s.credit_line,
            city=s.default_city,
            country=s.default_country,
            existing_caption=existing_caption if amend else None,
            existing_keywords=existing_keywords,
            append_separator=s.append_separator,
        )

        # If a sidecar JPG exists alongside a RAW, write to that too
        if job.is_raw:
            for ext in (".jpg", ".JPG", ".jpeg", ".JPEG"):
                sidecar = job.file_path.with_suffix(ext)
                if sidecar.exists():
                    sidecar_existing_caption = exiftool.read_existing_caption(sidecar)
                    sidecar_existing_kw = exiftool.read_existing_keywords(sidecar)
                    exiftool.write_iptc(
                        file_path=sidecar,
                        caption=caption,
                        keywords=keywords,
                        artist_name=s.artist_name,
                        copyright_notice=s.copyright_year_notice(),
                        credit_line=s.credit_line,
                        city=s.default_city,
                        country=s.default_country,
                        existing_caption=sidecar_existing_caption if amend else None,
                        existing_keywords=sidecar_existing_kw,
                        append_separator=s.append_separator,
                    )

        return caption, keywords
