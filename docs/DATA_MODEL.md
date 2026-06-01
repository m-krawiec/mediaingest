# DATA_MODEL — photo-ingest

## Directory structure

```
/nvme-mirror/media/                      # NVMe tier (NVME_MEDIA_ROOT)
  inbox/
    <import_id>/
      DCIM/                              # (copy_mode=dcim) or _card/ (full_card)
      _ingest/                           # per-import artifacts (see below)
  work/
    <project_id>/                        # active editing copies (post-MVP)
  tmp/                                   # scratch; the ONLY rm-eligible area

/hdd-mirror/archive/media/               # HDD tier (HDD_ARCHIVE_ROOT)
  imports/
    <import_id>/
      DCIM/                              # immutable card dump = source of truth
      _ingest/                           # per-import artifacts (mirrors inbox)
  library/                               # derived by-type view (post-MVP)
    raw/
    photos/
    videos/
    sidecars/
    other/
  projects/
    <project_id>/                        # completed sessions (post-MVP)
  exports/
    immich/                              # gallery outputs (post-MVP)
  manifests/                             # roll-up: <import_id>.tsv copies (optional)
  logs/                                  # roll-up: ingest.jsonl append log (optional)
```

`imports/<import_id>/` is immutable. `inbox/`, `work/`, `library/`, `projects/`,
`exports/` are derived/disposable. Only `tmp/` may be deleted by the program.

## copy_mode and the card-dump layout

The system supports two modes, recorded as `copy_mode` in `ingest.json`:

| Mode | Selector | On-disk layout under `<import_id>/` |
| --- | --- | --- |
| `dcim` (default) | `--copy-mode dcim` | `DCIM/…` + `_ingest/` |
| `full_card` | `--copy-mode full-card` | `_card/<original card contents>` + `_ingest/` |

How the mode is distinguished and recorded:

- The CLI flag (or `ingest.copy_mode` in config) sets the mode explicitly.
- `dcim` copies only the `DCIM/` subtree of the mounted card. If `DCIM/` is absent,
  the run **fails** with a clear error (do not silently fall back).
- `full_card` copies the entire mounted card into `_card/`, preserving the card's
  top-level layout (which may or may not include `DCIM/`, plus `MISC/`, `PRIVATE/`,
  vendor folders, `.dat` files, etc.).
- `ingest.json.copy_mode` always records which mode produced the dump, so consumers
  never have to guess from the directory shape.

The `_ingest/` directory is identical in structure in both modes and on both tiers.

## import_id

Format:

```
YYYY-MM-DD_<camera>-<cardlabel>_<sequence>
```

Example:

```
2026-06-01_fuji-avpro-sd_001
```

- `YYYY-MM-DD` — ingest date (operationally sortable, human-readable). Configurable
  via `ingest.date_format`.
- `<camera>` — short camera tag from `--camera` / `ingest.default_camera`,
  slugified (lowercase, `[a-z0-9-]`).
- `<cardlabel>` — filesystem label of the card (`source_label`), slugified; falls
  back to `nolabel` if the card has none.
- `<sequence>` — zero-padded counter (`001`, `002`, …) that makes the id unique for
  a given date+camera+card, incremented until a free directory is found.

Template is configurable via `ingest.import_id_template` with tokens
`{date} {camera} {cardlabel} {seq}`. The same `import_id` is used on **both** tiers.

### import_id conflict rule
If `imports/<import_id>/` (HDD) or `inbox/<import_id>/` (NVMe) already exists, the
run **halts** with a non-zero exit code, unless `--resume` is given — in which case
the existing directories are reused and `rsync --partial` continues the copy.
Without `--resume`, the sequence counter increments to find a fresh id only when
the operator passes `--auto-seq`; otherwise an explicit `--import-id` collision is
an error (never silently overwrite).

## Per-import `_ingest/` artifacts

```
_ingest/
  ingest.json            # canonical machine-readable summary of the run (see fields)
  ingest.log             # human-readable text log
  events.jsonl           # one event object per line (see events)
  source_lsblk.txt       # `lsblk -O <device>` snapshot at ingest time
  source_tree.txt        # full recursive listing of the source as seen
  file_manifest.tsv      # per-file record (see format)
  checksums.sha256       # `sha256sum`-format lines for every copied file
  rsync_to_nvme.log      # rsync stdout/stderr, stage 1
  rsync_to_hdd.log       # rsync stdout/stderr, stage 2
  verification.json      # reconciliation result (counts/sizes/checksums)
  metrics.prom           # Prometheus textfile metrics for this run
```

`_ingest/` is written on the NVMe inbox first and copied to the HDD imports copy so
both tiers are self-describing.

## `ingest.json` fields

```jsonc
{
  "import_id":            "2026-06-01_fuji-avpro-sd_001",
  "schema_version":       1,
  "started_at":           "2026-06-01T15:30:12+02:00",   // ISO 8601
  "finished_at":          "2026-06-01T15:54:03+02:00",
  "status":               "verified",   // pending|running|completed|failed|partial|verified
  "copy_mode":            "dcim",        // dcim|full_card

  "source_device":        "/dev/sdc1",
  "source_label":         "AVPRO-SD",
  "source_uuid":          "1234-ABCD",
  "source_filesystem":    "exfat",
  "source_mountpoint":    "/mnt/photo-ingest/sdc1",
  "source_read_only":     true,
  "source_files_count":   1842,
  "source_bytes":         64236519424,

  "nvme_destination":     "/nvme-mirror/media/inbox/2026-06-01_fuji-avpro-sd_001",
  "hdd_destination":      "/hdd-mirror/archive/media/imports/2026-06-01_fuji-avpro-sd_001",
  "copied_files_count":   1842,
  "copied_bytes":         64236519424,

  "checksum_algorithm":   "sha256",      // sha256|b3sum
  "verification_status":  "ok",          // ok|count_mismatch|size_mismatch|checksum_mismatch|skipped

  "raw_files_count":      1203,
  "photo_files_count":    1203,
  "video_files_count":    34,
  "sidecar_files_count":  402,
  "other_files_count":    0,
  "raw_bytes":            48000000000,
  "photo_bytes":          12000000000,
  "video_bytes":          4000000000,
  "sidecar_bytes":        36519424,
  "other_bytes":          0,

  "errors":               [],            // list of {stage, message}
  "warnings":             []             // list of {stage, message}
}
```

`status` lifecycle: `pending → running → (completed | failed | partial) → verified`.
- `completed` = both copies done; `verified` = copies done **and** verification ok.
- `partial` = a resumable interruption (e.g. an interrupted rsync, free-space stop).
- `failed` = a non-resumable error (wrong device, no DCIM, checksum mismatch).

## File-type classification

By lowercased extension (configurable in `classification:`). Used **only** for
statistics/manifest/metrics — never to filter ingest.

| Class | Extensions |
| --- | --- |
| `raw` | `raf` `raw` `dng` `cr2` `cr3` `nef` `arw` `orf` `rw2` |
| `photo` | `jpg` `jpeg` `heic` `heif` `png` `tif` `tiff` |
| `video` | `mov` `mp4` `m4v` `avi` `mts` `m2ts` |
| `sidecar` | `xmp` `dop` `cos` `xml` `aae` `thm` |
| `other` | everything else (still copied) |

Classification rules:
- Case-insensitive on extension; `.JPG` == `jpg`.
- A file with no extension → `other`.
- Unknown extension → `other` (never skipped, never an error).

## `file_manifest.tsv` format

Tab-separated, one header row, one row per source file. Columns:

| Column | Meaning |
| --- | --- |
| `relative_path` | Path relative to the dump root (e.g. `DCIM/100_FUJI/DSCF0001.RAF`) |
| `file_name` | Basename (`DSCF0001.RAF`) |
| `extension` | Lowercased, no dot (`raf`) |
| `file_class` | `raw`/`photo`/`video`/`sidecar`/`other` |
| `size_bytes` | Integer byte size |
| `mtime` | Source modification time, ISO 8601 |
| `checksum` | `<algo>:<hex>` (e.g. `sha256:ab12…`); empty if checksum skipped |
| `source_root` | Mountpoint the file was read from |
| `copied_to_nvme` | `1`/`0` |
| `copied_to_hdd` | `1`/`0` |

A roll-up copy may also be written to `archive/media/manifests/<import_id>.tsv`.

## `events.jsonl`

One JSON object per line. Common shape:

```jsonc
{"ts":"2026-06-01T15:30:12+02:00","event":"ingest_started","import_id":"2026-06-01_fuji-avpro-sd_001","data":{...}}
```

Event types (in normal order):

| Event | Emitted when |
| --- | --- |
| `ingest_started` | Run begins; config + args resolved |
| `source_detected` | Candidate device identified/validated |
| `source_mounted` | Card mounted read-only |
| `source_scanned` | Recursive scan complete (`source_files_count`, `source_bytes`) |
| `file_classification_finished` | Per-class counts/bytes computed |
| `copy_to_nvme_started` / `copy_to_nvme_finished` | rsync stage 1 |
| `checksum_started` / `checksum_finished` | Checksums over the copied tree |
| `copy_to_hdd_started` / `copy_to_hdd_finished` | rsync stage 2 |
| `verification_started` / `verification_finished` | Reconciliation |
| `ingest_finished` | Terminal success (status completed/verified) |
| `ingest_failed` | Terminal failure (with `data.stage`, `data.message`) |

Every event carries `ts`, `event`, `import_id`, and an `event`-specific `data` object.

## `verification.json`

```jsonc
{
  "import_id": "2026-06-01_fuji-avpro-sd_001",
  "checksum_algorithm": "sha256",
  "mode": "full",                  // full|sample
  "source_vs_nvme":  {"files_ok": true, "bytes_ok": true, "checksums_ok": true, "mismatches": []},
  "nvme_vs_hdd":     {"files_ok": true, "bytes_ok": true, "checksums_ok": true, "mismatches": []},
  "verification_status": "ok"      // ok|count_mismatch|size_mismatch|checksum_mismatch|skipped
}
```

`mismatches` is a list of `{relative_path, reason, expected, actual}` for triage.

## Prometheus metrics (`metrics.prom`)

Textfile-collector format. All gauges/counters carry no per-import label in the
roll-up file except where noted, to keep cardinality low; the per-import
`_ingest/metrics.prom` may add `import_id` for local inspection.

```
# HELP photo_ingest_last_success_timestamp Unix time of last verified ingest.
# TYPE photo_ingest_last_success_timestamp gauge
photo_ingest_last_success_timestamp 1748785443

# TYPE photo_ingest_last_failure_timestamp gauge
photo_ingest_last_failure_timestamp 0

# TYPE photo_ingest_duration_seconds gauge
photo_ingest_duration_seconds 1431

# TYPE photo_ingest_source_bytes gauge
photo_ingest_source_bytes 64236519424

# TYPE photo_ingest_copied_bytes_total counter
photo_ingest_copied_bytes_total 64236519424

# TYPE photo_ingest_files_total gauge
photo_ingest_files_total 1842

photo_ingest_raw_files_total 1203
photo_ingest_photo_files_total 1203
photo_ingest_video_files_total 34
photo_ingest_sidecar_files_total 402
photo_ingest_other_files_total 0

photo_ingest_raw_bytes 48000000000
photo_ingest_photo_bytes 12000000000
photo_ingest_video_bytes 4000000000
photo_ingest_sidecar_bytes 36519424
photo_ingest_other_bytes 0

# TYPE photo_ingest_errors_total counter
photo_ingest_errors_total 0

# TYPE photo_ingest_active gauge   (1 while running, else 0)
photo_ingest_active 0

# TYPE photo_ingest_verification_status gauge
# 0=skipped 1=ok 2=count_mismatch 3=size_mismatch 4=checksum_mismatch
photo_ingest_verification_status 1

# TYPE photo_ingest_runs_total counter
photo_ingest_runs_total 57
```

Metric-name reference (full list):
`photo_ingest_last_success_timestamp`, `photo_ingest_last_failure_timestamp`,
`photo_ingest_duration_seconds`, `photo_ingest_source_bytes`,
`photo_ingest_copied_bytes_total`, `photo_ingest_files_total`,
`photo_ingest_raw_files_total`, `photo_ingest_photo_files_total`,
`photo_ingest_video_files_total`, `photo_ingest_sidecar_files_total`,
`photo_ingest_other_files_total`, `photo_ingest_raw_bytes`,
`photo_ingest_photo_bytes`, `photo_ingest_video_bytes`,
`photo_ingest_sidecar_bytes`, `photo_ingest_other_bytes`,
`photo_ingest_errors_total`, `photo_ingest_active`,
`photo_ingest_verification_status`, `photo_ingest_runs_total`.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success (`completed` or `verified`) |
| `10` | Usage/config error (bad args, missing config) |
| `11` | Source error (no device, no DCIM in dcim mode, mount failed) |
| `12` | Destination error (insufficient free space, unwritable path) |
| `13` | `import_id` conflict without `--resume` |
| `20` | Copy error (rsync failed) |
| `21` | Verification failed (count/size/checksum mismatch) → status `failed`/`partial` |
| `30` | Interrupted/partial (resumable) |

These are stable and intended for automation (systemd, scripts, Uptime Kuma).
