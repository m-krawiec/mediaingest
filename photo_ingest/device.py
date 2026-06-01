from __future__ import annotations

import json
import logging
import os
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from photo_ingest.config import IngestConfig
from photo_ingest.errors import SourceError

log = logging.getLogger(__name__)

# Filesystems commonly found on camera SD cards.
CARD_FILESYSTEMS = {"vfat", "fat32", "exfat", "msdos"}

# Device name prefixes that are never removable media.
_SYSTEM_PREFIXES = ("nvme", "md", "dm-", "sr", "loop")


@dataclass
class DeviceInfo:
    device: str                 # e.g. /dev/sdc1
    disk: str                   # e.g. /dev/sdc
    label: str = ""
    uuid: str = ""
    filesystem: str = ""
    size_bytes: int = 0
    is_removable: bool = False
    mountpoints: list[str] = field(default_factory=list)

    @property
    def safe_label(self) -> str:
        """Slugified label suitable for use in an import_id."""
        raw = self.label or "nolabel"
        return _slugify(raw)


def list_removable_devices() -> list[DeviceInfo]:
    """Return block devices that look like removable media (SD cards, USB drives)."""
    try:
        out = _run_lsblk()
    except Exception as exc:
        log.warning("lsblk failed: %s", exc)
        return []

    devices = []
    for dev in _iter_partitions(out):
        info = _build_device_info(dev)
        if info and info.is_removable:
            devices.append(info)
    return devices


def validate_device(device: str, cfg: IngestConfig) -> DeviceInfo:
    """Validate *device* is a safe SD card target; return its DeviceInfo.

    Raises SourceError if the device is unsafe or not found.
    Never touches or writes the device.
    """
    dev_path = Path(device)
    if not dev_path.exists():
        raise SourceError(f"Device not found: {device}")
    if not _is_block_device(device):
        raise SourceError(f"Not a block device: {device}")

    disk = _disk_for_partition(device)
    disk_name = Path(disk).name

    if any(disk_name.startswith(p) for p in _SYSTEM_PREFIXES):
        raise SourceError(
            f"Device {device} looks like a system disk ({disk_name}); refusing to proceed."
        )

    removable = _is_removable(disk)
    if not removable:
        log.warning(
            "Device %s is not marked removable. "
            "Proceed only if you are certain this is the SD card.",
            device,
        )

    if _is_system_mount(disk):
        raise SourceError(
            f"Disk {disk} contains a system mountpoint (/). Cannot use as source."
        )

    try:
        raw = _run_lsblk(device)
        partitions = list(_iter_partitions(raw))
        dev_data = partitions[0] if partitions else {}
        info = _build_device_info(dev_data) or DeviceInfo(device=device, disk=disk)
    except Exception as exc:
        log.warning("Could not get full lsblk info for %s: %s", device, exc)
        info = DeviceInfo(device=device, disk=disk)

    info.is_removable = removable
    log.info(
        "Device validated: %s label=%r fs=%s size=%d removable=%s",
        device, info.label, info.filesystem, info.size_bytes, info.is_removable,
    )
    return info


@contextmanager
def mounted_readonly(
    device: str,
    cfg: IngestConfig,
    logger: logging.Logger | None = None,
) -> Iterator[Path]:
    """Mount *device* read-only; yield the mountpoint; unmount on exit.

    If the device is already mounted read-only, reuses the existing mountpoint.
    Never mounts read-write.
    """
    _log = logger or log
    existing = _current_mountpoint(device)
    if existing:
        _log.info("Device %s already mounted at %s; reusing", device, existing)
        yield Path(existing)
        return

    mountpoint = cfg.mount_base / Path(device).name.replace("/", "_")
    mountpoint.mkdir(parents=True, exist_ok=True)

    mount_opts = "ro,noexec,nosuid,nodev"
    _log.info("Mounting %s → %s (opts=%s)", device, mountpoint, mount_opts)
    result = subprocess.run(
        ["mount", "-o", mount_opts, device, str(mountpoint)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise SourceError(
            f"Failed to mount {device}: {result.stderr.strip() or result.stdout.strip()}"
        )
    try:
        yield mountpoint
    finally:
        _log.info("Unmounting %s", mountpoint)
        subprocess.run(["umount", str(mountpoint)], capture_output=True)
        try:
            mountpoint.rmdir()
        except OSError:
            pass


def lsblk_snapshot(device: str) -> str:
    """Return raw lsblk -O output for the device (for _ingest/source_lsblk.txt)."""
    try:
        result = subprocess.run(
            ["lsblk", "-O", device], capture_output=True, text=True
        )
        return result.stdout
    except Exception as exc:
        return f"lsblk failed: {exc}\n"


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _run_lsblk(device: str | None = None) -> dict:  # type: ignore[return]
    cmd = ["lsblk", "--json", "--output",
           "NAME,PATH,TYPE,FSTYPE,LABEL,UUID,SIZE,RM,MOUNTPOINTS"]
    if device:
        cmd.append(device)
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def _iter_partitions(lsblk_out: dict) -> Iterator[dict]:  # type: ignore[type-arg]
    for disk in lsblk_out.get("blockdevices", []):
        if disk.get("type") == "part":
            yield disk
        for child in disk.get("children", []):
            if child.get("type") == "part":
                yield child


def _build_device_info(dev: dict) -> DeviceInfo | None:  # type: ignore[type-arg]
    if not dev:
        return None
    path = dev.get("path") or f"/dev/{dev.get('name', '')}"
    disk = _disk_for_partition(path)
    size_str = dev.get("size", "0")
    try:
        size = _parse_size(str(size_str))
    except ValueError:
        size = 0
    mps = dev.get("mountpoints") or []
    return DeviceInfo(
        device=path,
        disk=disk,
        label=dev.get("label") or "",
        uuid=dev.get("uuid") or "",
        filesystem=(dev.get("fstype") or "").lower(),
        size_bytes=size,
        is_removable=bool(dev.get("rm")),
        mountpoints=[m for m in mps if m],
    )


def _disk_for_partition(partition: str) -> str:
    name = Path(partition).name
    # Strip trailing digit(s) and optional 'p' suffix (e.g. sdc1 → sdc, nvme0n1p1 → nvme0n1)
    import re
    m = re.match(r"^(.*?)p?\d+$", name)
    disk_name = m.group(1) if m else name
    return f"/dev/{disk_name}"


def _is_block_device(path: str) -> bool:
    try:
        return os.stat(path).st_mode & 0o170000 == 0o060000
    except OSError:
        return False


def _is_removable(disk: str) -> bool:
    name = Path(disk).name
    sysfs = Path(f"/sys/block/{name}/removable")
    try:
        return sysfs.read_text().strip() == "1"
    except OSError:
        return False


def _is_system_mount(disk: str) -> bool:
    """Return True if *disk* or any of its partitions are mounted on /."""
    try:
        mounts = Path("/proc/mounts").read_text()
    except OSError:
        return False
    disk_name = Path(disk).name
    for line in mounts.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            dev, mp = parts[0], parts[1]
            if mp == "/" and Path(dev).name.startswith(disk_name):
                return True
    return False


def _current_mountpoint(device: str) -> str | None:
    try:
        mounts = Path("/proc/mounts").read_text()
    except OSError:
        return None
    for line in mounts.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == device:
            return parts[1]
    return None


def _parse_size(s: str) -> int:
    """Parse lsblk size strings like '64G', '128M', '500B' → bytes."""
    s = s.strip()
    if not s or s == "0":
        return 0
    units = {"B": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
    suffix = s[-1].upper()
    if suffix in units:
        return int(float(s[:-1]) * units[suffix])
    return int(s)


def _slugify(s: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "nolabel"
