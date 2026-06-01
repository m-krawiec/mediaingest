# PRODUCT_BRIEF — photo-ingest

## Problem

After every shoot, photos and videos live only on SD cards until someone manually
drags them somewhere. That manual step is slow, unlogged, and error-prone:

- Copies are interrupted or partial and nobody notices until the card is reused.
- There is no record of *what* was on the card, *how many* files, or *how big*.
- RAW, JPEG, and video get mixed into ad-hoc folders that differ every time.
- There is no second copy and no integrity proof, so a single bad copy = data loss.
- The card is sometimes formatted before the copy was ever verified.

photo-ingest removes the manual, risky step with a **controlled, logged,
repeatable, two-copy ingest** that runs server-side without a GUI.

## Who it is for

A single professional photographer or a small studio running their own
infrastructure (Proxmox + Debian VM + Docker, ZFS mirrors, 10GbE). The operator
is technical enough to run a command or trigger a service, and wants the server —
not a laptop and not a desktop DAM — to own the safe-offload step.

It is explicitly **not** an editing tool, a culling tool, or a DAM. It feeds those.

## Main use cases

1. **Offload a card after a shoot.** Insert card, run ingest, get two verified
   copies (NVMe staging + HDD archive) plus a manifest, checksums, and a log.
2. **Prove integrity.** Show that the archive copy byte-for-byte matches the card,
   with per-file checksums and a count/size reconciliation.
3. **Know what you have.** Get per-card statistics by file type (RAW / photo /
   video / sidecar / other), in counts and bytes, in machine-readable form.
4. **Monitor ingests centrally.** Surface success/failure, duration, throughput,
   and file-type breakdown in Prometheus/Grafana; logs in Dozzle/Loki; health in
   Uptime Kuma.
5. **Stage for editing later** (post-MVP). Pull a subset of an import onto NVMe
   `work/` for a Lightroom/Capture One project, without touching the archive.

## Basic workflow

```
SD card
→ /nvme-mirror/media/inbox/<import_id>/                     (fast staging copy)
→ /hdd-mirror/archive/media/imports/<import_id>/            (archive copy = source of truth)
→ optionally /hdd-mirror/archive/media/library/raw/         (derived, post-MVP)
→ optionally /hdd-mirror/archive/media/library/photos/      (derived, post-MVP)
→ optionally /hdd-mirror/archive/media/library/videos/      (derived, post-MVP)
→ optionally /nvme-mirror/media/work/<project_id>/          (active editing, post-MVP)
→ optionally /hdd-mirror/archive/media/projects/<project_id>/ (completed sessions, post-MVP)
→ optionally /hdd-mirror/archive/media/exports/immich/<project_id>/ (gallery output, post-MVP)
```

The MVP delivers the first two arrows (card → NVMe inbox → HDD imports) plus the
manifest/checksum/verification/metrics around them. Everything below the second
arrow is designed here but built later.

## Storage roles

```
imports  = full, unchanged card dumps; the source of truth. Immutable.
library  = organized derived view by file type (raw/photos/videos/sidecars/other).
work     = active working copy on NVMe for an editing project.
projects = completed / described sessions, archived on HDD.
exports  = finished outputs, e.g. for Immich.
```

- **imports is never modified, filtered, split, or moved.** Derived layers are
  built *from* imports by copying, never by relocating originals out of imports.
- **library/work/projects/exports are disposable** — they can be regenerated from
  imports. Only imports (plus offsite backup) must be protected.

## File-type assumptions

- **RAW** (`.raf .raw .dng .cr2 .cr3 .nef .arw .orf .rw2`) is the **master**.
- **Photos** (`.jpg .jpeg .heic .heif .png .tif .tiff`) are usable/derivative or
  camera JPEGs; treated as first-class but distinct from RAW.
- **Video** (`.mov .mp4 .m4v .avi .mts .m2ts`) is a separate stream with different
  I/O characteristics and weaker date metadata.
- **Sidecars** (`.xmp .dop .cos .xml .aae .thm`) belong *with* their media and must
  travel together — never dropped.
- **Other** = everything else the camera writes. Also copied, never skipped.

These classes exist for **statistics, manifests, and metrics only**. They never
decide whether a file is copied.

## The ingest principle

**Ingest offloads everything.** The system copies the entire DCIM subtree
(default) or the entire card (`--copy-mode full-card`). It does not filter by
extension, does not deduplicate, does not rename, and does not sort during ingest.
The card dump under `imports/<import_id>/` is a faithful, complete copy.

Rationale: the archive may have evidentiary or commercial value; a partial or
filtered archive is worse than useless because you can't trust it. Selection and
organization are *downstream* concerns, performed on copies.

## Relationship to Lightroom, Immich, and the archive

- **Lightroom Classic / Capture One** keep their catalog/session and previews on a
  **local NVMe on the editing workstation**, never on a network share. They
  reference originals that live in the archive (or a staged `work/` copy over
  10GbE). photo-ingest produces those originals; it is not the catalog.
- **Immich** is a **gallery / browse / share / export layer**, not the RAW archive
  and not the editing tool. The intended pattern is to expose `imports` and/or
  `exports` to Immich as **read-only external libraries** *after* a project is
  frozen — not to make Immich the source of truth. (See the research report for
  Immich's external-library caveats: no album-structure preservation, non-global
  dedup, no `.xmp` writes on read-only libraries.)
- **The archive (`imports/`)** is the source of truth for both worlds. Everything
  else — catalogs, Immich timelines, exports — is derived and rebuildable.

## NVMe vs HDD decision

- **NVMe mirror = ingest staging + working storage.** First landing zone for the
  card and the home of active `work/` projects. NVMe rarely speeds up the *card
  read* (the card/reader/USB is usually the bottleneck) but massively speeds up
  everything *after* import: previews, cache, culling, AI denoise, parallel
  checksums, remote editing over 10GbE.
- **HDD mirror = source archive + completed projects.** Cheap, large, reliable,
  snapshot-friendly. Holds the immutable `imports/` and long-term `projects/`.

This tiering is by **workflow stage**, not "everything fast" or "everything cheap".

## imports vs library vs work vs projects vs exports

| Layer | Tier | Mutable? | Built by | Purpose |
| --- | --- | --- | --- | --- |
| `imports` | HDD | No (immutable) | ingest | Complete card dump, source of truth |
| `inbox` | NVMe | Transient | ingest | Fast staging copy before archive |
| `library` | HDD | Yes (derived) | library builder (post-MVP) | Organized by-type view |
| `work` | NVMe | Yes | stage command (post-MVP) | Active editing project |
| `projects` | HDD | Yes | manual/stage (post-MVP) | Completed/described sessions |
| `exports` | HDD | Yes | export (post-MVP) | Finished outputs, e.g. Immich |

## Why ingest must be controlled, logged, and repeatable

- **Controlled:** an explicit, validated device and mode — never "guess which
  `/dev/sdX` is the card and copy it." Wrong-device copies and accidental writes
  to system disks are the catastrophic failure mode.
- **Logged:** every run writes a human log, a machine-readable JSONL event stream,
  a manifest, and metrics. If you can't see what happened, you can't trust it.
- **Repeatable / idempotent:** re-running the same `import_id` must never corrupt
  data. A conflict halts unless `--resume` is given, which continues a partial
  copy via `rsync --partial` rather than starting over.

## What the system is NOT

- Not an editor, culler, rater, or DAM.
- Not a deduplicator.
- Not an EXIF-sorter (post-MVP, and only ever on copies).
- Not a card formatter or card-eraser — it never writes to or deletes from the source.
- Not an Immich importer (post-MVP).
- Not a backup tool for offsite/3-2-1 (that is a separate downstream concern).
- Not a network share manager.
