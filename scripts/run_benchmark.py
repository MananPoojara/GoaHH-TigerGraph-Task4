#!/usr/bin/env python
"""Run the benchmark cases and write validated answer files.

Usage:
    python scripts/run_benchmark.py                  # all cases in the pack
    python scripts/run_benchmark.py --case HHG-001   # one case
    python scripts/run_benchmark.py --chronological  # time-ordered, memory on

Every answer is validated before it is written. A case that fails validation
is reported and its file is withheld rather than shipped broken, because a
malformed answer scores zero for that part regardless.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.core.config import get_settings  # noqa: E402
from app.services.registry import Runtime  # noqa: E402
from fraudlens_contracts.validation import validate_answer  # noqa: E402
from fraudlens_investigator import Trigger, build_answer, run_investigation  # noqa: E402

logger = logging.getLogger("run_benchmark")


class GraphResolver:
    """Dataset lookups for the validator, backed by the graph client."""

    def __init__(self, graph) -> None:
        self._graph = graph
        self._fixture = hasattr(graph, "transactions")

    def transaction_exists(self, txn_id: str) -> bool:
        if self._fixture:
            return txn_id in self._graph.transactions
        result = self._graph.run(
            "get_case_anchor", {"txn_id": txn_id, "card_id": "", "customer_id": ""}
        )
        return bool(result and result[0].get("anchor"))

    def card_exists(self, card_id: str) -> bool:
        return card_id in self._graph.cards if self._fixture else True

    def customer_exists(self, customer_id: str) -> bool:
        return customer_id in self._graph.customers if self._fixture else True

    def closed_case_exists(self, case_id: str) -> bool:
        return case_id in self._graph.closed_cases if self._fixture else True

    def transaction_amount(self, txn_id: str) -> float | None:
        if self._fixture:
            row = self._graph.transactions.get(txn_id)
            return None if row is None else row.amount
        return None

    def transaction_timestamp(self, txn_id: str) -> datetime | None:
        if self._fixture:
            row = self._graph.transactions.get(txn_id)
            return None if row is None else row.ts
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", help="run only this case ID")
    parser.add_argument(
        "--chronological",
        action="store_true",
        help="run in opened-at order so earlier cases become memory for later ones",
    )
    # The challenge requires the answer files in `cases/` at the repo root.
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "cases")
    parser.add_argument(
        "--fixture",
        action="store_true",
        help="use the synthetic fixture case pack instead of the official one, so "
        "the pipeline can be demonstrated before the 708 MB file is in place",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    # The per-case logs are useful but drown the summary; keep the summary readable.
    logging.getLogger("fraudlens_graph").setLevel(logging.WARNING)
    logging.getLogger("fraudlens_investigator").setLevel(logging.WARNING)

    runtime = Runtime(get_settings())
    if args.fixture:
        # The fixture pack anchors on synthetic customers, so it must be paired
        # with the fixture-derived load files rather than the official ones.
        from fraudlens_contracts import load_case_pack

        pack_path = REPO_ROOT / "data" / "fixtures" / "generated" / "case_pack.csv"
        if not pack_path.exists():
            logger.error(
                "no fixture case pack at %s. Run: python scripts/prepare_data.py --fixture",
                pack_path,
            )
            return 2
        runtime._case_pack = load_case_pack(pack_path)

    graph = runtime.graph
    entries = runtime.case_pack

    if not entries:
        logger.error(
            "no case pack found. Put case_pack.csv in data/raw/ and run "
            "scripts/prepare_data.py first."
        )
        return 2

    if args.case:
        entries = [entry for entry in entries if entry.case_id == args.case]
        if not entries:
            logger.error("case %s is not in the pack", args.case)
            return 2

    if args.chronological:
        entries = sorted(entries, key=lambda entry: entry.opened_at)

    logger.info(
        "running %d case(s) against the %s backend (llm=%s)",
        len(entries),
        runtime.backend_name,
        "on" if runtime.llm.available else "deterministic",
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    resolver = GraphResolver(graph)

    written = 0
    failed: list[str] = []
    rows: list[tuple[str, str, float, str, float, bool, int]] = []

    for entry in entries:
        trigger = Trigger(
            case_id=entry.case_id,
            trigger_type=entry.trigger_type,
            trigger_text=entry.trigger_text,
            flagged_txn_id=entry.flagged_txn_id,
            card_id=entry.card_id,
            customer_id=entry.customer_id,
            opened_at=entry.opened_at,
            risk_score=entry.risk_score,
        )

        try:
            state = run_investigation(trigger, graph, runtime.llm).state
            answer = build_answer(state)
        except Exception:
            logger.exception("case %s failed to complete", entry.case_id)
            failed.append(entry.case_id)
            continue

        report = validate_answer(answer, resolver)
        if not report.ok:
            logger.error("case %s failed validation:\n%s", entry.case_id, report.summary())
            failed.append(entry.case_id)
            continue

        path = args.out_dir / f"{entry.case_id}.json"
        path.write_text(
            json.dumps(answer.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8"
        )
        written += 1

        rows.append(
            (
                entry.case_id,
                answer.case.verdict.value,
                answer.case.fraud_probability,
                answer.case.pattern.value,
                answer.case.exposure_usd,
                answer.sar.file,
                answer.tool_calls,
            )
        )

    _print_summary(rows, written, failed, args.out_dir)
    return 1 if failed else 0


def _print_summary(rows, written: int, failed: list[str], out_dir: Path) -> None:
    print()
    print(
        f"{'case':<10} {'verdict':<11} {'prob':>5} {'pattern':<28} {'exposure':>11} {'sar':>4} {'calls':>6}"
    )
    print("-" * 82)
    for case_id, verdict, probability, pattern, exposure, sar, calls in rows:
        print(
            f"{case_id:<10} {verdict:<11} {probability:>5.2f} {pattern:<28} "
            f"{exposure:>11,.2f} {'yes' if sar else 'no':>4} {calls:>6}"
        )

    print()
    print(f"{written} answer file(s) written to {out_dir}")
    if failed:
        print(f"FAILED: {', '.join(failed)}")
    else:
        verdicts = [row[1] for row in rows]
        fraud = verdicts.count("fraud")
        legit = verdicts.count("legitimate")
        uncertain = verdicts.count("uncertain")
        reports = sum(1 for row in rows if row[5])
        print(
            f"verdicts: {fraud} fraud, {legit} legitimate, {uncertain} uncertain · "
            f"{reports} report(s) recommended"
        )


if __name__ == "__main__":
    raise SystemExit(main())
