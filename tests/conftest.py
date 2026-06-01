"""Shared fixtures for photo-ingest tests.

All fixtures operate on tmp_path only — no real block devices, no mounts,
no rsync calls.  Device/copy tests use monkeypatching.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from photo_ingest.config import Config


@pytest.fixture()
def cfg() -> Config:
    """Default Config with all paths pointing inside tmp (but not created)."""
    return Config()


@pytest.fixture()
def media_tree(tmp_path: Path) -> Path:
    """A small synthetic DCIM tree.

    Returns the 'DCIM' directory root.
    """
    dcim = tmp_path / "DCIM" / "100FUJI"
    dcim.mkdir(parents=True)

    files = {
        "DSCF0001.RAF": b"RAF" * 100,
        "DSCF0001.JPG": b"JPG" * 50,
        "DSCF0002.RAF": b"RAF" * 120,
        "DSCF0002.JPG": b"JPG" * 60,
        "DSCF0003.MOV": b"MOV" * 200,
        "DSCF0003.XMP": b"XMP" * 10,
        "MISC.BIN": b"BIN" * 5,
    }
    for name, data in files.items():
        (dcim / name).write_bytes(data)

    return tmp_path / "DCIM"


@pytest.fixture()
def ingest_dirs(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Return (nvme_dest, hdd_dest, nvme_ingest_dir) all under tmp_path."""
    nvme = tmp_path / "nvme" / "inbox" / "test-import"
    hdd = tmp_path / "hdd" / "imports" / "test-import"
    ingest_dir = nvme / "_ingest"
    ingest_dir.mkdir(parents=True)
    return nvme, hdd, ingest_dir
