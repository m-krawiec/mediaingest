from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from photo_ingest.classify import Classifier
from photo_ingest.config import ClassificationConfig, Config, VerifyConfig
from photo_ingest.manifest import compute_checksums, write_checksums_file
from photo_ingest.scan import scan_source
from photo_ingest.verify import VerificationResult, verify


@pytest.fixture()
def full_copy(media_tree: Path, tmp_path: Path):  # type: ignore[no-untyped-def]
    """Return (scan_result, nvme_root, hdd_root, nvme_ingest_dir) with identical copies."""
    classifier = Classifier(ClassificationConfig())
    result = scan_source(media_tree, classifier)

    nvme = tmp_path / "nvme"
    hdd = tmp_path / "hdd"
    shutil.copytree(media_tree, nvme)
    shutil.copytree(media_tree, hdd)

    ingest_dir = tmp_path / "_ingest"
    ingest_dir.mkdir()

    checksums = compute_checksums(nvme, result.files, "sha256")
    for sf in result.files:
        sf.checksum = checksums.get(sf.relative_path, "")
    write_checksums_file(nvme, checksums, ingest_dir, "sha256")

    return result, nvme, hdd, ingest_dir


class TestVerify:
    def test_clean_copy_is_ok(self, full_copy: tuple) -> None:  # type: ignore[type-arg]
        scan_result, nvme, hdd, ingest_dir = full_copy
        cfg = VerifyConfig(mode="full")
        result = verify(scan_result.files, nvme, hdd, ingest_dir, cfg)
        assert result.status == "ok"
        assert result.source_vs_nvme.ok
        assert result.nvme_vs_hdd.ok

    def test_missing_file_on_hdd_fails(self, full_copy: tuple) -> None:  # type: ignore[type-arg]
        scan_result, nvme, hdd, ingest_dir = full_copy
        # Remove one file from HDD
        first = next(f for f in hdd.rglob("*.RAF"))
        first.unlink()
        cfg = VerifyConfig(mode="full")
        result = verify(scan_result.files, nvme, hdd, ingest_dir, cfg)
        assert result.nvme_vs_hdd.checksums_ok is False
        assert result.status != "ok"

    def test_corrupted_file_on_hdd_fails(self, full_copy: tuple) -> None:  # type: ignore[type-arg]
        scan_result, nvme, hdd, ingest_dir = full_copy
        # Corrupt one file on HDD
        raf = next(f for f in hdd.rglob("*.RAF"))
        raf.write_bytes(b"CORRUPTED")
        cfg = VerifyConfig(mode="full")
        result = verify(scan_result.files, nvme, hdd, ingest_dir, cfg)
        assert result.nvme_vs_hdd.checksums_ok is False
        assert len(result.nvme_vs_hdd.mismatches) >= 1

    def test_count_mismatch_detected(self, full_copy: tuple) -> None:  # type: ignore[type-arg]
        scan_result, nvme, hdd, ingest_dir = full_copy
        # Add an extra file on NVMe (simulates scan vs actual divergence)
        (nvme / "100FUJI" / "EXTRA.JPG").write_bytes(b"extra")
        cfg = VerifyConfig(mode="full")
        result = verify(scan_result.files, nvme, hdd, ingest_dir, cfg)
        # source_vs_nvme count should now differ
        assert not result.source_vs_nvme.files_ok

    def test_verification_result_to_dict(self, full_copy: tuple) -> None:  # type: ignore[type-arg]
        scan_result, nvme, hdd, ingest_dir = full_copy
        cfg = VerifyConfig()
        result = verify(scan_result.files, nvme, hdd, ingest_dir, cfg)
        d = result.to_dict()
        assert "verification_status" in d
        assert "source_vs_nvme" in d
        assert "nvme_vs_hdd" in d
