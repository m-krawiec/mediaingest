# TODO — photo-ingest

Checklist tracking build progress. Stages map to
[docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md). MVP = Discovery →
Docker/Systemd + Testing + Documentation.

## Discovery (Stage 0)

- [ ] Confirm NVMe mirror mountpoint (`nvme_media_root`)
- [ ] Confirm HDD mirror mountpoint (`hdd_archive_root`)
- [ ] Decide whether ingest runs in the VM or in a container (recommendation: **VM**)
- [ ] Check how the SD card appears in `lsblk -O`
- [ ] Check supported SD card filesystems (exFAT/FAT32/…)
- [ ] Decide the default copy mode: `dcim` (recommended) or `full-card`
- [ ] Confirm mount permissions for the ingest user (sudo/CAP_SYS_ADMIN/udisks)
- [ ] Confirm SD card passthrough method (USB passthrough to VM vs host mount+bind)
- [ ] Record decisions in `docs/STAGE0_DECISIONS.md`

## Storage

- [ ] Create ZFS datasets for NVMe + HDD tiers (see ARCHITECTURE)
- [ ] Set `compression=lz4`, `atime=off`; confirm dedup is **off**
- [ ] Prepare `/nvme-mirror/media/inbox`
- [ ] Prepare `/nvme-mirror/media/work`
- [ ] Prepare `/nvme-mirror/media/tmp`
- [ ] Prepare `/hdd-mirror/archive/media/imports`
- [ ] Prepare `/hdd-mirror/archive/media/library`
- [ ] Prepare `/hdd-mirror/archive/media/exports/immich`
- [ ] Prepare `/hdd-mirror/archive/media/manifests` and `/logs`
- [ ] Verify free-space check works before import

## Ingest CLI (Stage 1)

- [ ] `config.example.yml` (done) → derive site `config.yml`
- [ ] `config.py` loader (YAML + env) with validation and `--check-config`
- [ ] `photo-ingest` CLI skeleton (`cli.py`, `__main__.py`) with exit codes
- [ ] `device.py`: discovery + validation + read-only mount + safe unmount
- [ ] `scan.py`: recursive source scan (counts, bytes, tree snapshot)
- [ ] `classify.py`: extension → file_class
- [ ] `import_id` generation + conflict detection
- [ ] `copy.py`: rsync SD → NVMe (stage 1)
- [ ] `copy.py`: rsync NVMe → HDD (stage 2)
- [ ] `manifest.py`: `file_manifest.tsv`
- [ ] `--dry-run`
- [ ] `--source-device`
- [ ] `--import-id`
- [ ] `--camera`
- [ ] `--copy-mode dcim`
- [ ] `--copy-mode full-card`
- [ ] `--resume`
- [ ] `--auto-seq`
- [ ] Free-space validation

## File Classification

- [ ] RAW classification
- [ ] Photos classification
- [ ] Videos classification
- [ ] Sidecars classification
- [ ] Other classification
- [ ] File-count statistics by class
- [ ] Size statistics by class
- [ ] Classification written to `file_manifest.tsv`
- [ ] Classification written to `ingest.json`
- [ ] Prometheus metrics by class

## Verification (Stage 2)

- [ ] `checksums.sha256` generation (sha256 default, b3sum option)
- [ ] Fill manifest `checksum` column
- [ ] `events.jsonl` emitter (`events.py`)
- [ ] `verification.json` (`verify.py`)
- [ ] File-count comparison (source↔NVMe↔HDD)
- [ ] Size comparison
- [ ] Checksum comparison (full + sample modes)
- [ ] Safe failure modes (no deletion on mismatch; exit 21)
- [ ] Recovery procedure for interrupted imports (`--resume`)

## Observability (Stage 3)

- [ ] `metrics.py`: `metrics.prom` (per-import + collector roll-up)
- [ ] Ingest-duration metric
- [ ] Error metrics
- [ ] Metrics by file type
- [ ] Atomic `.prom` writes (temp + rename)
- [ ] Point node_exporter textfile collector at the dir; confirm Prometheus scrape
- [ ] Grafana dashboard draft (`deploy/grafana/photo-ingest-dashboard.json`)
- [ ] Uptime Kuma healthcheck (freshness probe)
- [ ] Plan Grafana Alloy integration (journald + events.jsonl → Loki)
- [ ] Plan Dozzle integration (exporter/API container logs)

## Docker/Systemd (Stage 4)

- [ ] `pyproject.toml` + `photo-ingest` entry point
- [ ] Compare Docker vs systemd (recommendation: systemd in VM — done in docs)
- [ ] `deploy/systemd/photo-ingest@.service` (least privilege)
- [ ] `deploy/systemd/photo-ingest.timer` (optional)
- [ ] Optional exporter container `deploy/docker/Dockerfile.exporter` (unprivileged)
- [ ] `deploy/docker/docker-compose.yml` (no `/dev` access)
- [ ] Runtime README section

## Testing

- [ ] Test with a small test card (or loopback image fixture)
- [ ] Test without a `DCIM/` folder (expect exit 11)
- [ ] `copy_mode=full-card` test
- [ ] Interrupted-import test (resume)
- [ ] `import_id` conflict test (exit 13; `--resume` succeeds)
- [ ] No-free-space test (exit 12)
- [ ] Checksum-mismatch test (exit 21; nothing deleted)
- [ ] Idempotency test (re-run causes no damage)
- [ ] Read-only-mount assertion (source mtimes unchanged)
- [ ] `--dry-run` writes-nothing test

## Documentation

- [x] `docs/PRODUCT_BRIEF.md`
- [x] `docs/ARCHITECTURE.md`
- [x] `docs/DATA_MODEL.md`
- [x] `docs/MVP_SCOPE.md`
- [x] `docs/IMPLEMENTATION_PLAN.md`
- [x] `docs/AGENTS.md`
- [x] `TODO.md`
- [x] `README.md`
- [x] `config.example.yml`
- [ ] `docs/STAGE0_DECISIONS.md` (filled during Stage 0)
- [ ] Runtime/install README (Stage 4)

## Future (Stages 5–6, post-MVP)

- [ ] Design `photo-stage` (NVMe `work/` staging with class filters)
- [ ] Design library builder (derived `raw/photos/videos/sidecars/other` view)
- [ ] Design EXIF sorting (date hierarchy, `FileModifyDate` fallback)
- [ ] Design Immich export watcher
- [ ] Design lifecycle policy for NVMe inbox (prune verified+archived only)
- [ ] Design notifications
- [ ] Design web UI
- [ ] Design udev auto-trigger on card insert
