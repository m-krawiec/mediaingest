from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class EventEmitter:
    """Thread-safe JSONL event writer.

    Writes one JSON object per line to events.jsonl inside an _ingest/ dir.
    The file handle stays open for the lifetime of the run so events are
    flushed immediately rather than buffered.
    """

    def __init__(self, ingest_dir: Path, import_id: str, dry_run: bool = False) -> None:
        self._import_id = import_id
        self._dry_run = dry_run
        self._lock = threading.Lock()
        self._fh = None
        if not dry_run:
            ingest_dir.mkdir(parents=True, exist_ok=True)
            self._fh = (ingest_dir / "events.jsonl").open("a", encoding="utf-8")

    def emit(self, event: str, data: dict[str, Any] | None = None) -> None:
        obj: dict[str, Any] = {
            "ts": _now_iso(),
            "event": event,
            "import_id": self._import_id,
        }
        if data:
            obj["data"] = data
        with self._lock:
            if self._fh is not None:
                self._fh.write(json.dumps(obj, default=str) + "\n")
                self._fh.flush()

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __enter__(self) -> "EventEmitter":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()
