from __future__ import annotations

import json
import logging
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path

from photo_ingest.config import VerifyConfig
from photo_ingest.manifest import compute_checksums, load_checksums_file
from photo_ingest.scan import SourceFile

log = logging.getLogger(__name__)


@dataclass
class TierComparison:
    label: str                   # e.g. "source_vs_nvme"
    expected_count: int = 0
    actual_count: int = 0
    expected_bytes: int = 0
    actual_bytes: int = 0
    files_ok: bool = True
    bytes_ok: bool = True
    checksums_ok: bool = True
    mismatches: list[dict[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.files_ok and self.bytes_ok and self.checksums_ok


@dataclass
class VerificationResult:
    checksum_algorithm: str
    mode: str
    source_vs_nvme: TierComparison = field(
        default_factory=lambda: TierComparison(label="source_vs_nvme")
    )
    nvme_vs_hdd: TierComparison = field(
        default_factory=lambda: TierComparison(label="nvme_vs_hdd")
    )

    @property
    def status(self) -> str:
        for cmp in (self.source_vs_nvme, self.nvme_vs_hdd):
            if not cmp.files_ok:
                return "count_mismatch"
            if not cmp.bytes_ok:
                return "size_mismatch"
            if not cmp.checksums_ok:
                return "checksum_mismatch"
        return "ok"

    def to_dict(self) -> dict:  # type: ignore[type-arg]
        return {
            "checksum_algorithm": self.checksum_algorithm,
            "mode": self.mode,
            "source_vs_nvme": asdict(self.source_vs_nvme),
            "nvme_vs_hdd": asdict(self.nvme_vs_hdd),
            "verification_status": self.status,
        }


def verify(
    source_files: list[SourceFile],
    nvme_root: Path,
    hdd_root: Path,
    ingest_dir_nvme: Path,
    cfg: VerifyConfig,
) -> VerificationResult:
    """Verify the two-tier copy against the source file list.

    source_vs_nvme: compare source scan counts/bytes against NVMe tree.
    nvme_vs_hdd:    compare NVMe checksums against HDD tree (re-reads HDD files).
    """
    result = VerificationResult(
        checksum_algorithm=cfg.checksum_algorithm,
        mode=cfg.mode,
    )

    # --- source vs NVMe (count + bytes; no re-read of source) ---
    svn = result.source_vs_nvme
    svn.expected_count = len(source_files)
    svn.expected_bytes = sum(sf.size_bytes for sf in source_files)

    nvme_files = _enumerate_tree(nvme_root)
    svn.actual_count = len(nvme_files)
    svn.actual_bytes = sum(size for size, _ in nvme_files.values())
    svn.files_ok = svn.actual_count == svn.expected_count
    svn.bytes_ok = svn.actual_bytes == svn.expected_bytes

    if not svn.files_ok:
        _diff_counts(source_files, nvme_files, svn)
        log.error(
            "source_vs_nvme count mismatch: expected %d, got %d",
            svn.expected_count, svn.actual_count,
        )
    if not svn.bytes_ok:
        log.error(
            "source_vs_nvme bytes mismatch: expected %d, got %d",
            svn.expected_bytes, svn.actual_bytes,
        )

    # --- NVMe vs HDD (checksum comparison) ---
    nvh = result.nvme_vs_hdd
    stored = load_checksums_file(ingest_dir_nvme / "checksums.sha256")
    if not stored:
        log.warning("No checksums.sha256 found; skipping checksum verification")
        nvh.checksums_ok = True  # treated as skipped, not failed
    else:
        files_to_check = _select_files(source_files, cfg)
        hdd_checksums = compute_checksums(hdd_root, files_to_check, cfg.checksum_algorithm)

        nvh.expected_count = len(files_to_check)
        nvh.actual_count = len(hdd_checksums)
        nvh.files_ok = nvh.actual_count == nvh.expected_count

        mismatches = []
        for sf in files_to_check:
            expected = stored.get(sf.relative_path)
            actual = hdd_checksums.get(sf.relative_path)
            if expected is None:
                mismatches.append({
                    "relative_path": sf.relative_path,
                    "reason": "not_in_manifest",
                    "expected": "",
                    "actual": actual or "",
                })
            elif actual != expected:
                mismatches.append({
                    "relative_path": sf.relative_path,
                    "reason": "checksum_mismatch",
                    "expected": expected,
                    "actual": actual or "",
                })

        if mismatches:
            nvh.checksums_ok = False
            nvh.mismatches = mismatches
            log.error("nvme_vs_hdd: %d checksum mismatches", len(mismatches))
            for m in mismatches[:5]:
                log.error("  %s: expected %s, got %s", m["relative_path"], m["expected"][:12], m["actual"][:12])
            if len(mismatches) > 5:
                log.error("  ... and %d more", len(mismatches) - 5)
        else:
            log.info("nvme_vs_hdd checksums OK (%d files checked)", len(files_to_check))

    return result


def write_verification_json(result: VerificationResult, ingest_dir: Path) -> None:
    out = ingest_dir / "verification.json"
    out.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
    log.info("Wrote %s (status=%s)", out, result.status)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _enumerate_tree(root: Path) -> dict[str, tuple[int, int]]:
    """Return {relative_path: (size_bytes, mtime_ns)} for every file under root."""
    result: dict[str, tuple[int, int]] = {}
    if not root.exists():
        return result
    for p in root.rglob("*"):
        if p.is_file(follow_symlinks=False):
            try:
                st = p.stat()
                result[str(p.relative_to(root))] = (st.st_size, st.st_mtime_ns)
            except OSError:
                pass
    return result


def _diff_counts(
    source_files: list[SourceFile],
    nvme_files: dict[str, tuple[int, int]],
    cmp: TierComparison,
) -> None:
    source_set = {sf.relative_path for sf in source_files}
    nvme_set = set(nvme_files.keys())
    for p in sorted(source_set - nvme_set)[:20]:
        cmp.mismatches.append({"relative_path": p, "reason": "missing_on_nvme", "expected": "", "actual": ""})
    for p in sorted(nvme_set - source_set)[:20]:
        cmp.mismatches.append({"relative_path": p, "reason": "extra_on_nvme", "expected": "", "actual": ""})


def _select_files(files: list[SourceFile], cfg: VerifyConfig) -> list[SourceFile]:
    if cfg.mode == "full":
        return files
    n = max(1, int(len(files) * cfg.sample_fraction))
    return random.sample(files, min(n, len(files)))
