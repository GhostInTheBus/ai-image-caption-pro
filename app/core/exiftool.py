"""
ExifTool wrapper for reading and writing IPTC/XMP metadata.

Requires exiftool to be installed or bundled at bin/exiftool.
Falls back to system `exiftool` if the bundled binary is not present.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Binary resolution ─────────────────────────────────────────────────────────

def _find_exiftool() -> str:
    """Find exiftool: bundled binary first, then system PATH."""
    # Look for bundled binary next to this file's package root
    project_root = Path(__file__).parent.parent.parent
    candidates = [
        project_root / "bin" / "exiftool",
        project_root / "bin" / "exiftool.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    # Fall back to system exiftool
    found = shutil.which("exiftool")
    if found:
        return found
    raise FileNotFoundError(
        "exiftool not found. Install it (brew install exiftool / apt install libimage-exiftool-perl) "
        "or place the binary at bin/exiftool."
    )


EXIFTOOL_BIN: str = ""   # resolved lazily on first use


def _et() -> str:
    global EXIFTOOL_BIN
    if not EXIFTOOL_BIN:
        EXIFTOOL_BIN = _find_exiftool()
    return EXIFTOOL_BIN


# ── Reading ───────────────────────────────────────────────────────────────────

def read_iptc(file_path: Path) -> Dict[str, Any]:
    """
    Read all IPTC and XMP metadata from a file.
    Returns a flat dict of tag → value (ExifTool JSON format).
    """
    result = subprocess.run(
        [_et(), "-json", "-IPTC:all", "-XMP:all", "-charset", "iptc=UTF8", str(file_path)],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(f"exiftool read failed: {result.stderr.strip()}")
    data = json.loads(result.stdout)
    return data[0] if data else {}


def read_existing_caption(file_path: Path) -> Optional[str]:
    """Return the existing IPTC Caption-Abstract if present, else None."""
    meta = read_iptc(file_path)
    return meta.get("Caption-Abstract") or meta.get("IPTC:Caption-Abstract")


def read_existing_keywords(file_path: Path) -> List[str]:
    """Return existing IPTC Keywords as a list."""
    meta = read_iptc(file_path)
    kw = meta.get("Keywords") or meta.get("IPTC:Keywords") or []
    if isinstance(kw, str):
        kw = [kw]
    return kw


# ── Extracting embedded JPEG from RAW ─────────────────────────────────────────

def extract_preview_jpeg(raw_path: Path, dest_dir: Optional[Path] = None) -> Path:
    """
    Extract the embedded JPEG preview from a RAW file.
    Returns the path to the extracted JPEG.

    Strategy:
      1. Try -JpgFromRaw (Canon CR3, Nikon NEF, etc.)
      2. Fall back to -PreviewImage (Sony ARW, others)
    Raises RuntimeError if neither works.
    """
    dest_dir = dest_dir or Path(tempfile.gettempdir()) / "photoai_previews"
    dest_dir.mkdir(parents=True, exist_ok=True)

    stem = raw_path.stem
    dest = dest_dir / f"{stem}_preview.jpg"

    # Try JpgFromRaw first
    for tag in ("-JpgFromRaw", "-PreviewImage"):
        result = subprocess.run(
            [_et(), "-b", tag, "-w!", str(dest), str(raw_path)],
            capture_output=True, text=True, timeout=60
        )
        if dest.exists() and dest.stat().st_size > 1000:
            return dest
        if dest.exists():
            dest.unlink()

    # Last resort: extract largest embedded image
    result = subprocess.run(
        [_et(), "-b", "-LargestImage", "-w!", str(dest), str(raw_path)],
        capture_output=True, text=True, timeout=60
    )
    if dest.exists() and dest.stat().st_size > 1000:
        return dest

    raise RuntimeError(
        f"Could not extract preview JPEG from {raw_path.name}. "
        f"exiftool stderr: {result.stderr.strip()}"
    )


# ── Writing ───────────────────────────────────────────────────────────────────

def write_iptc(
    file_path: Path,
    caption: str,
    keywords: List[str],
    artist_name: str = "",
    copyright_notice: str = "",
    credit_line: str = "",
    city: str = "",
    country: str = "",
    existing_caption: Optional[str] = None,
    existing_keywords: Optional[List[str]] = None,
    append_separator: str = "\n\n",
) -> None:
    """
    Write IPTC and XMP metadata to a file in-place.

    Caption append logic:
      - If existing_caption is set → append with separator
      - Otherwise → write caption as-is

    Keyword merge:
      - Combines existing_keywords + new keywords, deduplicated, preserving order
    """
    # Build final caption
    if existing_caption and existing_caption.strip():
        final_caption = f"{existing_caption.strip()}{append_separator}{caption}"
    else:
        final_caption = caption

    # Build merged keywords (existing first, then new, deduped, case-insensitive)
    seen: set[str] = set()
    merged_kw: List[str] = []
    for kw in (existing_keywords or []) + keywords:
        lower = kw.lower().strip()
        if lower and lower not in seen:
            seen.add(lower)
            merged_kw.append(kw.strip())

    # Build exiftool command
    cmd: List[str] = [
        _et(),
        "-overwrite_original",
        "-charset", "iptc=UTF8",
        f"-IPTC:Caption-Abstract={final_caption}",
        f"-XMP:Description={final_caption}",
    ]

    # Keywords — each as a separate flag
    for kw in merged_kw:
        cmd.append(f"-IPTC:Keywords={kw}")
        cmd.append(f"-XMP:Subject={kw}")

    # Fixed identity fields
    if artist_name:
        cmd += [f"-IPTC:By-line={artist_name}", f"-XMP:Creator={artist_name}"]
    if copyright_notice:
        cmd += [f"-IPTC:CopyrightNotice={copyright_notice}", f"-XMP:Rights={copyright_notice}"]
    if credit_line:
        cmd.append(f"-IPTC:Credit={credit_line}")

    # Location defaults — only write if not already present
    existing_meta = read_iptc(file_path)
    if city and not existing_meta.get("City") and not existing_meta.get("IPTC:City"):
        cmd.append(f"-IPTC:City={city}")
    if country and not existing_meta.get("Country-PrimaryLocationName") and not existing_meta.get("IPTC:Country-PrimaryLocationName"):
        cmd.append(f"-IPTC:Country-PrimaryLocationName={country}")

    cmd.append(str(file_path))

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"exiftool write failed: {result.stderr.strip()}")


def verify_write(file_path: Path) -> Dict[str, Any]:
    """Read back IPTC after write — used for verification/logging."""
    return read_iptc(file_path)
