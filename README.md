# photo-ingest

Server-side, headless automation for safely offloading photos and videos from SD
cards into a two-tier storage layout (NVMe staging + HDD archive), with full
logging, manifests, checksums, and Prometheus metrics.

> Working name: `photo-ingest`. Repository: `mediaingest`.

## What it does

A single ingest run performs a **full, unfiltered offload** of an SD card:

```
SD card
  → /nvme-mirror/media/inbox/<import_id>/      (fast staging copy)
  → /hdd-mirror/archive/media/imports/<import_id>/  (archive copy = source of truth)
```

It never deletes from the card, never formats it, and never skips files by
extension. File-type classification (RAW / photo / video / sidecar / other) is
computed for **statistics, manifests, and metrics only** — never to filter the copy.

See [docs/PRODUCT_BRIEF.md](docs/PRODUCT_BRIEF.md) for the full rationale.

## Documentation

| Document | Purpose |
| --- | --- |
| [docs/PRODUCT_BRIEF.md](docs/PRODUCT_BRIEF.md) | Problem, users, workflow, scope boundaries |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Proxmox → VM → Docker layering, data/log/metric flow, deployment recommendation |
| [docs/DATA_MODEL.md](docs/DATA_MODEL.md) | Directory layout, `import_id`, `ingest.json`, manifest, events, metrics |
| [docs/MVP_SCOPE.md](docs/MVP_SCOPE.md) | What is in / out of the MVP |
| [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) | Staged build plan with acceptance tests |
| [docs/AGENTS.md](docs/AGENTS.md) | Safety rules for humans and AI agents working on this repo |
| [TODO.md](TODO.md) | Actionable checklist |

## Key decisions (recommended defaults)

- **Language:** Python 3.11+ (stdlib-heavy, easy testing), `rsync` for copies,
  `sha256sum`/`b3sum` for checksums, JSONL for the event log.
- **Deployment:** ingest runs as a **CLI / systemd service in the Debian VM**
  (it needs block-device + mount access). Containers are reserved for the
  optional metrics exporter / future API — **not** a privileged `/dev`-mounting
  container. Rationale in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#deployment-recommendation).
- **Default copy mode:** `dcim` (`--copy-mode full-card` to grab everything).
- **Checksums:** `sha256` by default; `b3sum` opt-in for speed.

## Quick start (planned MVP UX)

```bash
cp config.example.yml /etc/photo-ingest/config.yml   # edit paths
photo-ingest list-devices                            # show candidate block devices
photo-ingest run --source-device /dev/sdc1 --camera fuji --dry-run
photo-ingest run --source-device /dev/sdc1 --camera fuji
```

Status of the CLI itself: **not yet implemented** — this repository currently
contains the design documents and configuration scaffold. Build order is in
[docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md).
