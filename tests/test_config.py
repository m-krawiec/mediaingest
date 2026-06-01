from __future__ import annotations

import os
from pathlib import Path

import pytest

from photo_ingest.config import Config, load_config
from photo_ingest.errors import ConfigError


class TestLoadConfig:
    def test_defaults_without_file(self) -> None:
        cfg = load_config(path=None)
        assert cfg.ingest.copy_mode == "dcim"
        assert cfg.verify.checksum_algorithm == "sha256"

    def test_load_from_file(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "config.yml"
        cfg_file.write_text(
            "storage:\n  nvme_media_root: /custom/nvme\n",
            encoding="utf-8",
        )
        cfg = load_config(cfg_file)
        assert cfg.storage.nvme_media_root == Path("/custom/nvme")

    def test_env_override_nvme_root(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NVME_MEDIA_ROOT", "/env/nvme")
        cfg = load_config(path=None)
        assert cfg.storage.nvme_media_root == Path("/env/nvme")

    def test_env_override_hdd_root(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HDD_ARCHIVE_ROOT", "/env/hdd")
        cfg = load_config(path=None)
        assert cfg.storage.hdd_archive_root == Path("/env/hdd")

    def test_invalid_copy_mode_raises(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "config.yml"
        cfg_file.write_text("ingest:\n  copy_mode: bogus\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="copy_mode"):
            load_config(cfg_file)

    def test_invalid_algorithm_raises(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "config.yml"
        cfg_file.write_text("verify:\n  checksum_algorithm: md5\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="checksum_algorithm"):
            load_config(cfg_file)

    def test_storage_properties(self) -> None:
        cfg = Config()
        assert cfg.storage.nvme_inbox == cfg.storage.nvme_media_root / "inbox"
        assert cfg.storage.hdd_imports == cfg.storage.hdd_archive_root / "imports"
