from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from photo_ingest.config import Config
from photo_ingest.errors import CopyError, DestError

log = logging.getLogger(__name__)


def check_free_space(destination: Path, required_bytes: int, safety_factor: float) -> None:
    """Raise DestError if *destination*'s filesystem lacks space for the copy."""
    needed = int(required_bytes * safety_factor)
    try:
        usage = shutil.disk_usage(destination)
        free = usage.free
    except OSError as exc:
        raise DestError(f"Cannot check free space on {destination}: {exc}") from exc

    if free < needed:
        raise DestError(
            f"Not enough free space on {destination}: "
            f"need {needed / 1024**3:.1f} GiB, have {free / 1024**3:.1f} GiB"
        )
    log.debug(
        "Free space check OK: need %.1f GiB, have %.1f GiB on %s",
        needed / 1024**3, free / 1024**3, destination,
    )


def rsync_copy(
    src: Path,
    dst: Path,
    log_path: Path,
    cfg: Config,
    resume: bool = False,
    dry_run: bool = False,
) -> None:
    """Run rsync src/ → dst/ and write the full log to *log_path*.

    Raises CopyError on non-zero rsync exit.
    Never passes --delete (would be catastrophic if src/dst are confused).
    Always passes --partial (enables --resume).
    """
    dst.mkdir(parents=True, exist_ok=True)

    cmd = [
        "rsync",
        *cfg.ingest.rsync_extra_args,
        "--partial",
        "--log-file", str(log_path),
    ]
    if dry_run:
        cmd.append("--dry-run")

    # Ensure trailing slash on src so rsync copies contents, not the directory itself.
    src_str = str(src).rstrip("/") + "/"
    cmd += [src_str, str(dst)]

    log.info("rsync: %s → %s%s", src, dst, " [dry-run]" if dry_run else "")
    log.debug("rsync cmd: %s", cmd)

    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        raise CopyError(
            f"rsync exited {result.returncode} copying {src} → {dst}. "
            f"See {log_path} for details."
        )
    log.info("rsync complete: %s → %s", src, dst)
