# ARCHITECTURE — photo-ingest

## Layering overview

```
┌─────────────────────────────────────────────────────────────────────┐
│ Proxmox host                                                          │
│  • ZFS pools: nvme-mirror (2×2TB), hdd-mirror (2×8TB)                 │
│  • Physical SD card reader (USB) and 10GbE NICs                       │
│  • Passes block storage + the card reader through to the Debian VM    │
│                                                                       │
│   ┌───────────────────────────────────────────────────────────────┐  │
│   │ Debian VM (application layer)                                  │  │
│   │  • Mounts: /nvme-mirror, /hdd-mirror (from host datasets)      │  │
│   │  • Sees the SD card as a block device: /dev/sdX                │  │
│   │  • photo-ingest CLI + systemd units run HERE (host of /dev)    │  │
│   │  • node_exporter (textfile collector) runs here                │  │
│   │                                                                │  │
│   │   ┌─────────────────────────────────────────────────────────┐ │  │
│   │   │ Docker (runtime)                                         │ │  │
│   │   │  • Existing: Grafana, Prometheus, Dozzle, Uptime Kuma,   │ │  │
│   │   │    cAdvisor, Grafana Alloy                               │ │  │
│   │   │  • New (optional): photo-ingest-exporter / future API    │ │  │
│   │   │    — NO privileged /dev access, NO card mounting         │ │  │
│   │   └─────────────────────────────────────────────────────────┘ │  │
│   └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### Proxmox (host layer)
Owns the physical hardware: the two ZFS mirrors, the USB SD card reader, and the
10GbE NICs. Responsible for presenting storage and the card device to the VM.
photo-ingest never runs on the host.

### Debian VM (application layer)
The unit of trust for ingest. It mounts both ZFS tiers and is where the SD card
appears as a block device. **photo-ingest runs here**, as a CLI today and a
systemd service/timer later. This is deliberate: the program that touches
`/dev/sdX` and performs mounts should run in the smallest, most auditable place
that legitimately needs that access — the VM — not inside a container.

### Docker (runtime)
Hosts the existing observability stack and, optionally, a thin photo-ingest
metrics exporter or future HTTP API. Containers here are **unprivileged** and
never see the card device. They read artifacts photo-ingest produced on disk.

## Storage

| Pool | Role | Mounted in VM as | Holds |
| --- | --- | --- | --- |
| `nvme-mirror` (2×2TB) | Ingest inbox + active work | `/nvme-mirror/media` | `inbox/`, `work/`, `tmp/` |
| `hdd-mirror` (2×8TB) | Source archive + completed projects | `/hdd-mirror/archive/media` | `imports/`, `library/`, `projects/`, `exports/`, `manifests/`, `logs/` |

Recommended ZFS datasets (created on the host, mounted into the VM):

```bash
# NVMe tier
zfs create -o mountpoint=/nvme-mirror/media        nvme-mirror/media
zfs create                                          nvme-mirror/media/inbox
zfs create                                          nvme-mirror/media/work

# HDD tier
zfs create -o mountpoint=/hdd-mirror/archive/media hdd-mirror/archive/media
zfs create                                          hdd-mirror/archive/media/imports
zfs create                                          hdd-mirror/archive/media/library
zfs create                                          hdd-mirror/archive/media/exports
```

Recommended ZFS properties: `compression=lz4` (cheap, helps); `atime=off`.
**Do not enable ZFS dedup** on the media pool — see the research report; it is RAM-
hungry and inappropriate for active photo work. Snapshots are the safety net:
snapshot `imports/` before any downstream operation ever touches it.

### How storage is mounted into the VM
Two viable options; pick one and record it in Stage 0:

1. **Datasets mounted on the host, exposed to the VM** via virtio-fs or a bind/
   9p share, or
2. **A dedicated zvol/disk passed to the VM** which the VM formats and mounts.

For a ZFS-on-host setup, option 1 (host owns ZFS, VM consumes a directory mount)
is simplest and keeps snapshots/scrubs on the host. The CLI does not care *how*
the mount happens; it only requires that `nvme_media_root` and `hdd_archive_root`
resolve to writable directories on the expected filesystems.

### How the SD card reader / block device reaches the VM
Options, in order of preference:

1. **USB passthrough of the card reader to the VM** (Proxmox `qm set <vmid>
   -usb0 host=<vendor:product>`). The card then appears as `/dev/sdX` inside the
   VM. Preferred: the reader is dedicated to ingest.
2. **Mount on the host, bind-mount the mountpoint into the VM.** Simpler but the
   host now participates in ingest; less clean.

The card's `/dev/sdX` letter is **not stable** and must never be assumed. The CLI
identifies the source by user-supplied `--source-device`, or by matching
filesystem label / UUID, and validates it is a removable, non-system device
before doing anything (see [AGENTS.md](AGENTS.md) and DATA_MODEL `source_*` fields).

## How ingest is started

| Phase | Trigger | Notes |
| --- | --- | --- |
| **MVP** | Manual: `photo-ingest run --source-device /dev/sdc1 ...` | Operator-driven, explicit device. |
| Later | `systemd` service + `.timer`, or an HTTP API call | Scheduled or on-demand without a shell. |
| Later | `udev` rule fires on card insert → oneshot service | Auto-detect; gated behind strict device validation. Out of MVP. |

## Containers and integrations

| Component | Where it runs | Role |
| --- | --- | --- |
| `photo-ingest` CLI / systemd | Debian VM | The actual ingest. Touches `/dev`, mounts card, runs rsync, writes artifacts. |
| `photo-ingest-exporter` (optional) | Docker (unprivileged) | Serves/relays metrics if textfile collector is not used. |
| node_exporter textfile collector | Debian VM | Reads `metrics.prom` files written by the CLI; Prometheus scrapes it. |
| Prometheus | Docker | Scrapes node_exporter / exporter; stores time series. |
| Grafana | Docker | Dashboards over Prometheus (+ Loki if added). |
| Dozzle | Docker | Tails container logs (exporter/API). VM/systemd logs go via Alloy. |
| Grafana Alloy | Docker/VM | Ships VM journald + JSONL logs to Loki (if/when Loki is added). |
| Uptime Kuma | Docker | Health check on the exporter endpoint / a freshness probe. |
| cAdvisor | Docker | Container resource metrics (already present). |

## Data flow

```
SD card (/dev/sdX, mounted read-only)
   │  rsync (stage 1)
   ▼
/nvme-mirror/media/inbox/<import_id>/DCIM/        + _ingest/ artifacts
   │  rsync (stage 2)
   ▼
/hdd-mirror/archive/media/imports/<import_id>/DCIM/  + _ingest/ artifacts
   │  (post-MVP) copy-derived
   ▼
library/ , work/ , projects/ , exports/
```

The card is read **once**: stage 1 copies card→NVMe, then stage 2 copies the
verified NVMe inbox→HDD (not card→HDD). Verification compares card↔NVMe and
NVMe↔HDD. Reading the card a single time minimizes card wear and total time — the
card/reader/USB is the slow, fragile link.

## Log flow

```
photo-ingest run
   ├── stdout/stderr           → journald (systemd) → Alloy → Loki → Grafana
   ├── <import>/_ingest/ingest.log     (human-readable, per-import)
   └── <import>/_ingest/events.jsonl   (machine-readable event stream)
```

Container components (exporter/API) log to stdout → captured by Docker → Dozzle,
and optionally Alloy → Loki.

## Metrics flow

```
photo-ingest run
   └── writes <import>/_ingest/metrics.prom
        └── (copied/symlinked to) /var/lib/node_exporter/textfile_collector/photo_ingest.prom
             └── node_exporter  ──scrape──►  Prometheus  ──►  Grafana
                                                          └──►  Uptime Kuma (freshness/health)
```

The textfile collector pattern is preferred for the MVP: the CLI is a batch job,
not a long-running server, so it should *write* metrics, not *serve* them. A
long-lived exporter/API is a later option for richer queries.

## Boundaries of responsibility

| Concern | Host (Proxmox) | VM (Debian) | Container (Docker) |
| --- | --- | --- | --- |
| ZFS pools, snapshots, scrubs | ✅ | — | — |
| Pass card device / storage to VM | ✅ | — | — |
| Mount card read-only, run rsync | — | ✅ | ❌ never |
| Classify, manifest, checksum, verify | — | ✅ | ❌ |
| Write logs/metrics artifacts | — | ✅ | — |
| Scrape/store/visualize metrics | — | textfile collector | ✅ Prometheus/Grafana |
| Tail logs | — | journald source | ✅ Dozzle/Alloy |

## Risks of a container with `/dev` access

Running the ingest in a container that is given `--privileged` or
`--device=/dev/sdX` (or worse, `-v /dev:/dev`) is the most dangerous design choice
available here:

- A bug or a wrong device argument can read/write **host block devices**, including
  the system disks and the ZFS members.
- `--privileged` effectively disables container isolation; a compromised or buggy
  container can affect the VM.
- Device passthrough to a container couples ingest correctness to Docker's device
  cgroup state, which is harder to reason about and audit than a plain VM process.
- The unstable `/dev/sdX` naming problem is now spread across two layers.

The benefit (packaging convenience) does not justify the blast radius for a job
whose entire purpose is *not* to damage data.

### Safer alternative (the recommendation)
Run ingest as a **systemd service / CLI in the Debian VM**, where block-device and
mount access is normal and auditable, and use a **container only for the metrics
exporter / future API**, which needs neither `/dev` nor privilege.

## MVP architecture

- **Language:** Python 3.11+. Rationale: rich stdlib for JSON/JSONL/hashlib/paths,
  straightforward unit testing of classification/verification/metrics logic,
  typed code, clean error handling and exit codes — all weak points of Bash for a
  program with this much branching and so many failure modes. `rsync` and
  `b3sum`/`sha256sum` are invoked as subprocesses, so we get rsync's reliability
  without reimplementing it.
- **Copy mechanism:** `rsync -a --partial --info=progress2` (archive mode preserves
  mtimes/perms; `--partial` enables `--resume`). Two stages: card→NVMe, NVMe→HDD.
- **Checksums/manifest:** `sha256sum` by default (`b3sum` opt-in for speed) over
  the copied tree; results recorded in `checksums.sha256` and `file_manifest.tsv`.
- **Event log:** JSONL (`events.jsonl`), one event object per line.
- **Metrics:** Prometheus **textfile collector** `.prom` files (per-import and a
  rolled-up file in the collector dir). A small HTTP exporter is an optional later
  addition, not the MVP path.

## Deployment recommendation

> **Recommendation: ingest = systemd service/CLI in the Debian VM; containers only
> for the optional exporter/API. Do NOT use a privileged, `/dev`-mounting container
> for ingest in the MVP.**

| Option | Pros | Cons | Verdict |
| --- | --- | --- | --- |
| **Container with mount + device access** | One-command packaging; matches existing Docker stack | Needs `--privileged` or device passthrough; large blast radius on host disks; unstable `/dev/sdX` across two layers; harder to audit; couples data safety to Docker device cgroups | ❌ Not for MVP |
| **systemd service/CLI in VM + container for exporter/API** | Block-device/mount access is native and auditable in the VM; minimal privilege; exporter/API stays unprivileged in Docker; clean responsibility split | Two deployment artifacts (a VM package + a container) instead of one | ✅ **Recommended** |

Justification: ingest's defining requirement is *not damaging data on the wrong
device*. The VM is the natural, least-privilege home for code that mounts cards
and runs rsync. Observability is a separate, unprivileged concern that fits the
existing Docker stack perfectly. Splitting them along the privilege boundary keeps
the dangerous part small and the convenient part containerized.
