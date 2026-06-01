from __future__ import annotations

import csv
import hashlib
import logging
import os
import subprocess
from pathlib import Path

from photo_ingest.classify import Classifier, FileClass
from photo_ingest.config import Config
from photo_ingest.scan import SourceFile

log = logging.getLogger(__name__)

TSV_COLUMNS = [
    "relative_path",
    "file_name",
    "extension",
    "file_class",
    "size_bytes",
    "mtime",
    "checksum",
    "source_root",
    "copied_to_nvme",
    "copied_to_hdd",
]


def compute_checksums(
    root: Path,
    files: list[SourceFile],
    algorithm: str,
) -> dict[str, str]:
    """Compute checksums for every file under *root*. Returns {relative_path: checksum_hex}."""
    log.info("Computing %s checksums for %d files under %s", algorithm, len(files), root)
    results: dict[str, str] = {}

    if algorithm == "b3sum":
        results = _checksums_b3sum(root, files)
    else:
        results = _checksums_sha256(root, files)

    log.info("Checksums complete: %d files", len(results))
    return results


def write_checksums_file(
    root: Path,
    checksums: dict[str, str],
    ingest_dir: Path,
    algorithm: str,
) -> Path:
    """Write a standard sha256sum-format file to <ingest_dir>/checksums.sha256."""
    out_path = ingest_dir / "checksums.sha256"
    lines = []
    for rel, cksum in sorted(checksums.items()):
        lines.append(f"{cksum}  {rel}\n")
    out_path.write_text("".join(lines), encoding="utf-8")
    log.info("Wrote %s (%d entries)", out_path, len(checksums))
    return out_path


def write_manifest(
    files: list[SourceFile],
    ingest_dir: Path,
) -> Path:
    """Write file_manifest.tsv to *ingest_dir*."""
    out_path = ingest_dir / "file_manifest.tsv"
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=TSV_COLUMNS, delimiter="\t")
        writer.writeheader()
        for sf in files:
            writer.writerow({
                "relative_path": sf.relative_path,
                "file_name": sf.file_name,
                "extension": sf.extension,
                "file_class": sf.file_class.value,
                "size_bytes": sf.size_bytes,
                "mtime": sf.mtime.isoformat(),
                "checksum": sf.checksum,
                "source_root": sf.source_root,
                "copied_to_nvme": "1" if sf.copied_to_nvme else "0",
                "copied_to_hdd": "1" if sf.copied_to_hdd else "0",
            })
    log.info("Wrote %s (%d rows)", out_path, len(files))
    return out_path


def load_checksums_file(path: Path) -> dict[str, str]:
    """Parse a sha256sum-format file → {relative_path: hex}."""
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) == 2:
            cksum, rel_path = parts
            result[rel_path.lstrip("*").strip()] = cksum
    return result


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _checksums_sha256(root: Path, files: list[SourceFile]) -> dict[str, str]:
    results: dict[str, str] = {}
    for sf in files:
        path = root / sf.relative_path
        try:
            h = hashlib.sha256()
            with path.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            results[sf.relative_path] = h.hexdigest()
        except OSError as exc:
            log.error("Cannot checksum %s: %s", path, exc)
    return results


def _checksums_b3sum(root: Path, files: list[SourceFile]) -> dict[str, str]:
    """Use the b3sum binary for speed; fall back to Python sha256 if absent."""
    try:
        subprocess.run(["b3sum", "--version"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        log.warning("b3sum not found; falling back to sha256")
        return _checksums_sha256(root, files)

    paths = [str(root / sf.relative_path) for sf in files]
    result = subprocess.run(["b3sum", "--no-names", *paths], capture_output=True, text=True)
    if result.returncode != 0:
        log.warning("b3sum failed; falling back to sha256")
        return _checksums_sha256(root, files)

    results: dict[str, str] = {}
    for sf, line in zip(files, result.stdout.splitlines()):
        results[sf.relative_path] = line.strip()
    return results
