"""Tests for IngestArgs validation and _source_context path selection."""
from __future__ import annotations

import pytest

from photo_ingest.errors import ConfigError
from photo_ingest.ingest import IngestArgs


class TestIngestArgs:
    def test_source_device_only_is_valid(self) -> None:
        args = IngestArgs(source_device="/dev/sdc1")
        assert args.source_device == "/dev/sdc1"
        assert args.source_path is None

    def test_source_path_only_is_valid(self) -> None:
        args = IngestArgs(source_path="/mnt/sdcard")
        assert args.source_path == "/mnt/sdcard"
        assert args.source_device is None

    def test_neither_raises(self) -> None:
        with pytest.raises(ConfigError, match="source-device"):
            IngestArgs()

    def test_both_raises(self) -> None:
        with pytest.raises(ConfigError, match="mutually exclusive"):
            IngestArgs(source_device="/dev/sdc1", source_path="/mnt/sdcard")

    def test_source_label_returns_device(self) -> None:
        args = IngestArgs(source_device="/dev/sdc1")
        assert args.source_label == "/dev/sdc1"

    def test_source_label_returns_path(self) -> None:
        args = IngestArgs(source_path="/mnt/sdcard")
        assert args.source_label == "/mnt/sdcard"


class TestSourceContextPath:
    def test_source_path_missing_dir_raises(self, tmp_path: object) -> None:
        from pathlib import Path
        from photo_ingest.config import Config
        from photo_ingest.errors import SourceError
        from photo_ingest.ingest import _source_context
        assert isinstance(tmp_path, Path)

        args = IngestArgs(source_path=str(tmp_path / "nonexistent"))
        with pytest.raises(SourceError, match="does not exist"):
            with _source_context(args, Config()):
                pass

    def test_source_path_valid_dir_yields_path(self, tmp_path: object) -> None:
        from pathlib import Path
        from photo_ingest.config import Config
        from photo_ingest.ingest import _source_context
        assert isinstance(tmp_path, Path)

        args = IngestArgs(source_path=str(tmp_path))
        with _source_context(args, Config()) as (mountpoint, device_info):
            assert mountpoint == tmp_path
            assert device_info.label == tmp_path.name
