from __future__ import annotations

import pytest

from photo_ingest.classify import Classifier, FileClass
from photo_ingest.config import ClassificationConfig


@pytest.fixture()
def classifier() -> Classifier:
    return Classifier(ClassificationConfig())


class TestClassifier:
    def test_raw_extensions(self, classifier: Classifier) -> None:
        for ext in ("raf", "RAF", "raw", "dng", "cr2", "cr3", "nef", "arw", "orf", "rw2"):
            assert classifier.classify(ext) == FileClass.RAW, ext

    def test_photo_extensions(self, classifier: Classifier) -> None:
        for ext in ("jpg", "JPG", "jpeg", "heic", "heif", "png", "tif", "tiff"):
            assert classifier.classify(ext) == FileClass.PHOTO, ext

    def test_video_extensions(self, classifier: Classifier) -> None:
        for ext in ("mov", "MOV", "mp4", "m4v", "avi", "mts", "m2ts"):
            assert classifier.classify(ext) == FileClass.VIDEO, ext

    def test_sidecar_extensions(self, classifier: Classifier) -> None:
        for ext in ("xmp", "XMP", "dop", "cos", "xml", "aae", "thm"):
            assert classifier.classify(ext) == FileClass.SIDECAR, ext

    def test_unknown_extension_is_other(self, classifier: Classifier) -> None:
        assert classifier.classify("bin") == FileClass.OTHER
        assert classifier.classify("dat") == FileClass.OTHER
        assert classifier.classify("") == FileClass.OTHER

    def test_dot_prefix_stripped(self, classifier: Classifier) -> None:
        assert classifier.classify(".raf") == FileClass.RAW
        assert classifier.classify(".jpg") == FileClass.PHOTO

    def test_case_insensitive(self, classifier: Classifier) -> None:
        assert classifier.classify("RAF") == classifier.classify("raf")
        assert classifier.classify("MOV") == classifier.classify("mov")

    def test_custom_classification_config(self) -> None:
        cfg = ClassificationConfig(raw=["xyz"], photo=[], video=[], sidecar=[])
        c = Classifier(cfg)
        assert c.classify("xyz") == FileClass.RAW
        assert c.classify("jpg") == FileClass.OTHER  # not in custom config
