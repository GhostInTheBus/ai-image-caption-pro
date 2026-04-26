"""
SQLite-backed job tracker for crash-safe batch processing.

Schema uses a simple state machine:
  pending → running → done
                    → error

On restart, any 'running' jobs are reset to 'pending' (they were interrupted).
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator, List, Optional

from app.models import BatchJob, ImageJob, JobStatus

DB_PATH = Path.home() / ".photoai" / "jobs.db"


def _ensure_db_dir() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def _conn() -> Generator[sqlite3.Connection, None, None]:
    _ensure_db_dir()
    con = sqlite3.connect(str(DB_PATH), detect_types=sqlite3.PARSE_DECLTYPES)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")   # safe concurrent writes
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_db() -> None:
    """Create tables if they don't exist."""
    with _conn() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS batches (
                batch_id    TEXT PRIMARY KEY,
                folder_path TEXT NOT NULL,
                total       INTEGER DEFAULT 0,
                created_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS jobs (
                job_id      TEXT PRIMARY KEY,
                file_path   TEXT NOT NULL,
                batch_id    TEXT NOT NULL,
                status      TEXT DEFAULT 'pending',
                error_msg   TEXT,
                created_at  TEXT DEFAULT (datetime('now')),
                updated_at  TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (batch_id) REFERENCES batches(batch_id)
            );

            CREATE INDEX IF NOT EXISTS idx_jobs_batch   ON jobs(batch_id);
            CREATE INDEX IF NOT EXISTS idx_jobs_status  ON jobs(status);
        """)


def create_batch(batch: BatchJob, jobs: List[ImageJob]) -> None:
    """Insert a new batch and all its pending jobs atomically."""
    with _conn() as con:
        con.execute(
            "INSERT OR IGNORE INTO batches (batch_id, folder_path, total) VALUES (?,?,?)",
            (batch.batch_id, str(batch.folder_path), len(jobs))
        )
        con.executemany(
            """INSERT OR IGNORE INTO jobs
               (job_id, file_path, batch_id, status)
               VALUES (?,?,?,'pending')""",
            [(j.job_id, str(j.file_path), j.batch_id) for j in jobs]
        )


def get_pending_jobs(batch_id: str) -> List[ImageJob]:
    """Return all pending jobs for a batch (used for initial run + resume)."""
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM jobs WHERE batch_id=? AND status='pending' ORDER BY file_path",
            (batch_id,)
        ).fetchall()
    return [_row_to_job(r) for r in rows]


def get_all_incomplete_batches() -> List[str]:
    """Return batch IDs that have pending jobs — used for auto-resume on launch."""
    with _conn() as con:
        rows = con.execute("""
            SELECT DISTINCT batch_id FROM jobs WHERE status IN ('pending','running')
        """).fetchall()
    return [r["batch_id"] for r in rows]


def get_batch_folder(batch_id: str) -> Optional[Path]:
    with _conn() as con:
        row = con.execute(
            "SELECT folder_path FROM batches WHERE batch_id=?", (batch_id,)
        ).fetchone()
    return Path(row["folder_path"]) if row else None


def mark_running(job_id: str) -> None:
    _update_status(job_id, "running")


def mark_done(job_id: str) -> None:
    _update_status(job_id, "done")


def mark_error(job_id: str, msg: str) -> None:
    with _conn() as con:
        con.execute(
            "UPDATE jobs SET status='error', error_msg=?, updated_at=? WHERE job_id=?",
            (msg, _now(), job_id)
        )


def mark_skipped(job_id: str) -> None:
    _update_status(job_id, "skipped")


def is_done(job_id: str) -> bool:
    """Check if a specific job is already marked done (skip on re-drop)."""
    with _conn() as con:
        row = con.execute(
            "SELECT status FROM jobs WHERE job_id=?", (job_id,)
        ).fetchone()
    return row is not None and row["status"] == "done"


def reset_batch_for_reprocess(batch_id: str) -> int:
    """Reset all done/error jobs in a batch back to pending for reprocessing."""
    with _conn() as con:
        cur = con.execute(
            "UPDATE jobs SET status='pending', error_msg=NULL, updated_at=? WHERE batch_id=?",
            (_now(), batch_id)
        )
        return cur.rowcount


def reset_interrupted_jobs() -> int:
    """
    On startup: any job stuck in 'running' was interrupted by a crash.
    Reset to 'pending' so it gets retried.
    Returns count of jobs reset.
    """
    with _conn() as con:
        cur = con.execute(
            "UPDATE jobs SET status='pending', updated_at=? WHERE status='running'",
            (_now(),)
        )
        return cur.rowcount


def get_recent_batches(limit: int = 15) -> list[dict]:
    """Return recent batches with per-status counts for the log view."""
    with _conn() as con:
        rows = con.execute("""
            SELECT
                b.folder_path,
                b.created_at,
                SUM(j.status='done')    AS done,
                SUM(j.status='error')   AS errors,
                SUM(j.status='pending') AS pending,
                SUM(j.status='skipped') AS skipped
            FROM batches b
            LEFT JOIN jobs j ON j.batch_id = b.batch_id
            GROUP BY b.batch_id
            ORDER BY b.created_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def clear_all_jobs() -> int:
    """Delete the entire job history."""
    with _conn() as con:
        cur = con.execute("DELETE FROM jobs")
        con.execute("DELETE FROM batches")
        return cur.rowcount


def clear_incomplete_jobs() -> int:
    """Delete all pending/running/error jobs so they can be reprocessed."""
    with _conn() as con:
        cur = con.execute(
            "DELETE FROM jobs WHERE status IN ('pending', 'running', 'error')"
        )
        con.execute("""
            DELETE FROM batches WHERE batch_id NOT IN (
                SELECT DISTINCT batch_id FROM jobs
            )
        """)
        return cur.rowcount


def get_batch_stats(batch_id: str) -> dict:
    with _conn() as con:
        row = con.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(status='done')    AS done,
                SUM(status='error')   AS errors,
                SUM(status='pending') AS pending,
                SUM(status='running') AS running,
                SUM(status='skipped') AS skipped
            FROM jobs WHERE batch_id=?
        """, (batch_id,)).fetchone()
    return dict(row) if row else {}


# ── helpers ──────────────────────────────────────────────────────────────────

def _update_status(job_id: str, status: str) -> None:
    with _conn() as con:
        con.execute(
            "UPDATE jobs SET status=?, updated_at=? WHERE job_id=?",
            (status, _now(), job_id)
        )


def _now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def _row_to_job(row: sqlite3.Row) -> ImageJob:
    return ImageJob(
        file_path=Path(row["file_path"]),
        batch_id=row["batch_id"],
        status=JobStatus(row["status"]),
        error_msg=row["error_msg"],
    )
