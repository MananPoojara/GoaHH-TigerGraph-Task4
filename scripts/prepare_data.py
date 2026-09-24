#!/usr/bin/env python
"""Verify the official source files and build TigerGraph load files.

Usage:
    python scripts/prepare_data.py                 # real data in data/raw/
    python scripts/prepare_data.py --fixture       # synthetic data, for dev
    python scripts/prepare_data.py --skip-hashes   # faster, presence only

The load is refused if a source file's size or SHA-256 disagrees with the
committed manifest. The dataset was transformed specifically so answers cannot
be recovered from the public IEEE-CIS file, so quietly loading a different copy
would invalidate every result derived from it.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from fraudlens_contracts import load_case_pack, load_closed_cases  # noqa: E402
from fraudlens_loading import (  # noqa: E402
    assert_supplied_card_ids,
    build_card_mapping,
    preprocess,
    verify_sources,
    write_fixture_dataset,
)

logger = logging.getLogger("prepare_data")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture",
        action="store_true",
        help="generate and use synthetic data instead of the official files",
    )
    parser.add_argument(
        "--skip-hashes",
        action="store_true",
        help="check presence and size but not SHA-256 (faster on the 708 MB file)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="stop after N transaction rows (smoke tests only; produces an "
        "incomplete card mapping that must not be used for scored answers)",
    )
    parser.add_argument("--raw-dir", type=Path, default=REPO_ROOT / "data" / "raw")
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "data" / "processed")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    raw_dir: Path = args.raw_dir
    out_dir: Path = args.out_dir

    if args.fixture:
        raw_dir = REPO_ROOT / "data" / "fixtures" / "generated"
        logger.info("generating synthetic fixture data in %s", raw_dir)
        counts = write_fixture_dataset(raw_dir)
        logger.info("fixture written: %s", counts)
    else:
        logger.info("verifying official sources in %s", raw_dir)
        report = verify_sources(
            raw_dir,
            REPO_ROOT / "data" / "source-manifest.json",
            compute_hashes=not args.skip_hashes,
        )
        print(report.summary())

        if report.missing:
            logger.error(
                "missing source file(s): %s. Download them from the official Drive "
                "folder into %s before loading.",
                ", ".join(report.missing),
                raw_dir,
            )
            return 2
        if report.corrupt:
            logger.error(
                "source file(s) do not match the committed manifest: %s. Re-download "
                "rather than loading a file that is not the official one.",
                ", ".join(report.corrupt),
            )
            return 3

    logger.info("preprocessing into %s", out_dir)
    result = preprocess(raw_dir, out_dir, limit=args.limit)
    print(result.summary())

    if result.rejected_rows:
        logger.warning("%d row(s) rejected; first few:", result.rejected_rows)
        for reason in result.rejections[:10]:
            logger.warning("  %s", reason)

    # The card mapping is a stable identity transform, so it is asserted
    # against every supplied card ID before the load is accepted.
    if not args.fixture and args.limit is None:
        code = _assert_card_mapping(raw_dir)
        if code != 0:
            return code

    print(f"\nLoad files written to {out_dir}")
    print("Next: python scripts/install_graph.py   (needs TG_HOST and a credential in .env)")
    return 0


def _assert_card_mapping(raw_dir: Path) -> int:
    """Check derived card IDs against every supplied one."""
    logger.info("asserting derived card IDs against the supplied ones")
    mapping, _ = build_card_mapping(raw_dir / "transactions.csv")

    supplied: list[tuple[str, str]] = []

    closed_path = raw_dir / "closed_cases_history.csv"
    if closed_path.exists():
        for case in load_closed_cases(closed_path):
            if case.customer_id and case.card_id:
                supplied.append((case.customer_id, case.card_id))
            for card_id in case.connected_card_ids:
                customer = card_id.split("-K")[0]
                supplied.append((customer, card_id))

    pack_path = raw_dir / "case_pack.csv"
    if pack_path.exists():
        for entry in load_case_pack(pack_path):
            supplied.append((entry.customer_id, entry.card_id))

    if not supplied:
        logger.warning("no supplied card IDs available to assert against")
        return 0

    result = assert_supplied_card_ids(mapping, supplied)
    print(result.summary())

    if not result.ok:
        for customer, card, derived in result.mismatches[:10]:
            logger.error("mismatch: %s expected %s, derived {%s}", customer, card, derived)
        for customer, card in result.unresolvable[:10]:
            logger.error("unresolvable: %s / %s", customer, card)
        logger.error(
            "the card derivation rule does not reproduce the supplied IDs; the load "
            "is refused because every downstream ID would be wrong"
        )
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
