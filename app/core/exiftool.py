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


# ── Extracting / generating a JPEG from RAW ──────────────────────────────────

def _try_exiftool_extract(raw_path: Path, dest: Path) -> bool:
    """Try extracting embedded JPEG via exiftool stdout. Returns True on success."""
    for tag in ("-JpgFromRaw", "-PreviewImage", "-LargestImage"):
        result = subprocess.run(
            [_et(), "-b", tag, str(raw_path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
        )
        if result.returncode == 0 and len(result.stdout) > 10_000:
            dest.write_bytes(result.stdout)
            return True
    return False


def _try_sips(raw_path: Path, dest: Path, max_px: int = 1920) -> bool:
    """macOS sips: decode RAW data → JPEG, longest side ≤ max_px. Returns True on success."""
    try:
        r = subprocess.run(
            ["sips", "-s", "format", "jpeg", "-Z", str(max_px), str(raw_path), "--out", str(dest)],
            capture_output=True, text=True, timeout=120,
        )
        return r.returncode == 0 and dest.exists() and dest.stat().st_size > 10_000
    except FileNotFoundError:
        return False


def _try_dcraw(raw_path: Path, dest: Path) -> bool:
    """Linux fallback: dcraw → PPM piped through convert. Returns True on success."""
    try:
        dcraw = subprocess.run(
            ["dcraw", "-c", "-w", "-h", str(raw_path)],
            capture_output=True, timeout=120,
        )
        if dcraw.returncode != 0 or not dcraw.stdout:
            return False
        convert = subprocess.run(
            ["convert", "ppm:-", str(dest)],
            input=dcraw.stdout, capture_output=True, timeout=60,
        )
        return convert.returncode == 0 and dest.exists() and dest.stat().st_size > 10_000
    except FileNotFoundError:
        return False


def extract_preview_jpeg(raw_path: Path, dest_dir: Optional[Path] = None) -> Path:
    """
    Get a JPEG from a RAW file for AI processing.

    Strategy (in order):
      1. exiftool -JpgFromRaw / -PreviewImage / -LargestImage (fast, no decode)
      2. sips (macOS built-in RAW decoder, always works on macOS)
      3. dcraw + convert (Linux fallback, if both tools are installed)

    The returned JPEG is written to dest_dir and the caller is responsible
    for deleting it (or use a TemporaryDirectory context).
    """
    dest_dir = dest_dir or Path(tempfile.gettempdir()) / "photoai_previews"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{raw_path.stem}_preview.jpg"

    if _try_exiftool_extract(raw_path, dest):
        return dest
    if _try_sips(raw_path, dest):
        return dest
    if _try_dcraw(raw_path, dest):
        return dest

    raise RuntimeError(
        f"Could not generate a JPEG preview from {raw_path.name}. "
        f"On macOS this should always work via sips — verify the file is a valid RAW."
    )


# ── Writing ───────────────────────────────────────────────────────────────────

def write_iptc(
    file_path: Path,
    caption: str,
    keywords: List[str],
    artist_name: str = "",
    copyright_notice: str = "",
    credit_line: str = "",
    headline: str = "",
    source: str = "",
    instructions: str = "",
    job_identifier: str = "",
    alt_text: str = "",
    extended_description: str = "",
    city: str = "",
    state_province: str = "",
    sublocation: str = "",
    country: str = "",
    country_code: str = "",
    contact_email: str = "",
    contact_phone: str = "",
    contact_url: str = "",
    existing_caption: Optional[str] = None,
    existing_keywords: Optional[List[str]] = None,
    append_separator: str = "\n\n",
    ai_label: str = "[ai]",
) -> None:
    """
    Write IPTC and XMP metadata to a file in-place.

    Caption append logic:
      - ai_label (e.g. "[ai]") is appended to the AI caption first
      - If existing_caption is set → existing + append_separator + ai_caption
      - Otherwise → write ai_caption as-is

    Keyword merge:
      - Combines existing_keywords + new keywords, deduplicated, preserving order
    """
    # Apply optional signature label to the AI-generated portion only
    ai_caption = f"{caption} {ai_label}".strip() if ai_label else caption

    # Append after existing caption using the configured separator
    if existing_caption and existing_caption.strip():
        sep = append_separator if append_separator else "\n\n"
        final_caption = f"{existing_caption.strip()}{sep}{ai_caption}"
    else:
        final_caption = ai_caption

    # Build merged keywords (existing first, then new, deduped, case-insensitive)
    seen: set[str] = set()
    merged_kw: List[str] = []
    for kw in (existing_keywords or []) + keywords:
        lower = kw.lower().strip()
        if lower and lower not in seen:
            seen.add(lower)
            merged_kw.append(kw.strip())

    # Build exiftool command
    # -m: ignore minor errors (e.g. IPTC not supported in some RAW formats) so XMP tags still write
    cmd: List[str] = [
        _et(),
        "-overwrite_original",
        "-m",
        "-charset", "iptc=UTF8",
        f"-IPTC:Caption-Abstract={final_caption}",
        f"-XMP:Description={final_caption}",
    ]

    # Keywords — write to IPTC, XMP dc:subject, and XMP-lr:HierarchicalSubject
    # Repeating the same flag multiple times is the correct exiftool idiom for list tags.
    # XMP-dc:Subject is the dc:subject field that Lightroom, Bridge, and PM all read as "Keywords".
    for kw in merged_kw:
        cmd.append(f"-IPTC:Keywords={kw}")
        cmd.append(f"-XMP-dc:Subject={kw}")
        cmd.append(f"-XMP-lr:HierarchicalSubject={kw}")

    # Fixed identity fields
    if artist_name:
        cmd += [f"-IPTC:By-line={artist_name}", f"-XMP:Creator={artist_name}"]
    if copyright_notice:
        cmd += [f"-IPTC:CopyrightNotice={copyright_notice}", f"-XMP:Rights={copyright_notice}"]
    if credit_line:
        cmd.append(f"-IPTC:Credit={credit_line}")

    # Publication / stationery (always write if set)
    if headline:
        cmd += [f"-IPTC:Headline={headline}", f"-XMP-photoshop:Headline={headline}"]
    if source:
        cmd += [f"-IPTC:Source={source}", f"-XMP-photoshop:Source={source}"]
    if instructions:
        cmd += [f"-IPTC:SpecialInstructions={instructions}", f"-XMP-photoshop:Instructions={instructions}"]
    if job_identifier:
        cmd += [f"-IPTC:OriginalTransmissionReference={job_identifier}", f"-XMP-photoshop:TransmissionReference={job_identifier}"]

    # Accessibility fields (IPTC Photo Metadata 2021)
    # Alt text defaults to the AI caption if not explicitly set
    effective_alt = alt_text if alt_text else final_caption
    cmd.append(f"-XMP-iptcExt:AltTextAccessibility={effective_alt}")
    if extended_description:
        cmd.append(f"-XMP-iptcExt:ExtDescrAccessibility={extended_description}")

    # Contact info (always write if set)
    if contact_email:
        cmd.append(f"-XMP-iptcCore:CiEmailWork={contact_email}")
    if contact_phone:
        cmd.append(f"-XMP-iptcCore:CiTelWork={contact_phone}")
    if contact_url:
        cmd.append(f"-XMP-iptcCore:CiUrlWork={contact_url}")

    # Location defaults — only write if not already present
    existing_meta = read_iptc(file_path)
    if city and not existing_meta.get("City") and not existing_meta.get("IPTC:City"):
        cmd.append(f"-IPTC:City={city}")
    if state_province and not existing_meta.get("Province-State") and not existing_meta.get("IPTC:Province-State"):
        cmd.append(f"-IPTC:Province-State={state_province}")
    if sublocation and not existing_meta.get("Sub-location") and not existing_meta.get("IPTC:Sub-location"):
        cmd.append(f"-IPTC:Sub-location={sublocation}")
    if country and not existing_meta.get("Country-PrimaryLocationName") and not existing_meta.get("IPTC:Country-PrimaryLocationName"):
        cmd.append(f"-IPTC:Country-PrimaryLocationName={country}")
    if country_code and not existing_meta.get("Country-PrimaryLocationCode") and not existing_meta.get("IPTC:Country-PrimaryLocationCode"):
        cmd.append(f"-IPTC:Country-PrimaryLocationCode={country_code}")

    cmd.append(str(file_path))

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

    if result.returncode != 0:
        raise RuntimeError(f"exiftool write failed: {result.stderr.strip()}")
    if "1 image files updated" not in result.stdout:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"exiftool wrote 0 files to {file_path.name} — {detail}")


def restore_iptc(
    file_path: Path,
    original_caption: Optional[str],
    original_keywords: List[str],
) -> None:
    """
    Restore Caption-Abstract and Keywords to their pre-AI values.
    Pass original_caption=None to clear the caption entirely.
    Pass original_keywords=[] to clear all keywords.
    Also deletes any XMP sidecar written by the app.
    """
    cmd: List[str] = [_et(), "-overwrite_original", "-m", "-charset", "iptc=UTF8"]

    caption_val = original_caption.strip() if original_caption else ""
    cmd += [
        f"-IPTC:Caption-Abstract={caption_val}",
        f"-XMP:Description={caption_val}",
    ]

    # Restore keywords — must mirror every field that write_iptc touches
    if original_keywords:
        for kw in original_keywords:
            cmd += [
                f"-IPTC:Keywords={kw}",
                f"-XMP-dc:Subject={kw}",
                f"-XMP-lr:HierarchicalSubject={kw}",
            ]
    else:
        # Delete all keyword fields entirely (empty = clears the list tag)
        cmd += [
            "-IPTC:Keywords=",
            "-XMP-dc:Subject=",
            "-XMP-lr:HierarchicalSubject=",
        ]

    cmd.append(str(file_path))
    subprocess.run(cmd, capture_output=True, text=True, timeout=60)

    # Remove the XMP sidecar the app created (RAW files only)
    sidecar = file_path.with_suffix(".xmp")
    if sidecar.exists():
        sidecar.unlink(missing_ok=True)


def write_xmp_sidecar(
    raw_path: Path,
    caption: str,
    keywords: List[str],
    artist: str = "",
    copyright_notice: str = "",
) -> Path:
    """
    Write a Photo Mechanic / Lightroom-compatible XMP sidecar alongside a RAW file.
    Returns the sidecar path. Overwrites any existing sidecar.

    Uses exiftool to generate the XMP so the namespace layout, rdf:Alt / rdf:Bag
    structure, and xpacket encoding are guaranteed to match what PM expects.

    Photo Mechanic reads sidecar .xmp files instantly without needing Cmd+R,
    unlike embedded RAW XMP which requires a manual metadata refresh.
    """
    sidecar = raw_path.with_suffix(".xmp")

    # Seed an empty but valid XMP file so exiftool has something to update.
    # exiftool cannot create a standalone .xmp from nothing — it needs an existing file.
    if not sidecar.exists():
        sidecar.write_text(
            "<?xpacket begin='\ufeff' id='W5M0MpCehiHzreSzNTczkc9d'?>"
            "<x:xmpmeta xmlns:x='adobe:ns:meta/'>"
            "<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'/>"
            "</x:xmpmeta>"
            "<?xpacket end='w'?>",
            encoding="utf-8",
        )

    # Build the exiftool command targeting the sidecar path directly.
    cmd: List[str] = [
        _et(),
        "-overwrite_original",
        "-charset", "iptc=UTF8",
        # Caption → dc:description (PM "Caption" field)
        f"-XMP-dc:Description={caption}",
        # Copyright → dc:rights + xmpRights:Marked (PM "Copyright" field)
    ]

    if copyright_notice:
        cmd += [
            f"-XMP-dc:Rights={copyright_notice}",
            "-XMP-xmpRights:Marked=True",
        ]

    if artist:
        cmd.append(f"-XMP-dc:Creator={artist}")

    # Keywords → dc:subject (PM "Keywords" field)
    for kw in keywords:
        cmd.append(f"-XMP-dc:Subject={kw}")

    cmd.append(str(sidecar))

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"exiftool sidecar write failed: {result.stderr.strip()}")

    return sidecar


def verify_write(file_path: Path) -> Dict[str, Any]:
    """Read back IPTC and XMP after write — confirms data persisted in either namespace."""
    result = subprocess.run(
        [_et(), "-json", "-IPTC:all", "-XMP:all", "-charset", "iptc=UTF8", str(file_path)],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0 or not result.stdout.strip():
        return {}
    try:
        data = json.loads(result.stdout)
        return data[0] if data else {}
    except (json.JSONDecodeError, IndexError):
        return {}
