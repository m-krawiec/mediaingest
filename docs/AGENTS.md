# AGENTS — rules for humans and AI agents working on photo-ingest

This project moves irreplaceable data off removable media. The cost of a bug is
permanent data loss on the wrong block device. Read this before writing code.

## Prime directives (non-negotiable)

1. **Never delete from, write to, or format the source card.** Ingest is read-only
   at the source, always. No `rm`, no `mkfs`, no `--delete` toward the source, no
   "tidy up the card" feature.
2. **Never filter files by type during ingest.** Classification exists for
   statistics/manifest/metrics only. Every file on the card (or in `DCIM/`, per
   mode) is copied. If a file's class is unknown, it is `other` and still copied.
3. **`imports/` is the immutable source of truth.** Do not move, rename, mutate, or
   delete anything under `imports/`. Derived layers (`library/`, `work/`,
   `projects/`, `exports/`) are built by **copying** from `imports/`, never by
   relocating originals out of it.
4. **Never operate on `/dev` without explicit, validated confirmation.** The card's
   `/dev/sdX` name is not stable. Validate before touching (see "Device safety").
5. **Logs and metrics are mandatory.** Every run writes `ingest.log`,
   `events.jsonl`, `file_manifest.tsv`, `checksums.sha256`, `ingest.json`, and
   `metrics.prom`. A run that can't log is a run that didn't happen safely.

## Data safety rules

- All copy operations must be **idempotent**: re-running the same `import_id` must
  never damage data. Use `rsync --partial`; never `rsync --delete` in the ingest path.
- An `import_id` conflict **halts** (exit `13`) unless `--resume` is passed.
- Prefer `--dry-run` in initial testing and in any new copy/move code path.
- `rm` is permitted **only** within the application's own temp area
  (`<nvme_media_root>/tmp/…`). It must never run on the source, on `imports/`, or
  on any path the program did not itself create this run. No `rm -rf` on a variable
  that could be empty or root — guard against `rm -rf "$x/"` when `$x` is unset.
- Writes go to a temp path + atomic `rename()` for artifacts that observers read
  (e.g. `metrics.prom`), to avoid partial reads.
- Snapshot-friendly: assume ZFS snapshots protect `imports/`; do not design any
  feature that requires mutating `imports/` in place.

## Device safety

- **Do not assume `/dev/sdc1` is the SD card.** Resolve and validate the device
  every run.
- A candidate source device must pass **all** of:
  - it is **removable** (e.g. `/sys/block/<dev>/removable == 1`) **or** explicitly
    confirmed by the operator via `--source-device` plus `--i-know-what-im-doing`;
  - it is **not** a mounted system/root device, not a ZFS pool member, not part of
    `nvme_media_root` / `hdd_archive_root`;
  - its filesystem is an expected card filesystem (exFAT/FAT32/…), or full-card
    mode was explicitly chosen.
- **Never** touch `sda`, `sdb`, `nvme*`, pool members, or the roots' backing devices
  without passing this validation. When in doubt, refuse and ask.
- Mount the card **read-only** (`mount -o ro`); unmount in a `finally`/cleanup path
  so a crash never leaves a dangling mount.
- Avoid destructive commands entirely in the source path. There is no legitimate
  ingest reason to write to the card.

## Configuration rules

- **No hardcoded paths.** Everything comes from `config.yml` / env
  (`NVME_MEDIA_ROOT`, `HDD_ARCHIVE_ROOT`, …). Defaults live in `config.example.yml`,
  not scattered in code.
- `import_id` names must be **predictable** and deterministic from inputs (date,
  camera, card label, sequence). Same inputs → same id.

## Error handling (every one of these must be handled, logged, and exit-coded)

| Condition | Required behavior |
| --- | --- |
| No free space on destination | Stop before copying; exit `12`; status `failed`. |
| No card / device absent | Exit `11`; clear message. |
| No `DCIM/` in `copy_mode=dcim` | Exit `11`; do **not** silently fall back to full-card. |
| Broken/failed mount | Exit `11`; ensure no dangling mount. |
| `import_id` conflict | Exit `13` unless `--resume`. |
| Insufficient permissions | Exit `10`/`11` as appropriate; actionable message. |
| Failed rsync | Exit `20`; preserve partial copy for `--resume`; never delete source. |
| Mismatched file count | Exit `21`; status `failed`; list discrepancy; delete nothing. |
| Mismatched checksums | Exit `21`; status `failed`; list offending files; delete nothing. |

Failures must be visible in **both** logs and metrics
(`photo_ingest_errors_total`, `photo_ingest_last_failure_timestamp`,
`photo_ingest_verification_status`).

## Testing rules

- **Every stage has an acceptance test** (see IMPLEMENTATION_PLAN). Do not mark a
  stage done without them.
- Use a small **test card** (or a loopback image / fixture tree) for automated
  tests; never test destructive paths against real cards.
- Required test cases include: no `DCIM/`, `full-card` mode, interrupted/resumed
  import, `import_id` conflict, no free space, checksum mismatch, idempotent re-run.
- New copy/delete logic must ship with a `--dry-run` path and a test that asserts
  it writes nothing.

## Code-quality rules

- Match the surrounding code's style and idioms (Python 3.11+, typed, stdlib-first).
- Keep dangerous operations (mount, rsync, rm) in small, single-purpose, well-tested
  functions with explicit guards — not inline in orchestration code.
- Subprocess calls (rsync, sha256sum, mount) pass argument **lists**, never shell
  strings; no `shell=True` with interpolated paths.
- Map errors to the typed errors in `errors.py` and the stable exit codes in
  DATA_MODEL; don't invent ad-hoc exit codes.

## For AI agents specifically

- If a task seems to require filtering ingest, deleting a source, moving files out
  of `imports/`, or touching `/dev` without validation — **stop and ask**. These
  contradict the prime directives and are almost certainly a misunderstanding.
- "Classify" never means "skip." Classification annotates; it never gates a copy.
- When unsure which device is the card, do not guess — surface candidates and
  require explicit confirmation.
- Prefer adding a guard + test over adding a feature, when the two conflict.
- Keep `imports/` immutability intact in every change; if a refactor would let
  something write into `imports/`, that refactor is wrong.
