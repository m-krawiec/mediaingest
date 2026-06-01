# IMPLEMENTATION_PLAN — photo-ingest

Staged plan. Each stage lists **result**, **files to create**, **risks**, and
**acceptance tests**. Stages 0–4 are the MVP; 5–6 are post-MVP. Build in order;
do not start a stage until the previous stage's acceptance tests pass.

Proposed source layout (created incrementally across stages):

```
photo_ingest/
  __init__.py
  __main__.py            # `python -m photo_ingest`
  cli.py                 # argparse, subcommands, exit codes
  config.py              # YAML + env loading, validation, defaults
  device.py              # block-device discovery, validation, read-only mount
  scan.py                # recursive source scan
  classify.py            # extension -> file_class
  copy.py                # rsync stage 1 / stage 2 wrappers
  manifest.py            # file_manifest.tsv + checksums.sha256
  verify.py              # count/size/checksum reconciliation
  events.py              # JSONL event emitter
  metrics.py             # Prometheus textfile writer
  ingest.py              # orchestration / state machine
  errors.py              # typed errors mapped to exit codes
tests/
deploy/
  systemd/photo-ingest@.service
  systemd/photo-ingest.timer
  docker/Dockerfile.exporter
  docker/docker-compose.yml
  grafana/photo-ingest-dashboard.json
config.example.yml
```

---

## Stage 0 — Decisions and preparation

**Result:** every environment-specific unknown is resolved and written down, so no
later stage has to guess.

**Files to create:**
- `docs/STAGE0_DECISIONS.md` (or a filled-in section in this file) recording the
  answers below.
- `config.yml` derived from `config.example.yml` with real paths.

**Decisions to confirm:**
- NVMe mountpoint (`nvme_media_root`) and HDD mountpoint (`hdd_archive_root`).
- File ownership/permissions for the ingest user; whether `mount` needs sudo/CAP.
- SD card access method (USB passthrough to VM vs host mount + bind) — see
  ARCHITECTURE "How the SD card reader reaches the VM".
- How the card appears: `lsblk -O`, expected filesystems (exFAT/FAT32/…), label.
- Default copy mode (`dcim` recommended).
- Language: **Python** (decided — see ARCHITECTURE "MVP architecture").

**Risks:** wrong assumptions here propagate everywhere; mount permissions are the
most common blocker (mounting may require `CAP_SYS_ADMIN`/sudo or an fstab/udisks
policy).

**Acceptance tests:**
- `lsblk -O` output for a test card captured and reviewed.
- The ingest user can mount the card read-only and read both storage roots.
- `config.yml` validates (Stage 1 `config.py` `--check-config`).

---

## Stage 1 — Manual ingest CLI (copy only)

**Result:** `photo-ingest run` copies card → NVMe → HDD with classification,
logging, and a manifest. No verification yet.

**Files to create:** `cli.py`, `config.py`, `device.py`, `scan.py`, `classify.py`,
`copy.py`, `manifest.py`, `events.py`, `ingest.py`, `errors.py`, `__main__.py`.

**Work:**
- Config loading (YAML + env override) and validation; `--check-config`.
- Path validation: roots exist, writable, on expected filesystems.
- Device detection/validation: removable, non-system; resolve label/UUID/fs.
- Read-only mount (configurable mount base); unmount in a `finally`.
- Recursive source scan → counts, bytes, tree snapshot.
- Classification by extension → per-class counts/bytes.
- `import_id` generation + conflict detection (`--resume`, `--auto-seq`).
- rsync stage 1 (card→NVMe) and stage 2 (NVMe→HDD) with logs.
- `file_manifest.tsv` (checksum column may be empty until Stage 2).
- `--dry-run`, `--source-device`, `--import-id`, `--camera`, `--copy-mode`.

**Risks:** unstable `/dev/sdX`; partial copies; rsync flag mistakes (e.g.
accidental `--delete`); mount left dangling on crash. Mitigate with strict device
validation, `--partial`, never using `--delete`, and `finally`-unmount.

**Acceptance tests:**
- `--dry-run` lists planned actions and writes nothing.
- A real card produces matching DCIM trees on both tiers (by `diff -r` of names).
- `import_id` conflict halts with exit `13`; `--resume` continues.
- Missing `DCIM/` in `dcim` mode → exit `11`; full-card mode still works.
- Per-class counts in `ingest.json` equal manifest sums.
- Source mtimes unchanged; mount was read-only (verified via mount flags).

---

## Stage 2 — Verification

**Result:** every run proves integrity; `status` can reach `verified`.

**Files to create:** `verify.py`, plus `checksums.sha256` / `verification.json`
generation wired into `ingest.py`.

**Work:**
- `checksums.sha256` over the copied tree (sha256 default; b3sum option).
- Fill the manifest `checksum` column.
- Compare source → NVMe and NVMe → HDD: count, bytes, checksums.
- `verification.json` with mismatch detail; set `verification_status`.
- Safe failure modes: on mismatch, set `status=failed`/`partial`, exit `21`,
  **never** delete either copy, surface mismatches in log + metrics.

**Risks:** checksum cost on large cards (mitigate with `verify.mode: sample`);
false mismatches from in-flight files (card is read-only, so stable); time skew on
exFAT mtimes (compare with tolerance or rely on size+checksum).

**Acceptance tests:**
- Clean card → `verification_status: ok`, exit `0`, status `verified`.
- Inject a corrupted file on one tier → exit `21`, mismatch listed, no deletion.
- Count mismatch and size mismatch each produce the correct status/exit.
- Sample mode checksums the configured fraction; counts/sizes still 100%.

---

## Stage 3 — Observability

**Result:** runs are visible in Prometheus/Grafana, logs in Dozzle/Alloy, health in
Uptime Kuma.

**Files to create:** `metrics.py`, `deploy/grafana/photo-ingest-dashboard.json`,
healthcheck doc/snippet, Alloy/Dozzle integration notes.

**Work:**
- Write `events.jsonl` for all events (finalize schema).
- Write `metrics.prom` (per-import + roll-up into textfile collector dir).
- All metrics from DATA_MODEL, including per-file-type and verification status.
- Point node_exporter textfile collector at the dir; confirm Prometheus scrape.
- Grafana dashboard draft: last success/failure, duration, throughput, per-class
  breakdown, error count, active gauge.
- Uptime Kuma: a freshness/health probe (e.g. push or a metrics-freshness check).
- Document Alloy shipping journald + `events.jsonl` to Loki (if/when Loki exists).

**Risks:** textfile-collector dir permissions; metric cardinality if `import_id`
labels leak into the roll-up; partial `.prom` writes (write to temp + atomic rename).

**Acceptance tests:**
- `metrics.prom` parses with `promtool check metrics`.
- Prometheus shows `photo_ingest_last_success_timestamp` updating after a run.
- Grafana dashboard renders all panels from real data.
- Uptime Kuma flips to down when no successful ingest within the freshness window.
- `.prom` is written atomically (no partial reads observed under load).

---

## Stage 4 — Packaging

**Result:** the tool installs and runs as a systemd service in the VM; the optional
exporter/API runs as an unprivileged container.

**Files to create:** `pyproject.toml`, `deploy/systemd/photo-ingest@.service`,
`deploy/systemd/photo-ingest.timer` (optional), `deploy/docker/Dockerfile.exporter`,
`deploy/docker/docker-compose.yml`, `config.example.yml` (already present), a
runtime README section.

**Work:**
- Package as an installable Python CLI (`photo-ingest` entry point).
- systemd unit (templated by device or import) with least privilege; document the
  capabilities/sudo needed for mount.
- Optional exporter container (unprivileged; reads collector dir or serves metrics).
- `docker-compose.yml` wiring the exporter into the existing stack (Prometheus
  scrape target, Dozzle log capture).
- Runtime README: install, configure, run, troubleshoot.

**Risks:** over-privileging the systemd unit; container accidentally given device
access (explicitly forbid in compose). Keep ingest out of the container.

**Acceptance tests:**
- `pip install .` then `photo-ingest --help` works on a clean VM.
- `systemctl start photo-ingest@…` runs a full ingest; journald shows logs.
- Exporter container starts unprivileged, exposes/relays metrics, appears in
  Prometheus and Dozzle; it has **no** `/dev` access (verified).

---

## Stage 5 — Staging for work (post-MVP)

**Result:** `photo-stage` creates an NVMe `work/<project_id>/` copy of selected
imports/folders for editing, without touching `imports/`.

**Files to create:** `photo_ingest/stage.py`, `cli.py` `stage` subcommand, staging
log format.

**Work:**
- Create a project on NVMe `work/`.
- Copy selected imports or subfolders (by import_id, by folder, by class filter).
- Allow staging RAW only / photos only / video only / everything — this is a
  **derived-copy filter**, explicitly separate from ingest (ingest never filters).
- Staging logs + a small manifest of what was staged.

**Risks:** users confusing staging filters with ingest filters (document loudly);
NVMe space pressure; never move out of `imports/`.

**Acceptance tests:**
- `photo-stage --import-id … --classes raw` populates `work/<project>/` with only
  RAW, leaving `imports/` untouched.
- Staging the same project twice is idempotent.

---

## Stage 6 — Future extensions (post-MVP)

**Result:** roadmap items scoped enough to start when prioritized.

Items (each its own future mini-plan):
- **Immich export watcher** — push frozen `exports/immich/<project>/` to Immich /
  trigger a rescan of a read-only external library.
- **EXIF sorting / library builder** — build `library/raw|photos|videos|sidecars|
  other` as a derived, by-date view from `imports/` using ExifTool, with
  `FileModifyDate` fallback for date-less files. Copies only; imports stays immutable.
- **Lifecycle policy** — prune old `inbox/` entries from NVMe once archived +
  verified + (optionally) backed up offsite. Policy-driven, never automatic on
  un-verified data.
- **Notifications** — success/failure to email/Telegram/etc.
- **Web UI** — read-only first (browse imports, view manifests/metrics), then
  trigger ingests via the API.

**Risks/acceptance:** defined per item when scheduled. Invariant across all of
them: `imports/` is immutable; derived layers are rebuildable; nothing deletes
un-verified, un-backed-up originals.
