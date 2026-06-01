from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from photo_ingest.errors import ConfigError

_ENV_PREFIX = "PHOTO_INGEST_"


@dataclass
class StorageConfig:
    nvme_media_root: Path = Path("/nvme-mirror/media")
    hdd_archive_root: Path = Path("/hdd-mirror/archive/media")
    inbox_dirname: str = "inbox"
    work_dirname: str = "work"
    tmp_dirname: str = "tmp"
    imports_dirname: str = "imports"
    library_dirname: str = "library"
    projects_dirname: str = "projects"
    exports_dirname: str = "exports"
    manifests_dirname: str = "manifests"
    logs_dirname: str = "logs"

    @property
    def nvme_inbox(self) -> Path:
        return self.nvme_media_root / self.inbox_dirname

    @property
    def nvme_tmp(self) -> Path:
        return self.nvme_media_root / self.tmp_dirname

    @property
    def hdd_imports(self) -> Path:
        return self.hdd_archive_root / self.imports_dirname

    @property
    def hdd_manifests(self) -> Path:
        return self.hdd_archive_root / self.manifests_dirname

    @property
    def hdd_logs(self) -> Path:
        return self.hdd_archive_root / self.logs_dirname


@dataclass
class IngestConfig:
    copy_mode: str = "dcim"
    import_id_template: str = "{date}_{camera}-{cardlabel}_{seq}"
    date_format: str = "%Y-%m-%d"
    default_camera: str = "cam"
    mount_read_only: bool = True
    mount_base: Path = Path("/mnt/photo-ingest")
    free_space_safety_factor: float = 1.10
    rsync_extra_args: list[str] = field(
        default_factory=lambda: ["-a", "--info=progress2", "--no-compress"]
    )


@dataclass
class VerifyConfig:
    checksum_algorithm: str = "sha256"
    mode: str = "full"
    sample_fraction: float = 0.10


@dataclass
class MetricsConfig:
    textfile_dir: Path = Path("/var/lib/node_exporter/textfile_collector")
    write_per_import: bool = True


@dataclass
class LoggingConfig:
    console_format: str = "text"
    level: str = "INFO"


@dataclass
class ClassificationConfig:
    raw: list[str] = field(
        default_factory=lambda: ["raf", "raw", "dng", "cr2", "cr3", "nef", "arw", "orf", "rw2"]
    )
    photo: list[str] = field(
        default_factory=lambda: ["jpg", "jpeg", "heic", "heif", "png", "tif", "tiff"]
    )
    video: list[str] = field(
        default_factory=lambda: ["mov", "mp4", "m4v", "avi", "mts", "m2ts"]
    )
    sidecar: list[str] = field(
        default_factory=lambda: ["xmp", "dop", "cos", "xml", "aae", "thm"]
    )


@dataclass
class Config:
    storage: StorageConfig = field(default_factory=StorageConfig)
    ingest: IngestConfig = field(default_factory=IngestConfig)
    verify: VerifyConfig = field(default_factory=VerifyConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    classification: ClassificationConfig = field(default_factory=ClassificationConfig)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_config(path: Path | None = None) -> Config:
    """Load config from YAML file, then apply env overrides."""
    raw: dict[str, Any] = {}

    config_path = path or _resolve_config_path()
    if config_path and config_path.exists():
        try:
            with config_path.open() as fh:
                raw = yaml.safe_load(fh) or {}
        except Exception as exc:
            raise ConfigError(f"Cannot read config {config_path}: {exc}") from exc

    _apply_env_overrides(raw)
    return _build_config(raw)


def _resolve_config_path() -> Path | None:
    env = os.environ.get("PHOTO_INGEST_CONFIG")
    if env:
        return Path(env)
    candidates = [
        Path("/etc/photo-ingest/config.yml"),
        Path.home() / ".config" / "photo-ingest" / "config.yml",
        Path("config.yml"),
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _apply_env_overrides(raw: dict[str, Any]) -> None:
    """Apply a handful of well-known env shortcuts and the PHOTO_INGEST_* prefix."""
    shortcuts: dict[str, tuple[str, str]] = {
        "NVME_MEDIA_ROOT": ("storage", "nvme_media_root"),
        "HDD_ARCHIVE_ROOT": ("storage", "hdd_archive_root"),
    }
    for env_key, (section, key) in shortcuts.items():
        val = os.environ.get(env_key)
        if val:
            raw.setdefault(section, {})[key] = val

    for env_key, val in os.environ.items():
        if not env_key.startswith(_ENV_PREFIX):
            continue
        rest = env_key[len(_ENV_PREFIX):].lower()
        parts = rest.split("_", 1)
        if len(parts) == 2:
            section, key = parts
            raw.setdefault(section, {})[key] = val


def _build_config(raw: dict[str, Any]) -> Config:
    cfg = Config()

    s = raw.get("storage", {})
    if s:
        if "nvme_media_root" in s:
            cfg.storage.nvme_media_root = Path(s["nvme_media_root"])
        if "hdd_archive_root" in s:
            cfg.storage.hdd_archive_root = Path(s["hdd_archive_root"])
        for k in ("inbox_dirname", "work_dirname", "tmp_dirname", "imports_dirname",
                  "library_dirname", "projects_dirname", "exports_dirname",
                  "manifests_dirname", "logs_dirname"):
            if k in s:
                setattr(cfg.storage, k, str(s[k]))

    i = raw.get("ingest", {})
    if i:
        for k in ("copy_mode", "import_id_template", "date_format", "default_camera"):
            if k in i:
                setattr(cfg.ingest, k, str(i[k]))
        if "mount_read_only" in i:
            cfg.ingest.mount_read_only = bool(i["mount_read_only"])
        if "mount_base" in i:
            cfg.ingest.mount_base = Path(i["mount_base"])
        if "free_space_safety_factor" in i:
            cfg.ingest.free_space_safety_factor = float(i["free_space_safety_factor"])
        if "rsync_extra_args" in i:
            cfg.ingest.rsync_extra_args = list(i["rsync_extra_args"])

    v = raw.get("verify", {})
    if v:
        if "checksum_algorithm" in v:
            cfg.verify.checksum_algorithm = str(v["checksum_algorithm"])
        if "mode" in v:
            cfg.verify.mode = str(v["mode"])
        if "sample_fraction" in v:
            cfg.verify.sample_fraction = float(v["sample_fraction"])

    m = raw.get("metrics", {})
    if m:
        if "textfile_dir" in m:
            cfg.metrics.textfile_dir = Path(m["textfile_dir"])
        if "write_per_import" in m:
            cfg.metrics.write_per_import = bool(m["write_per_import"])

    lo = raw.get("logging", {})
    if lo:
        if "console_format" in lo:
            cfg.logging.console_format = str(lo["console_format"])
        if "level" in lo:
            cfg.logging.level = str(lo["level"])

    cl = raw.get("classification", {})
    if cl:
        for k in ("raw", "photo", "video", "sidecar"):
            if k in cl:
                setattr(cfg.classification, k, [str(x) for x in cl[k]])

    _validate(cfg)
    return cfg


def _validate(cfg: Config) -> None:
    if cfg.ingest.copy_mode not in ("dcim", "full_card"):
        raise ConfigError(
            f"ingest.copy_mode must be 'dcim' or 'full_card', got '{cfg.ingest.copy_mode}'"
        )
    if cfg.verify.checksum_algorithm not in ("sha256", "b3sum"):
        raise ConfigError(
            f"verify.checksum_algorithm must be 'sha256' or 'b3sum', "
            f"got '{cfg.verify.checksum_algorithm}'"
        )
    if cfg.verify.mode not in ("full", "sample"):
        raise ConfigError(
            f"verify.mode must be 'full' or 'sample', got '{cfg.verify.mode}'"
        )
    if not (0.0 < cfg.ingest.free_space_safety_factor):
        raise ConfigError("ingest.free_space_safety_factor must be > 0")
