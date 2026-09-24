"""Source-integrity checks.

A load is refused unless the source files are byte-for-byte what the committed
manifest recorded. The dataset was transformed specifically so answers cannot
be looked up in the public IEEE-CIS file; silently loading a different copy
would invalidate every result derived from it.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Read in 8 MB blocks: large enough that hashing a 708 MB file is I/O bound,
# small enough not to hold the file in memory.
_HASH_BLOCK_BYTES = 8 * 1024 * 1024


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_BLOCK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class FileCheck:
    name: str
    present: bool
    expected_bytes: int
    actual_bytes: int | None
    expected_sha256: str
    actual_sha256: str | None

    @property
    def size_ok(self) -> bool:
        return self.actual_bytes == self.expected_bytes

    @property
    def hash_ok(self) -> bool:
        return self.actual_sha256 == self.expected_sha256

    @property
    def ok(self) -> bool:
        return self.present and self.size_ok and self.hash_ok

    def describe(self) -> str:
        if not self.present:
            return f"{self.name}: MISSING"
        if not self.size_ok:
            return f"{self.name}: size {self.actual_bytes} != expected {self.expected_bytes}"
        if not self.hash_ok:
            return f"{self.name}: sha256 mismatch"
        return f"{self.name}: ok"


@dataclass
class IntegrityReport:
    checks: list[FileCheck] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    @property
    def present_and_valid(self) -> list[str]:
        return [check.name for check in self.checks if check.ok]

    @property
    def missing(self) -> list[str]:
        return [check.name for check in self.checks if not check.present]

    @property
    def corrupt(self) -> list[str]:
        return [
            check.name
            for check in self.checks
            if check.present and not (check.size_ok and check.hash_ok)
        ]

    def summary(self) -> str:
        return "\n".join(check.describe() for check in self.checks)


def verify_sources(
    raw_dir: Path,
    manifest_path: Path,
    *,
    required: tuple[str, ...] = (
        "transactions.csv",
        "identity.csv",
        "closed_cases_history.csv",
        "case_pack.csv",
    ),
    compute_hashes: bool = True,
) -> IntegrityReport:
    """Check the raw files against the committed manifest.

    Args:
        raw_dir: where the official CSVs live.
        manifest_path: the committed `data/source-manifest.json`.
        required: files that must be present and valid.
        compute_hashes: set false to skip hashing when only presence and size
            matter; hashing 708 MB takes a few seconds.
    """
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest["files"]

    report = IntegrityReport()
    for name in required:
        entry = files.get(name)
        if entry is None:
            raise KeyError(f"{name} is not described in {manifest_path}")

        path = raw_dir / name
        if not path.exists():
            report.checks.append(
                FileCheck(
                    name=name,
                    present=False,
                    expected_bytes=entry["bytes"],
                    actual_bytes=None,
                    expected_sha256=entry["sha256"],
                    actual_sha256=None,
                )
            )
            continue

        actual_bytes = path.stat().st_size
        actual_hash = sha256_of(path) if compute_hashes else entry["sha256"]
        check = FileCheck(
            name=name,
            present=True,
            expected_bytes=entry["bytes"],
            actual_bytes=actual_bytes,
            expected_sha256=entry["sha256"],
            actual_sha256=actual_hash,
        )
        report.checks.append(check)
        if not check.ok:
            logger.error("source integrity failure: %s", check.describe())

    return report
