from __future__ import annotations

from enum import Enum

from photo_ingest.config import ClassificationConfig


class FileClass(str, Enum):
    RAW = "raw"
    PHOTO = "photo"
    VIDEO = "video"
    SIDECAR = "sidecar"
    OTHER = "other"


class Classifier:
    def __init__(self, cfg: ClassificationConfig) -> None:
        self._map: dict[str, FileClass] = {}
        for ext in cfg.raw:
            self._map[ext.lower()] = FileClass.RAW
        for ext in cfg.photo:
            self._map[ext.lower()] = FileClass.PHOTO
        for ext in cfg.video:
            self._map[ext.lower()] = FileClass.VIDEO
        for ext in cfg.sidecar:
            self._map[ext.lower()] = FileClass.SIDECAR

    def classify(self, extension: str) -> FileClass:
        """Return the FileClass for a lowercased, dot-stripped extension."""
        return self._map.get(extension.lower().lstrip("."), FileClass.OTHER)
