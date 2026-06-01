from __future__ import annotations

from pathlib import Path

import pytest

from photo_ingest.config import Config
from photo_ingest.metrics import _render, write_metrics


class TestRenderMetrics:
    def test_contains_required_metrics(self) -> None:
        data = {
            "active": 0,
            "last_success_ts": 1748785443,
            "last_failure_ts": 0,
            "duration_seconds": 120,
            "source_bytes": 1000,
            "copied_bytes": 1000,
            "files_total": 10,
            "errors_total": 0,
            "verification_status": "ok",
            "runs_total": 5,
            "raw_files": 3,
            "raw_bytes": 600,
            "photo_files": 4,
            "photo_bytes": 300,
            "video_files": 2,
            "video_bytes": 100,
            "sidecar_files": 1,
            "sidecar_bytes": 0,
            "other_files": 0,
            "other_bytes": 0,
        }
        rendered = _render(data)
        assert "photo_ingest_last_success_timestamp" in rendered
        assert "photo_ingest_duration_seconds" in rendered
        assert "photo_ingest_raw_files_total" in rendered
        assert "photo_ingest_verification_status 1" in rendered  # "ok" maps to 1

    def test_atomic_write(self, tmp_path: Path) -> None:
        cfg = Config()
        cfg.metrics.textfile_dir = tmp_path / "collector"
        cfg.metrics.textfile_dir.mkdir()
        cfg.metrics.write_per_import = True

        ingest_dir = tmp_path / "_ingest"
        ingest_dir.mkdir()

        write_metrics({"verification_status": "ok"}, ingest_dir, cfg, "test-001")

        per_import = ingest_dir / "metrics.prom"
        rollup = cfg.metrics.textfile_dir / "photo_ingest.prom"
        assert per_import.exists()
        assert rollup.exists()

    def test_skipped_status_maps_to_zero(self) -> None:
        rendered = _render({"verification_status": "skipped"})
        assert "photo_ingest_verification_status 0" in rendered
