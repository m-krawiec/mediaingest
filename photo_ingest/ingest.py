from __future__ import annotations

import json
import logging
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from photo_ingest.classify import Classifier
from photo_ingest.config import Config
from photo_ingest.copy import check_free_space, rsync_copy
from photo_ingest.device import DeviceInfo, lsblk_snapshot, mounted_readonly, validate_device
from photo_ingest.errors import ConfigError, ConflictError, IngestError, SourceError
from photo_ingest.events import EventEmitter
from photo_ingest.manifest import (
    compute_checksums,
    write_checksums_file,
    write_manifest,
)
from photo_ingest.metrics import write_metrics
from photo_ingest.scan import ScanResult, scan_source, write_tree_snapshot
from photo_ingest.verify import verify, write_verification_json

log = logging.getLogger(__name__)


@dataclass
class IngestArgs:
    # Exactly one of source_device or source_path must be set.
    source_device: str | None = None   # block device: tool mounts it itself
    source_path: str | None = None     # pre-mounted directory: no mount needed (Docker)
    camera: str | None = None
    import_id: str | None = None
    copy_mode: str | None = None       # overrides config if set
    resume: bool = False
    auto_seq: bool = False
    dry_run: bool = False

    def __post_init__(self) -> None:
        if not self.source_device and not self.source_path:
            raise ConfigError("Either --source-device or --source-path must be provided.")
        if self.source_device and self.source_path:
            raise ConfigError("--source-device and --source-path are mutually exclusive.")

    @property
    def source_label(self) -> str:
        return self.source_device or self.source_path or ""


@dataclass
class IngestRun:
    import_id: str
    args: IngestArgs
    cfg: Config
    status: str = "pending"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    device_info: DeviceInfo | None = None
    scan: ScanResult | None = None
    nvme_dest: Path | None = None
    hdd_dest: Path | None = None
    nvme_ingest_dir: Path | None = None
    hdd_ingest_dir: Path | None = None
    errors: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)
    verification_status: str = "skipped"

    def add_error(self, stage: str, message: str) -> None:
        self.errors.append({"stage": stage, "message": message})
        log.error("[%s] %s", stage, message)

    def add_warning(self, stage: str, message: str) -> None:
        self.warnings.append({"stage": stage, "message": message})
        log.warning("[%s] %s", stage, message)

    def to_dict(self) -> dict[str, Any]:
        sc = self.scan
        dv = self.device_info
        return {
            "import_id": self.import_id,
            "schema_version": 1,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "status": self.status,
            "copy_mode": self.args.copy_mode or self.cfg.ingest.copy_mode,
            "source_device": self.args.source_label,
            "source_label": dv.label if dv else "",
            "source_uuid": dv.uuid if dv else "",
            "source_filesystem": dv.filesystem if dv else "",
            "source_read_only": self.cfg.ingest.mount_read_only,
            "source_files_count": len(sc.files) if sc else 0,
            "source_bytes": sc.total_bytes if sc else 0,
            "nvme_destination": str(self.nvme_dest) if self.nvme_dest else "",
            "hdd_destination": str(self.hdd_dest) if self.hdd_dest else "",
            "copied_files_count": len(sc.files) if sc else 0,
            "copied_bytes": sc.total_bytes if sc else 0,
            "checksum_algorithm": self.cfg.verify.checksum_algorithm,
            "verification_status": self.verification_status,
            "raw_files_count": sc.counts.get("raw", 0) if sc else 0,
            "photo_files_count": sc.counts.get("photo", 0) if sc else 0,
            "video_files_count": sc.counts.get("video", 0) if sc else 0,
            "sidecar_files_count": sc.counts.get("sidecar", 0) if sc else 0,
            "other_files_count": sc.counts.get("other", 0) if sc else 0,
            "raw_bytes": sc.bytes_by_class.get("raw", 0) if sc else 0,
            "photo_bytes": sc.bytes_by_class.get("photo", 0) if sc else 0,
            "video_bytes": sc.bytes_by_class.get("video", 0) if sc else 0,
            "sidecar_bytes": sc.bytes_by_class.get("sidecar", 0) if sc else 0,
            "other_bytes": sc.bytes_by_class.get("other", 0) if sc else 0,
            "errors": self.errors,
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run(args: IngestArgs, cfg: Config) -> IngestRun:
    """Execute a full ingest run. Returns the IngestRun state.
    Raises IngestError subclasses on fatal errors.
    """
    copy_mode = args.copy_mode or cfg.ingest.copy_mode

    # 1. Resolve source — either validate+mount a block device, or use a pre-mounted path.
    with _source_context(args, cfg) as (mountpoint, device_info):

        # 2. Generate import_id (needs device_info for card label)
        import_id = args.import_id or _generate_import_id(
            camera=args.camera or cfg.ingest.default_camera,
            card_label=device_info.safe_label,
            cfg=cfg,
            auto_seq=args.auto_seq,
        )

        # 3. Resolve dest paths
        nvme_dest = cfg.storage.nvme_inbox / import_id
        hdd_dest = cfg.storage.hdd_imports / import_id
        nvme_ingest_dir = nvme_dest / "_ingest"
        hdd_ingest_dir = hdd_dest / "_ingest"

        # 4. Conflict check
        _check_conflict(import_id, nvme_dest, hdd_dest, args.resume)

        run_state = IngestRun(
            import_id=import_id,
            args=args,
            cfg=cfg,
            nvme_dest=nvme_dest,
            hdd_dest=hdd_dest,
            nvme_ingest_dir=nvme_ingest_dir,
            hdd_ingest_dir=hdd_ingest_dir,
            device_info=device_info,
        )

        # 5. Create directories
        if not args.dry_run:
            nvme_ingest_dir.mkdir(parents=True, exist_ok=True)
            hdd_ingest_dir.mkdir(parents=True, exist_ok=True)

        emitter = EventEmitter(nvme_ingest_dir, import_id, dry_run=args.dry_run)
        file_handler = _setup_file_logging(nvme_ingest_dir, args.dry_run)

        run_state.status = "running"
        run_state.started_at = datetime.now(tz=timezone.utc)
        start_ts = time.monotonic()

        emitter.emit("ingest_started", {
            "source": args.source_label,
            "copy_mode": copy_mode,
            "dry_run": args.dry_run,
            "resume": args.resume,
        })
        _write_ingest_json(run_state, nvme_ingest_dir, args.dry_run)

        try:
            emitter.emit("source_mounted", {"mountpoint": str(mountpoint)})

            # Write lsblk snapshot (only meaningful for block devices)
            if not args.dry_run and args.source_device:
                (nvme_ingest_dir / "source_lsblk.txt").write_text(
                    lsblk_snapshot(args.source_device), encoding="utf-8"
                )

            # 6. Determine source root within the mountpoint
            if copy_mode == "dcim":
                source_root = mountpoint / "DCIM"
                if not source_root.is_dir():
                    raise SourceError(
                        f"No DCIM directory found under {mountpoint}. "
                        "Use --copy-mode full-card to copy the entire card."
                    )
            else:
                source_root = mountpoint

            emitter.emit("source_detected", {
                "source_root": str(source_root),
                "copy_mode": copy_mode,
            })

            # 7. Scan
            classifier = Classifier(cfg.classification)
            scan_result = scan_source(source_root, classifier)
            run_state.scan = scan_result
            if not args.dry_run:
                write_tree_snapshot(source_root, nvme_ingest_dir / "source_tree.txt")

            emitter.emit("source_scanned", {
                "files": len(scan_result.files),
                "bytes": scan_result.total_bytes,
            })
            emitter.emit("file_classification_finished", {
                k: v for k, v in scan_result.counts.items()
            })

            if args.dry_run:
                log.info(
                    "[dry-run] Would copy %d files (%.1f MiB) from %s",
                    len(scan_result.files),
                    scan_result.total_bytes / 1024 / 1024,
                    source_root,
                )
                run_state.status = "completed"
                return run_state

            # 8. Free space check
            check_free_space(
                cfg.storage.nvme_inbox,
                scan_result.total_bytes,
                cfg.ingest.free_space_safety_factor,
            )
            check_free_space(
                cfg.storage.hdd_imports,
                scan_result.total_bytes,
                cfg.ingest.free_space_safety_factor,
            )

            # 9. rsync source → NVMe
            dest_subdir = "DCIM" if copy_mode == "dcim" else "_card"
            nvme_copy_root = nvme_dest / dest_subdir
            hdd_copy_root = hdd_dest / dest_subdir

            emitter.emit("copy_to_nvme_started")
            rsync_copy(
                source_root,
                nvme_copy_root,
                nvme_ingest_dir / "rsync_to_nvme.log",
                cfg,
                resume=args.resume,
            )
            for sf in scan_result.files:
                sf.copied_to_nvme = True
            emitter.emit("copy_to_nvme_finished",
                         {"files": len(scan_result.files), "bytes": scan_result.total_bytes})

            # 10. Checksums on NVMe copy
            emitter.emit("checksum_started", {"algorithm": cfg.verify.checksum_algorithm})
            checksums = compute_checksums(
                nvme_copy_root, scan_result.files, cfg.verify.checksum_algorithm
            )
            cksum_map = {sf.relative_path: sf for sf in scan_result.files}
            for rel, cksum in checksums.items():
                if rel in cksum_map:
                    cksum_map[rel].checksum = cksum
            write_checksums_file(nvme_copy_root, checksums, nvme_ingest_dir,
                                 cfg.verify.checksum_algorithm)
            emitter.emit("checksum_finished", {"files": len(checksums)})

            write_manifest(scan_result.files, nvme_ingest_dir)

            # 11. rsync NVMe → HDD (copies whole import dir incl. _ingest/ artifacts)
            emitter.emit("copy_to_hdd_started")
            rsync_copy(
                nvme_dest,
                hdd_dest,
                nvme_ingest_dir / "rsync_to_hdd.log",
                cfg,
                resume=args.resume,
            )
            for sf in scan_result.files:
                sf.copied_to_hdd = True
            emitter.emit("copy_to_hdd_finished",
                         {"files": len(scan_result.files), "bytes": scan_result.total_bytes})

            # 12. Verify
            emitter.emit("verification_started")
            vresult = verify(
                scan_result.files,
                nvme_copy_root,
                hdd_copy_root,
                nvme_ingest_dir,
                cfg.verify,
            )
            run_state.verification_status = vresult.status
            write_verification_json(vresult, nvme_ingest_dir)
            emitter.emit("verification_finished", {"status": vresult.status})

            if vresult.status != "ok":
                run_state.add_error("verify", f"Verification failed: {vresult.status}")

        except IngestError:
            _handle_failure(run_state, nvme_ingest_dir, emitter, args.dry_run)
            raise
        except Exception as exc:
            run_state.add_error("unexpected", str(exc))
            _handle_failure(run_state, nvme_ingest_dir, emitter, args.dry_run)
            raise
        finally:
            emitter.close()
            if file_handler:
                logging.getLogger().removeHandler(file_handler)
                file_handler.close()

    # --- source unmounted / context exited here ---

    # 13. Final status + artifacts
    run_state.status = "verified" if vresult.status == "ok" else "failed"
    run_state.finished_at = datetime.now(tz=timezone.utc)
    duration = time.monotonic() - start_ts

    _write_ingest_json(run_state, nvme_ingest_dir, args.dry_run)
    _sync_ingest_dir_to_hdd(nvme_ingest_dir, hdd_ingest_dir)
    _write_run_metrics(run_state, nvme_ingest_dir, cfg, duration)

    log.info(
        "Ingest %s: status=%s, %d files, %.1f MiB, %.0fs",
        import_id, run_state.status,
        len(scan_result.files),
        scan_result.total_bytes / 1024 / 1024,
        duration,
    )
    return run_state


# ---------------------------------------------------------------------------
# Source context: block device mount OR pre-mounted path
# ---------------------------------------------------------------------------

@contextmanager
def _source_context(
    args: IngestArgs,
    cfg: Config,
) -> Iterator[tuple[Path, DeviceInfo]]:
    """Yield (source_mountpoint, device_info).

    --source-path (Docker / pre-mounted): no device validation or mounting.
    --source-device (native): validate the block device, mount it read-only.
    """
    if args.source_path:
        path = Path(args.source_path)
        if not path.is_dir():
            raise SourceError(
                f"--source-path {path} does not exist or is not a directory. "
                "Mount the SD card on the host before running the container."
            )
        log.info("Using pre-mounted source path: %s", path)
        # No filesystem label/uuid available without lsblk; use path stem as label.
        info = DeviceInfo(device=str(path), disk="", label=path.name)
        yield path, info
    else:
        assert args.source_device
        device_info = validate_device(args.source_device, cfg.ingest)
        with mounted_readonly(args.source_device, cfg.ingest, log) as mountpoint:
            yield mountpoint, device_info


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_import_id(
    camera: str,
    card_label: str,
    cfg: Config,
    auto_seq: bool,
) -> str:
    date_str = datetime.now().strftime(cfg.ingest.date_format)
    camera_slug = _slugify(camera)
    seq = 1

    while True:
        seq_str = f"{seq:03d}"
        import_id = (
            cfg.ingest.import_id_template
            .replace("{date}", date_str)
            .replace("{camera}", camera_slug)
            .replace("{cardlabel}", card_label)
            .replace("{seq}", seq_str)
        )
        nvme = cfg.storage.nvme_inbox / import_id
        hdd = cfg.storage.hdd_imports / import_id
        if not nvme.exists() and not hdd.exists():
            return import_id
        if not auto_seq:
            return import_id  # conflict handled by _check_conflict
        seq += 1
        if seq > 999:
            raise IngestError("Could not find a free import_id up to sequence 999")


def _check_conflict(
    import_id: str,
    nvme_dest: Path,
    hdd_dest: Path,
    resume: bool,
) -> None:
    if (nvme_dest.exists() or hdd_dest.exists()) and not resume:
        raise ConflictError(import_id)
    if (nvme_dest.exists() or hdd_dest.exists()) and resume:
        log.info("import_id %s already exists; resuming", import_id)


def _write_ingest_json(run: IngestRun, ingest_dir: Path, dry_run: bool) -> None:
    if dry_run:
        return
    out = ingest_dir / "ingest.json"
    out.write_text(json.dumps(run.to_dict(), indent=2, default=str), encoding="utf-8")


def _sync_ingest_dir_to_hdd(nvme_ingest_dir: Path, hdd_ingest_dir: Path) -> None:
    import shutil
    hdd_ingest_dir.mkdir(parents=True, exist_ok=True)
    for src in nvme_ingest_dir.iterdir():
        dst = hdd_ingest_dir / src.name
        try:
            shutil.copy2(src, dst)
        except OSError as exc:
            log.warning("Could not sync %s to HDD: %s", src.name, exc)


def _write_run_metrics(
    run: IngestRun,
    ingest_dir: Path,
    cfg: Config,
    duration: float,
) -> None:
    sc = run.scan
    ts = int(run.finished_at.timestamp()) if run.finished_at else 0
    success = run.status in ("verified", "completed")
    data: dict[str, Any] = {
        "active": 0,
        "last_success_ts": ts if success else 0,
        "last_failure_ts": 0 if success else ts,
        "duration_seconds": round(duration),
        "source_bytes": sc.total_bytes if sc else 0,
        "copied_bytes": sc.total_bytes if sc else 0,
        "files_total": len(sc.files) if sc else 0,
        "errors_total": len(run.errors),
        "verification_status": run.verification_status,
        "runs_total": 1,
    }
    if sc:
        for cls in ("raw", "photo", "video", "sidecar", "other"):
            data[f"{cls}_files"] = sc.counts.get(cls, 0)
            data[f"{cls}_bytes"] = sc.bytes_by_class.get(cls, 0)
    write_metrics(data, ingest_dir, cfg, run.import_id)


def _handle_failure(
    run: IngestRun,
    ingest_dir: Path | None,
    emitter: EventEmitter,
    dry_run: bool,
) -> None:
    run.status = "failed"
    run.finished_at = datetime.now(tz=timezone.utc)
    emitter.emit("ingest_failed", {"errors": run.errors})
    if ingest_dir and not dry_run:
        _write_ingest_json(run, ingest_dir, dry_run)


def _setup_file_logging(ingest_dir: Path, dry_run: bool) -> logging.FileHandler | None:
    if dry_run:
        return None
    ingest_dir.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(ingest_dir / "ingest.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s  %(message)s"))
    logging.getLogger().addHandler(fh)
    return fh


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "cam"
