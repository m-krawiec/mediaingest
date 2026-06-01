# MVP_SCOPE — photo-ingest

The MVP is "**a safe, logged, verified, two-copy full offload from one card, run by
one command.**" Nothing more. It must be trustworthy before it is convenient.

## In scope (MVP)

### Execution
- [x] Manual ingest via a single command: `photo-ingest run …`.
- [x] Configuration via a YAML file (`config.yml`) and/or environment variables;
      **no hardcoded paths**.
- [x] Source selection by explicit `--source-device /dev/sdc1`, or by matching
      filesystem label/UUID; with validation that the device is removable and not a
      system disk.
- [x] Mount the SD card **read-only** when the tool performs the mount.
- [x] `--copy-mode dcim` (default) copies the `DCIM/` subtree; `--copy-mode
      full-card` copies the entire card.
- [x] **No filtering of file types during ingest.** The full dump structure is
      preserved.

### Copy
- [x] rsync stage 1: card → NVMe inbox.
- [x] rsync stage 2: NVMe inbox → HDD imports (card read once).
- [x] Idempotent re-runs; `--resume` continues a partial copy via `rsync --partial`.
- [x] Free-space validation before each stage (`source_bytes * safety_factor`).

### Classification (statistics only)
- [x] Classify every file into `raw` / `photo` / `video` / `sidecar` / `other` by
      extension — for manifest, `ingest.json`, and metrics. Never to skip files.
- [x] Per-class counts and bytes.

### Records
- [x] Human text log (`ingest.log`).
- [x] Machine JSONL event log (`events.jsonl`).
- [x] `file_manifest.tsv` (per-file: path, class, size, mtime, checksum, copied flags).
- [x] `checksums.sha256` over the copied tree.
- [x] `ingest.json` canonical summary.

### Verification
- [x] File-count reconciliation (source ↔ NVMe ↔ HDD).
- [x] Byte-count reconciliation.
- [x] Checksum verification (full by default; sampling configurable).
- [x] `verification.json` with mismatch detail.

### Observability
- [x] Prometheus metrics as a `.prom` textfile (per-import + collector roll-up).
- [x] Metrics include duration, errors, per-file-type counts/bytes, verification
      status, timestamps.

### Operational guarantees
- [x] Stable **exit codes** suitable for automation (see DATA_MODEL).
- [x] **Never** deletes data from the card.
- [x] **Never** formats the card.
- [x] **Never** skips files by extension during ingest.
- [x] **Never** deletes data from NVMe (no inbox cleanup in MVP).
- [x] **No** automatic Immich import.
- [x] **No** automatic EXIF sorting.
- [x] **No** physical population of `library/raw|photos|videos|…`.

## Out of scope (MVP) — designed here, built later

- udev auto-trigger on card insert.
- Web UI.
- HTTP API.
- Immich integration / export watcher.
- Project staging (`photo-stage`, `work/` population).
- EXIF-based sorting / date hierarchy.
- Physical creation/population of `library/raw`, `library/photos`, `library/videos`,
  `library/sidecars`, `library/other`.
- Deduplication (file- or block-level).
- Hardlink/symlink-based library views.
- Notifications (email/Telegram/etc.).
- Lifecycle management (e.g. pruning old inboxes from NVMe).
- Grafana dashboard build-out (a draft JSON is a Stage 3 deliverable, but operating
  it is post-MVP).

## MVP acceptance criteria

The MVP is "done" when, against a real test card:

1. `photo-ingest run --source-device <dev> --camera <tag>` produces
   `inbox/<import_id>/` and `imports/<import_id>/` with identical DCIM trees.
2. The card is provably untouched (read-only mount; mtimes preserved; no writes).
3. `verification.json` reports `ok` with matching counts, bytes, and checksums on
   both hops.
4. `file_manifest.tsv`, `checksums.sha256`, `events.jsonl`, `ingest.json`, and
   `metrics.prom` are all present and internally consistent.
5. Per-class counts/bytes in `ingest.json` equal the sums in `file_manifest.tsv`.
6. Re-running the same command halts with exit `13` (conflict); adding `--resume`
   completes cleanly with no data damage.
7. A run interrupted mid-copy resumes correctly with `--resume`.
8. Exit codes match DATA_MODEL for: no device, no DCIM, no free space, conflict,
   rsync failure, checksum mismatch.
9. `metrics.prom` is scrapeable by node_exporter's textfile collector and a
   freshness check works in Uptime Kuma.
