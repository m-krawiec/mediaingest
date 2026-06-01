from __future__ import annotations

from pathlib import Path

import pytest

from photo_ingest.classify import Classifier, FileClass
from photo_ingest.config import ClassificationConfig
from photo_ingest.scan import ScanResult, scan_source, write_tree_snapshot


@pytest.fixture()
def classifier() -> Classifier:
    return Classifier(ClassificationConfig())


class TestScanSource:
    def test_counts_files(self, media_tree: Path, classifier: Classifier) -> None:
        result = scan_source(media_tree, classifier)
        # media_tree has 7 files in tests/conftest.py
        assert len(result.files) == 7

    def test_total_bytes(self, media_tree: Path, classifier: Classifier) -> None:
        result = scan_source(media_tree, classifier)
        expected = sum(f.size_bytes for f in result.files)
        assert result.total_bytes == expected

    def test_classification_counts(self, media_tree: Path, classifier: Classifier) -> None:
        result = scan_source(media_tree, classifier)
        assert result.counts["raw"] == 2    # DSCF0001.RAF, DSCF0002.RAF
        assert result.counts["photo"] == 2  # DSCF0001.JPG, DSCF0002.JPG
        assert result.counts["video"] == 1  # DSCF0003.MOV
        assert result.counts["sidecar"] == 1  # DSCF0003.XMP
        assert result.counts["other"] == 1   # MISC.BIN

    def test_relative_paths_are_relative(self, media_tree: Path, classifier: Classifier) -> None:
        result = scan_source(media_tree, classifier)
        for sf in result.files:
            assert not Path(sf.relative_path).is_absolute()

    def test_extension_lowercase(self, media_tree: Path, classifier: Classifier) -> None:
        result = scan_source(media_tree, classifier)
        for sf in result.files:
            assert sf.extension == sf.extension.lower()

    def test_empty_directory(self, tmp_path: Path, classifier: Classifier) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        result = scan_source(empty, classifier)
        assert result.files == []
        assert result.total_bytes == 0


class TestWriteTreeSnapshot:
    def test_creates_file(self, media_tree: Path, tmp_path: Path) -> None:
        dest = tmp_path / "source_tree.txt"
        write_tree_snapshot(media_tree, dest)
        assert dest.exists()
        content = dest.read_text()
        assert "DSCF0001.RAF" in content

    def test_all_files_listed(self, media_tree: Path, tmp_path: Path) -> None:
        dest = tmp_path / "source_tree.txt"
        write_tree_snapshot(media_tree, dest)
        lines = dest.read_text().splitlines()
        names = [l.split("\t")[0] for l in lines if l]
        assert any("DSCF0001.RAF" in n for n in names)
        assert any("DSCF0003.MOV" in n for n in names)
