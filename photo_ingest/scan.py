from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from photo_ingest.classify import Classifier, FileClass

log = logging.getLogger(__name__)


@dataclass
class SourceFile:
    relative_path: str      # relative to dump root, e.g. DCIM/100FUJI/DSCF0001.RAF
    file_name: str
    extension: str          # lowercased, no dot
    file_class: FileClass
    size_bytes: int
    mtime: datetime
    checksum: str = ""      # filled during manifest computation
    source_root: str = ""
    copied_to_nvme: bool = False
    copied_to_hdd: bool = False


@dataclass
class ScanResult:
    root: Path
    files: list[SourceFile] = field(default_factory=list)
    total_bytes: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    bytes_by_class: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.counts:
            self.counts = {c.value: 0 for c in FileClass}
        if not self.bytes_by_class:
            self.bytes_by_class = {c.value: 0 for c in FileClass}


def scan_source(root: Path, classifier: Classifier) -> ScanResult:
    """Recursively scan *root* and return a ScanResult with per-file metadata.

    Never modifies any file. Follows symlinks that stay within *root*.
    """
    result = ScanResult(root=root)
    log.info("Scanning source tree: %s", root)

    for path in sorted(root.rglob("*")):
        if not path.is_file(follow_symlinks=False):
            continue
        try:
            stat = path.stat()
        except OSError as exc:
            log.warning("Cannot stat %s: %s — skipping", path, exc)
            continue

        rel = path.relative_to(root)
        ext = path.suffix.lstrip(".").lower()
        file_class = classifier.classify(ext)
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

        sf = SourceFile(
            relative_path=str(rel),
            file_name=path.name,
            extension=ext,
            file_class=file_class,
            size_bytes=stat.st_size,
            mtime=mtime,
            source_root=str(root),
        )
        result.files.append(sf)
        result.total_bytes += stat.st_size
        result.counts[file_class.value] = result.counts.get(file_class.value, 0) + 1
        result.bytes_by_class[file_class.value] = (
            result.bytes_by_class.get(file_class.value, 0) + stat.st_size
        )

    log.info(
        "Scan complete: %d files, %.1f MiB  raw=%d photo=%d video=%d sidecar=%d other=%d",
        len(result.files),
        result.total_bytes / 1024 / 1024,
        result.counts.get("raw", 0),
        result.counts.get("photo", 0),
        result.counts.get("video", 0),
        result.counts.get("sidecar", 0),
        result.counts.get("other", 0),
    )
    return result


def write_tree_snapshot(root: Path, dest: Path) -> None:
    """Write a recursive file listing of *root* to *dest* (source_tree.txt)."""
    lines = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        marker = "/" if path.is_dir() else ""
        try:
            size = path.stat().st_size if path.is_file() else 0
        except OSError:
            size = 0
        lines.append(f"{rel}{marker}\t{size}")
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
