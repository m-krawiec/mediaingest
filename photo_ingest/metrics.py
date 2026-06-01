from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from photo_ingest.config import Config

log = logging.getLogger(__name__)

_VERIFY_STATUS_CODES = {
    "ok": 1,
    "count_mismatch": 2,
    "size_mismatch": 3,
    "checksum_mismatch": 4,
    "skipped": 0,
}


def write_metrics(
    data: dict[str, Any],
    ingest_dir: Path,
    cfg: Config,
    import_id: str,
) -> None:
    """Write per-import metrics.prom and update the roll-up textfile-collector file."""
    content = _render(data)

    if cfg.metrics.write_per_import:
        per_import = ingest_dir / "metrics.prom"
        _atomic_write(per_import, content)
        log.debug("Wrote per-import metrics: %s", per_import)

    collector_dir = cfg.metrics.textfile_dir
    if collector_dir and _dir_is_writable(collector_dir):
        rollup = collector_dir / "photo_ingest.prom"
        _atomic_write(rollup, content)
        log.info("Updated textfile collector: %s", rollup)
    else:
        log.debug(
            "Textfile collector dir not writable or not set (%s); skipping roll-up",
            collector_dir,
        )


def _render(data: dict[str, Any]) -> str:
    lines: list[str] = []

    def gauge(name: str, value: Any, help_text: str = "") -> None:
        if help_text:
            lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")
        lines.append(f"{name} {value}")

    def counter(name: str, value: Any, help_text: str = "") -> None:
        if help_text:
            lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} counter")
        lines.append(f"{name} {value}")

    gauge("photo_ingest_active", data.get("active", 0),
          "1 while an ingest is running, else 0")
    gauge("photo_ingest_last_success_timestamp", data.get("last_success_ts", 0),
          "Unix timestamp of last verified ingest")
    gauge("photo_ingest_last_failure_timestamp", data.get("last_failure_ts", 0),
          "Unix timestamp of last failed ingest")
    gauge("photo_ingest_duration_seconds", data.get("duration_seconds", 0),
          "Duration of the last ingest in seconds")
    gauge("photo_ingest_source_bytes", data.get("source_bytes", 0),
          "Total bytes on source card")
    counter("photo_ingest_copied_bytes_total", data.get("copied_bytes", 0),
            "Total bytes copied (last run)")
    gauge("photo_ingest_files_total", data.get("files_total", 0),
          "Total files on source (last run)")

    for cls in ("raw", "photo", "video", "sidecar", "other"):
        gauge(f"photo_ingest_{cls}_files_total", data.get(f"{cls}_files", 0))
        gauge(f"photo_ingest_{cls}_bytes", data.get(f"{cls}_bytes", 0))

    counter("photo_ingest_errors_total", data.get("errors_total", 0),
            "Total errors in last run")
    gauge("photo_ingest_verification_status",
          _VERIFY_STATUS_CODES.get(data.get("verification_status", "skipped"), 0),
          "0=skipped 1=ok 2=count_mismatch 3=size_mismatch 4=checksum_mismatch")
    counter("photo_ingest_runs_total", data.get("runs_total", 0),
            "Total ingest runs since installation")

    lines.append("")  # trailing newline for textfile collector
    return "\n".join(lines)


def _atomic_write(path: Path, content: str) -> None:
    """Write *content* to *path* atomically (temp file + rename)."""
    dir_ = path.parent
    dir_.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".prom.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _dir_is_writable(path: Path) -> bool:
    return path.is_dir() and os.access(path, os.W_OK)
