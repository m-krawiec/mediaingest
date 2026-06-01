from __future__ import annotations

import csv
from pathlib import Path

import pytest

from photo_ingest.classify import Classifier, FileClass
from photo_ingest.config import ClassificationConfig, Config
from photo_ingest.manifest import (
    compute_checksums,
    load_checksums_file,
    write_checksums_file,
    write_manifest,
)
from photo_ingest.scan import scan_source


@pytest.fixture()
def classifier() -> Classifier:
    return Classifier(ClassificationConfig())


@pytest.fixture()
def scanned(media_tree: Path, classifier: Classifier):  # type: ignore[no-untyped-def]
    return scan_source(media_tree, classifier)


class TestWriteManifest:
    def test_creates_tsv(self, scanned: object, tmp_path: Path) -> None:
        from photo_ingest.scan import ScanResult
        assert isinstance(scanned, ScanResult)
        ingest_dir = tmp_path / "_ingest"
        ingest_dir.mkdir()
        path = write_manifest(scanned.files, ingest_dir)
        assert path.exists()

    def test_header_and_rows(self, scanned: object, tmp_path: Path) -> None:
        from photo_ingest.scan import ScanResult
        assert isinstance(scanned, ScanResult)
        ingest_dir = tmp_path / "_ingest"
        ingest_dir.mkdir()
        path = write_manifest(scanned.files, ingest_dir)
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh, delimiter="\t")
            rows = list(reader)
        assert len(rows) == len(scanned.files)
        required_cols = {"relative_path", "file_class", "size_bytes", "checksum"}
        assert required_cols <= set(rows[0].keys())

    def test_file_class_values_valid(self, scanned: object, tmp_path: Path) -> None:
        from photo_ingest.scan import ScanResult
        assert isinstance(scanned, ScanResult)
        ingest_dir = tmp_path / "_ingest"
        ingest_dir.mkdir()
        path = write_manifest(scanned.files, ingest_dir)
        valid = {c.value for c in FileClass}
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh, delimiter="\t")
            for row in reader:
                assert row["file_class"] in valid


class TestChecksums:
    def test_sha256_produces_hex_strings(self, media_tree: Path, scanned: object) -> None:
        from photo_ingest.scan import ScanResult
        assert isinstance(scanned, ScanResult)
        checksums = compute_checksums(media_tree, scanned.files, "sha256")
        assert len(checksums) == len(scanned.files)
        for rel, cksum in checksums.items():
            assert len(cksum) == 64, f"bad sha256 for {rel}: {cksum!r}"
            assert all(c in "0123456789abcdef" for c in cksum)

    def test_checksum_is_deterministic(self, media_tree: Path, scanned: object) -> None:
        from photo_ingest.scan import ScanResult
        assert isinstance(scanned, ScanResult)
        c1 = compute_checksums(media_tree, scanned.files, "sha256")
        c2 = compute_checksums(media_tree, scanned.files, "sha256")
        assert c1 == c2

    def test_write_and_load_roundtrip(self, media_tree: Path, scanned: object, tmp_path: Path) -> None:
        from photo_ingest.scan import ScanResult
        assert isinstance(scanned, ScanResult)
        ingest_dir = tmp_path / "_ingest"
        ingest_dir.mkdir()
        checksums = compute_checksums(media_tree, scanned.files, "sha256")
        write_checksums_file(media_tree, checksums, ingest_dir, "sha256")
        loaded = load_checksums_file(ingest_dir / "checksums.sha256")
        assert loaded == checksums

    def test_changed_file_produces_different_checksum(
        self, media_tree: Path, scanned: object, tmp_path: Path
    ) -> None:
        from photo_ingest.scan import ScanResult
        assert isinstance(scanned, ScanResult)
        # Make a copy, modify one file
        import shutil
        copy = tmp_path / "copy"
        shutil.copytree(media_tree, copy)

        original_checksums = compute_checksums(media_tree, scanned.files, "sha256")

        # Re-scan the copy
        from photo_ingest.classify import Classifier
        from photo_ingest.config import ClassificationConfig
        from photo_ingest.scan import scan_source
        copy_scan = scan_source(copy, Classifier(ClassificationConfig()))

        # Corrupt one file in the copy
        (copy / "100FUJI" / "DSCF0001.RAF").write_bytes(b"CORRUPTED")
        corrupted_checksums = compute_checksums(copy, copy_scan.files, "sha256")

        raf_key = next(k for k in original_checksums if "DSCF0001.RAF" in k)
        assert original_checksums[raf_key] != corrupted_checksums[raf_key]
