from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from photo_ingest import __version__
from photo_ingest.config import load_config
from photo_ingest.device import list_removable_devices
from photo_ingest.errors import ExitCode, IngestError
from photo_ingest.ingest import IngestArgs, run as ingest_run


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    cfg = _load_config_or_exit(args)
    _configure_logging(args, cfg)

    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(ExitCode.USAGE_ERROR)

    try:
        args.func(args, cfg)
    except IngestError as exc:
        logging.getLogger("photo-ingest").error("%s", exc)
        sys.exit(exc.exit_code)
    except KeyboardInterrupt:
        logging.getLogger("photo-ingest").error("Interrupted")
        sys.exit(ExitCode.INTERRUPTED)


# ---------------------------------------------------------------------------
# Sub-commands
# ---------------------------------------------------------------------------

def cmd_run(args: argparse.Namespace, cfg: object) -> None:
    from photo_ingest.config import Config
    assert isinstance(cfg, Config)

    ingest_args = IngestArgs(
        source_device=getattr(args, "source_device", None),
        source_path=getattr(args, "source_path", None),
        camera=args.camera,
        import_id=args.import_id,
        copy_mode=args.copy_mode,
        resume=args.resume,
        auto_seq=args.auto_seq,
        dry_run=args.dry_run,
    )
    run_state = ingest_run(ingest_args, cfg)

    if run_state.status in ("failed",):
        sys.exit(ExitCode.COPY_ERROR)


def cmd_list_devices(_args: argparse.Namespace, _cfg: object) -> None:
    devices = list_removable_devices()
    if not devices:
        print("No removable block devices found.")
        print("If the card is inserted, try: lsblk -O")
        return
    print(f"{'DEVICE':<16} {'LABEL':<20} {'FS':<10} {'SIZE':>12}  REMOVABLE")
    print("-" * 70)
    for d in devices:
        size_gib = d.size_bytes / 1024**3
        print(
            f"{d.device:<16} {(d.label or '-'):<20} {(d.filesystem or '-'):<10} "
            f"{size_gib:>10.1f}G  {'yes' if d.is_removable else 'no'}"
        )


def cmd_check_config(_args: argparse.Namespace, cfg: object) -> None:
    from photo_ingest.config import Config
    assert isinstance(cfg, Config)
    print("Config OK")
    print(f"  nvme_media_root  : {cfg.storage.nvme_media_root}")
    print(f"  hdd_archive_root : {cfg.storage.hdd_archive_root}")
    print(f"  copy_mode        : {cfg.ingest.copy_mode}")
    print(f"  checksum         : {cfg.verify.checksum_algorithm}")
    print(f"  verify mode      : {cfg.verify.mode}")
    print(f"  mount_read_only  : {cfg.ingest.mount_read_only}")
    print(f"  textfile_dir     : {cfg.metrics.textfile_dir}")


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="photo-ingest",
        description="Safe, logged SD card ingest for photos and videos.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--config", metavar="PATH", type=Path,
        help="Path to config.yml (default: auto-detect)",
    )
    parser.add_argument(
        "--log-level", default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Override log level",
    )

    sub = parser.add_subparsers(title="commands")

    # --- run ---
    p_run = sub.add_parser("run", help="Execute a full SD card ingest")
    src_group = p_run.add_mutually_exclusive_group(required=True)
    src_group.add_argument(
        "--source-device", metavar="DEV",
        help="Block device to ingest from, e.g. /dev/sdc1 (tool mounts it read-only)",
    )
    src_group.add_argument(
        "--source-path", metavar="PATH",
        help=(
            "Pre-mounted source directory, e.g. /mnt/sdcard "
            "(Docker / host-mounted; no device access needed)"
        ),
    )
    p_run.add_argument(
        "--camera", metavar="TAG",
        help="Short camera identifier (slugified, e.g. fuji, sony-a7iv)",
    )
    p_run.add_argument(
        "--import-id", metavar="ID",
        help="Override the generated import_id (must not already exist unless --resume)",
    )
    p_run.add_argument(
        "--copy-mode", choices=["dcim", "full-card"],
        help="dcim (default): copy DCIM/ only.  full-card: copy entire card.",
    )
    p_run.add_argument(
        "--resume", action="store_true",
        help="Continue a partial copy (import_id must already exist)",
    )
    p_run.add_argument(
        "--auto-seq", action="store_true",
        help="Increment the sequence suffix to find a free import_id instead of erroring",
    )
    p_run.add_argument(
        "--dry-run", action="store_true",
        help="Scan and log planned actions without copying anything",
    )
    p_run.set_defaults(func=cmd_run)

    # --- list-devices ---
    p_ls = sub.add_parser("list-devices", help="List removable block devices")
    p_ls.set_defaults(func=cmd_list_devices)

    # --- check-config ---
    p_cc = sub.add_parser("check-config", help="Validate configuration and print active values")
    p_cc.set_defaults(func=cmd_check_config)

    return parser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_config_or_exit(args: argparse.Namespace) -> object:
    from photo_ingest.config import Config
    from photo_ingest.errors import ConfigError
    try:
        config_path: Path | None = getattr(args, "config", None)
        return load_config(config_path)
    except Exception as exc:
        print(f"photo-ingest: config error: {exc}", file=sys.stderr)
        sys.exit(ExitCode.USAGE_ERROR)


def _configure_logging(args: argparse.Namespace, cfg: object) -> None:
    from photo_ingest.config import Config
    level_str: str = getattr(args, "log_level", None) or (
        cfg.logging.level if isinstance(cfg, Config) else "INFO"
    )
    level = getattr(logging, level_str.upper(), logging.INFO)

    fmt = "%(asctime)s %(levelname)-8s %(message)s"
    logging.basicConfig(level=level, format=fmt, stream=sys.stderr)
