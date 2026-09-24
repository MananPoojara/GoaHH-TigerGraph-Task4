"""In-memory stand-in for TigerGraph, over preprocessed load files.

Why this exists
---------------
Tests must be able to assert graph semantics without a live workspace, and the
UI has to be demonstrable before one is provisioned. This class implements the
same installed-query contract as `TigerGraphClient` and returns the same result
shapes.

What it is not
--------------
It is not an alternative to TigerGraph. Each method here mirrors a query that
is written in GSQL under `graph/queries/`; the GSQL is authoritative and is
what a scored run executes. Where the two could drift, the GSQL wins, and the
integration tests exist to catch drift once a workspace is available.

Cutoff handling is duplicated faithfully on purpose: a temporal-leak bug that
only reproduced against the real backend would be found far too late.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .client import ALLOWED_READ_QUERIES, ALLOWED_WRITE_QUERIES, CallLog, GraphError

logger = logging.getLogger(__name__)

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


def _parse_ts(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        raise ValueError("empty timestamp")
    return datetime.strptime(text, TIMESTAMP_FORMAT)


def _fmt(value: datetime | None) -> str:
    return value.strftime(TIMESTAMP_FORMAT) if value else ""


@dataclass
class _Row:
    """One transaction, already typed."""

    txn_id: str
    customer_id: str
    card_id: str
    ts: datetime
    amount: float
    product_cd: str
    channel: str
    risk_score: float
    addr1: str
    addr2: str
    p_email: str
    r_email: str
    device_profile_id: str
    device_is_new: bool
    proxy_status: str
    match_status: str


@dataclass
class _StoredCase:
    """A case written back during a run."""

    attributes: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    transactions: list[str] = field(default_factory=list)
    connected_cards: list[str] = field(default_factory=list)
    devices: list[str] = field(default_factory=list)
    similar: list[str] = field(default_factory=list)


class FixtureGraphClient:
    """Installed-query semantics over preprocessed CSVs. Test double only."""

    backend = "fixture"

    def __init__(self, processed_dir: Path, *, call_log: CallLog | None = None) -> None:
        self.processed_dir = Path(processed_dir)
        self.call_log = call_log or CallLog()

        self.transactions: dict[str, _Row] = {}
        self.by_card: dict[str, list[_Row]] = defaultdict(list)
        self.by_customer: dict[str, list[_Row]] = defaultdict(list)
        self.by_device: dict[str, list[_Row]] = defaultdict(list)
        self.by_region: dict[str, list[_Row]] = defaultdict(list)
        self.by_recipient_email: dict[str, list[_Row]] = defaultdict(list)
        self.cards: dict[str, dict[str, str]] = {}
        self.customers: dict[str, dict[str, str]] = {}
        self.devices: dict[str, dict[str, str]] = {}
        self.closed_cases: dict[str, dict[str, Any]] = {}
        self.written_cases: dict[str, _StoredCase] = {}

        self._load()

    # -- loading -----------------------------------------------------------

    def _read(self, name: str) -> list[dict[str, str]]:
        path = self.processed_dir / name
        if not path.exists():
            return []
        with path.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    def _load(self) -> None:
        for raw in self._read("transactions.csv"):
            try:
                row = _Row(
                    txn_id=raw["txn_id"],
                    customer_id=raw["customer_id"],
                    card_id=raw["card_id"],
                    ts=_parse_ts(raw["ts"]),
                    amount=float(raw["amount"]),
                    product_cd=raw["product_cd"],
                    channel=raw["channel"],
                    risk_score=float(raw["risk_score"] or 0.0),
                    addr1=raw.get("addr1", ""),
                    addr2=raw.get("addr2", ""),
                    p_email=raw.get("p_email", ""),
                    r_email=raw.get("r_email", ""),
                    device_profile_id=raw.get("device_profile_id", ""),
                    device_is_new=raw.get("device_is_new", "") == "true",
                    proxy_status=raw.get("proxy_status", ""),
                    match_status=raw.get("match_status", ""),
                )
            except (KeyError, ValueError):
                logger.exception("skipping malformed processed row")
                raise

            self.transactions[row.txn_id] = row
            self.by_card[row.card_id].append(row)
            self.by_customer[row.customer_id].append(row)
            if row.device_profile_id:
                self.by_device[row.device_profile_id].append(row)
            if row.addr1:
                self.by_region[row.addr1].append(row)
            if row.r_email:
                self.by_recipient_email[row.r_email].append(row)

        for bucket in (self.by_card, self.by_customer, self.by_device, self.by_region):
            for rows in bucket.values():
                rows.sort(key=lambda item: (item.ts, item.txn_id))

        self.cards = {row["card_id"]: row for row in self._read("cards.csv")}
        self.customers = {row["customer_id"]: row for row in self._read("customers.csv")}
        self.devices = {row["device_id"]: row for row in self._read("devices.csv")}

        for row in self._read("closed_cases.csv"):
            self.closed_cases[row["case_id"]] = dict(row)

        links: dict[str, list[str]] = defaultdict(list)
        for link in self._read("closed_case_txns.csv"):
            links[link["case_id"]].append(link["txn_id"])
        for case_id, txn_ids in links.items():
            if case_id in self.closed_cases:
                self.closed_cases[case_id]["txn_ids"] = txn_ids

        # Which device profiles each closed case touched. Derived once here
        # because it is the link `find_similar_cases` traverses most.
        for case in self.closed_cases.values():
            device_ids = {
                self.transactions[txn_id].device_profile_id
                for txn_id in case.get("txn_ids", [])
                if txn_id in self.transactions and self.transactions[txn_id].device_profile_id
            }
            case["device_ids"] = sorted(device_ids)

        logger.info(
            "fixture graph loaded: %d transactions, %d cards, %d devices, %d closed cases",
            len(self.transactions),
            len(self.cards),
            len(self.devices),
            len(self.closed_cases),
        )

    # -- dispatch ----------------------------------------------------------

    def is_live(self) -> bool:
        return False

    def run(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        if query not in ALLOWED_READ_QUERIES and query not in ALLOWED_WRITE_QUERIES:
            raise GraphError(query, "query is not in the allow-list")

        handler = getattr(self, f"_q_{query}", None)
        if handler is None:
            raise GraphError(query, "not implemented by the fixture backend")

        started = time.perf_counter()
        result = handler(params)
        latency_ms = (time.perf_counter() - started) * 1000
        self.call_log.record(query, latency_ms)
        return result

    # -- read queries ------------------------------------------------------

    def _q_get_case_anchor(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        txn_id = str(params["txn_id"])
        card_id = str(params.get("card_id", ""))
        customer_id = str(params.get("customer_id", ""))

        errors: list[str] = []
        row = self.transactions.get(txn_id)
        if row is None:
            errors.append("flagged transaction not found")
            return [{"anchor": [], "card": [], "customer": [], "integrity_errors": errors}]

        if card_id and row.card_id != card_id:
            errors.append("flagged transaction is not on the supplied card")
        if customer_id and row.customer_id != customer_id:
            errors.append("supplied card does not belong to the supplied customer")

        return [
            {
                "anchor": [
                    {
                        "txn_id": row.txn_id,
                        "ts": _fmt(row.ts),
                        "amount": row.amount,
                        "product_cd": row.product_cd,
                        "channel": row.channel,
                        "risk_score": row.risk_score,
                        "addr1": row.addr1,
                        "addr2": row.addr2,
                        "p_email": row.p_email,
                        "r_email": row.r_email,
                        "device_profile_id": row.device_profile_id,
                        "device_is_new": row.device_is_new,
                        "proxy_status": row.proxy_status,
                        "match_status": row.match_status,
                    }
                ],
                "card": [self.cards.get(row.card_id, {})],
                "customer": [self.customers.get(row.customer_id, {})],
                "integrity_errors": errors,
            }
        ]

    def _q_get_card_window(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        card_id = str(params["card_id"])
        anchor_ts = _parse_ts(params["anchor_ts"])
        cutoff = _parse_ts(params["cutoff"])
        start = anchor_ts - timedelta(hours=int(params.get("hours_before", 72)))
        end = anchor_ts + timedelta(hours=int(params.get("hours_after", 72)))
        # Never look past the decision time, whatever the caller asked for.
        end = min(end, cutoff)
        limit = int(params.get("max_results", 200))

        window = [row for row in self.by_card.get(card_id, []) if start <= row.ts <= end][:limit]

        previous_ts: datetime | None = None
        entries = []
        for row in window:
            gap = -1.0 if previous_ts is None else (row.ts - previous_ts).total_seconds() / 3600
            previous_ts = row.ts
            entries.append(
                {
                    "txn_id": row.txn_id,
                    "ts": _fmt(row.ts),
                    "amount": row.amount,
                    "product_cd": row.product_cd,
                    "channel": row.channel,
                    "risk_score": row.risk_score,
                    "addr1": row.addr1,
                    "p_email": row.p_email,
                    "device_profile_id": row.device_profile_id,
                    "device_is_new": row.device_is_new,
                    "proxy_status": row.proxy_status,
                    "hours_since_prev": round(gap, 4),
                }
            )

        return [
            {
                "window": entries,
                "online_count": sum(1 for r in window if r.channel == "online"),
                "in_person_count": sum(1 for r in window if r.channel == "in_person"),
                "total_amount": round(sum(abs(r.amount) for r in window), 2),
                "devices": sorted({r.device_profile_id for r in window if r.device_profile_id}),
                "regions": sorted({r.addr1 for r in window if r.addr1}),
                "window_start": _fmt(start),
                "window_end": _fmt(end),
            }
        ]

    def _q_get_customer_baseline(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        customer_id = str(params["customer_id"])
        cutoff = _parse_ts(params["cutoff"])
        start = cutoff - timedelta(days=int(params.get("lookback_days", 180)))

        # Strictly before the cutoff: the flagged transaction is not part of
        # the baseline it is compared against.
        rows = [row for row in self.by_customer.get(customer_id, []) if start <= row.ts < cutoff]

        amounts = [abs(row.amount) for row in rows]
        count = len(amounts)
        mean = sum(amounts) / count if count else 0.0
        variance = sum((value - mean) ** 2 for value in amounts) / count if count else 0.0

        region_counts: dict[str, int] = defaultdict(int)
        product_counts: dict[str, int] = defaultdict(int)
        for row in rows:
            if row.addr1:
                region_counts[row.addr1] += 1
            product_counts[row.product_cd] += 1

        return [
            {
                "txn_count": count,
                "mean_amount": round(mean, 4),
                "std_amount": round(variance**0.5, 4),
                "online_count": sum(1 for r in rows if r.channel == "online"),
                "in_person_count": sum(1 for r in rows if r.channel == "in_person"),
                "known_regions": sorted(region_counts),
                "region_counts": dict(region_counts),
                "known_products": sorted(product_counts),
                "product_counts": dict(product_counts),
                "known_devices": sorted({r.device_profile_id for r in rows if r.device_profile_id}),
                "known_email_domains": sorted({r.p_email for r in rows if r.p_email}),
                "lookback_start": _fmt(start),
                "cutoff": _fmt(cutoff),
            }
        ]

    def _q_detect_card_testing(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        card_id = str(params["card_id"])
        cutoff = _parse_ts(params["cutoff"])
        start = cutoff - timedelta(hours=int(params.get("window_hours", 24)))
        small_max = float(params.get("small_amount_max", 5.0))

        rows = [row for row in self.by_card.get(card_id, []) if start <= row.ts <= cutoff]
        small = [r for r in rows if r.channel == "online" and abs(r.amount) <= small_max]

        # R5 requires three or more small authorizations "within an hour", so
        # find the tightest run of three that actually satisfies that, rather
        # than counting every small charge in a 24-hour window.
        run: list[_Row] = []
        for index in range(len(small)):
            window_run = [
                r for r in small[index:] if (r.ts - small[index].ts).total_seconds() <= 3600
            ]
            if len(window_run) > len(run):
                run = window_run

        # A larger purchase only completes the pattern if it comes after the
        # testing run. Purchases before it are ordinary activity.
        if len(run) >= 3:
            sequence_end = run[-1].ts
            larger = [r for r in rows if abs(r.amount) > small_max and r.ts >= sequence_end]
        else:
            larger = []

        return [
            {
                "sequence": [
                    {"txn_id": r.txn_id, "ts": _fmt(r.ts), "amount": r.amount, "channel": r.channel}
                    for r in rows
                ],
                "small_online_count": len(run),
                "small_txn_ids": [r.txn_id for r in run],
                "within_one_hour": len(run) >= 3,
                "span_seconds": int((run[-1].ts - run[0].ts).total_seconds()) if run else 0,
                "small_online_count_in_window": len(small),
                "larger_txn_ids": [r.txn_id for r in larger],
                "window_start": _fmt(start),
                "cutoff": _fmt(cutoff),
                "small_amount_threshold": small_max,
            }
        ]

    def _q_detect_cnp_burst(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        card_id = str(params["card_id"])
        cutoff = _parse_ts(params["cutoff"])
        start = cutoff - timedelta(hours=int(params.get("window_hours", 48)))

        rows = [
            row
            for row in self.by_card.get(card_id, [])
            if row.channel == "online" and start <= row.ts <= cutoff
        ]
        return [
            {
                "online_transactions": [
                    {
                        "txn_id": r.txn_id,
                        "ts": _fmt(r.ts),
                        "amount": r.amount,
                        "product_cd": r.product_cd,
                        "device_profile_id": r.device_profile_id,
                        "device_is_new": r.device_is_new,
                        "proxy_status": r.proxy_status,
                    }
                    for r in rows
                ],
                "online_count": len(rows),
                "burst_amount": round(sum(abs(r.amount) for r in rows), 2),
                "new_device_count": sum(1 for r in rows if r.device_is_new),
                "proxied_count": sum(
                    1 for r in rows if r.proxy_status and r.proxy_status != "transparent"
                ),
                "device_ids": sorted({r.device_profile_id for r in rows if r.device_profile_id}),
            }
        ]

    def _q_detect_region_anomaly(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        customer_id = str(params["customer_id"])
        cutoff = _parse_ts(params["cutoff"])
        window_start = cutoff - timedelta(hours=int(params.get("window_hours", 72)))
        baseline_start = window_start - timedelta(days=int(params.get("baseline_days", 120)))

        rows = self.by_customer.get(customer_id, [])
        baseline = [r for r in rows if baseline_start <= r.ts < window_start and r.addr1]
        recent = [r for r in rows if window_start <= r.ts <= cutoff and r.addr1]

        baseline_counts: dict[str, int] = defaultdict(int)
        for row in baseline:
            baseline_counts[row.addr1] += 1

        window_counts: dict[str, int] = defaultdict(int)
        for row in recent:
            window_counts[row.addr1] += 1

        novel = sorted(region for region in window_counts if region not in baseline_counts)
        concurrent_home = sum(
            count for region, count in window_counts.items() if region in baseline_counts
        )

        return [
            {
                "baseline_regions": dict(baseline_counts),
                "window_regions": dict(window_counts),
                "novel_regions": novel,
                "in_person_window_count": sum(1 for r in recent if r.channel == "in_person"),
                "concurrent_home_region_count": concurrent_home,
            }
        ]

    def _q_detect_account_takeover(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        customer_id = str(params["customer_id"])
        cutoff = _parse_ts(params["cutoff"])
        start = cutoff - timedelta(hours=int(params.get("window_hours", 72)))

        rows = [r for r in self.by_customer.get(customer_id, []) if start <= r.ts <= cutoff]
        return [
            {
                "cards_active": sorted({r.card_id for r in rows}),
                "online_count": sum(1 for r in rows if r.channel == "online"),
                "in_person_count": sum(1 for r in rows if r.channel == "in_person"),
                "new_device_count": sum(1 for r in rows if r.device_is_new),
                "new_devices": sorted(
                    {r.device_profile_id for r in rows if r.device_is_new and r.device_profile_id}
                ),
                "match_anomaly_count": sum(
                    1 for r in rows if r.match_status and "match_status:2" not in r.match_status
                ),
                "devices_used": sorted({r.device_profile_id for r in rows if r.device_profile_id}),
                "email_domains": sorted({r.p_email for r in rows if r.p_email}),
            }
        ]

    def _q_detect_recurring_charge(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        card_id = str(params["card_id"])
        amount = abs(float(params["amount"]))
        product_cd = str(params.get("product_cd", ""))
        cutoff = _parse_ts(params["cutoff"])
        start = cutoff - timedelta(days=int(params.get("lookback_days", 180)))
        tolerance = float(params.get("amount_tolerance", 1.0))

        # Strictly before the cutoff: the disputed charge is not evidence that
        # it is itself recurring.
        matches = [
            row
            for row in self.by_card.get(card_id, [])
            if start <= row.ts < cutoff
            and row.product_cd == product_cd
            and abs(abs(row.amount) - amount) <= tolerance
        ]
        return [
            {
                "prior_matching_charges": [
                    {"txn_id": r.txn_id, "ts": _fmt(r.ts), "amount": r.amount} for r in matches
                ],
                "match_count": len(matches),
                "lookback_start": _fmt(start),
                "cutoff": _fmt(cutoff),
                "target_amount": amount,
                "target_product": product_cd,
            }
        ]

    def _q_get_shared_origin_ring(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        kind = str(params["origin_kind"])
        origin_id = str(params["origin_id"])
        exclude = str(params.get("exclude_card_id", ""))
        cutoff = _parse_ts(params["cutoff"])
        start = cutoff - timedelta(hours=int(params.get("window_hours", 720)))
        max_cards = int(params.get("max_cards", 50))

        source = {
            "device": self.by_device,
            "region": self.by_region,
            "recipient_email": self.by_recipient_email,
        }.get(kind)
        if source is None:
            raise GraphError("get_shared_origin_ring", f"unknown origin kind {kind!r}")

        rows = [row for row in source.get(origin_id, []) if start <= row.ts <= cutoff]
        connected_cards = sorted({r.card_id for r in rows if r.card_id != exclude})[:max_cards]
        connected_customers = sorted({r.customer_id for r in rows if r.card_id != exclude})

        # Which connected cards already carry confirmed fraud the bank closed
        # before this cutoff?
        prior_cases: list[str] = []
        cards_with_fraud: list[str] = []
        for case in self.closed_cases.values():
            if case.get("outcome") != "confirmed_fraud":
                continue
            closed_at = case.get("closed_at")
            if closed_at and _parse_ts(closed_at) >= cutoff:
                continue
            if case.get("card_id") in connected_cards:
                prior_cases.append(case["case_id"])
                cards_with_fraud.append(case["card_id"])

        return [
            {
                "origin_kind": kind,
                "origin_id": origin_id,
                "connected_cards": connected_cards,
                "connected_customers": connected_customers,
                "ring_txn_ids": [r.txn_id for r in rows],
                "ring_txn_count": len(rows),
                "prior_fraud_cases": sorted(set(prior_cases)),
                "cards_with_prior_fraud": sorted(set(cards_with_fraud)),
                "window_start": _fmt(start),
                "cutoff": _fmt(cutoff),
            }
        ]

    def _q_find_device_connections(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        card_id = str(params["card_id"])
        cutoff = _parse_ts(params["cutoff"])
        start = cutoff - timedelta(hours=int(params.get("window_hours", 720)))

        rows = [
            r
            for r in self.by_card.get(card_id, [])
            if r.device_profile_id and start <= r.ts <= cutoff
        ]
        counts: dict[str, int] = defaultdict(int)
        new_ids: set[str] = set()
        for row in rows:
            counts[row.device_profile_id] += 1
            if row.device_is_new:
                new_ids.add(row.device_profile_id)

        devices = []
        for device_id, count in sorted(counts.items()):
            meta = self.devices.get(device_id, {})
            # Fan-out is recomputed as of the cutoff, never read from a
            # whole-graph attribute computed later.
            observed = [r for r in self.by_device.get(device_id, []) if r.ts <= cutoff]
            devices.append(
                {
                    "device_id": device_id,
                    "readable": meta.get("readable", ""),
                    "any_new": device_id in new_ids,
                    "txn_count": count,
                    "card_fanout": len({r.card_id for r in observed}),
                    "customer_fanout": len({r.customer_id for r in observed}),
                    "proxy_status": meta.get("proxy_status", ""),
                }
            )

        return [{"devices": devices, "new_device_ids": sorted(new_ids)}]

    def _q_find_similar_cases(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        customer_id = str(params.get("customer_id", ""))
        card_id = str(params.get("card_id", ""))
        device_ids = set(params.get("device_ids") or [])
        pattern_hint = str(params.get("pattern_hint", ""))
        cutoff = _parse_ts(params["cutoff"])
        limit = int(params.get("max_cases", 5))

        scores: dict[str, float] = {}
        reasons: dict[str, str] = {}

        def bump(case_id: str, score: float, reason: str) -> None:
            if score > scores.get(case_id, 0.0):
                scores[case_id] = score
                reasons[case_id] = reason

        for case in self.closed_cases.values():
            closed_at = case.get("closed_at")
            # Only history the bank had already closed by our decision time.
            if not closed_at or _parse_ts(closed_at) >= cutoff:
                continue
            case_id = case["case_id"]
            if customer_id and case.get("customer_id") == customer_id:
                bump(case_id, 1.0, "same customer")
            if device_ids & set(case.get("device_ids", [])):
                bump(case_id, 0.9, "shared device profile")
            if card_id and case.get("card_id") == card_id:
                bump(case_id, 0.6, "same card")
            if pattern_hint and case.get("pattern") == pattern_hint:
                bump(case_id, 0.3, "same pattern")

        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:limit]
        results = []
        for case_id, score in ranked:
            case = self.closed_cases[case_id]
            results.append(
                {
                    "case_id": case_id,
                    "outcome": case.get("outcome", ""),
                    "pattern": case.get("pattern", ""),
                    "customer_id": case.get("customer_id", ""),
                    "card_id": case.get("card_id", ""),
                    "exposure_usd": float(case.get("exposure_usd") or 0.0),
                    "n_txns": int(case.get("n_txns") or 0),
                    "report_filed": str(case.get("report_filed", "")).lower() == "true",
                    "closed_at": case.get("closed_at", ""),
                    "structural_score": score,
                    "link_reason": reasons[case_id],
                    "analyst_notes": case.get("analyst_notes", ""),
                }
            )
        return [{"similar_cases": results}]

    def _q_get_correlated_case_triggers(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        device_ids = set(params.get("device_ids") or [])
        cutoff = _parse_ts(params["cutoff"])
        start = cutoff - timedelta(days=int(params.get("window_days", 30)))
        customer_id = str(params.get("customer_id", ""))

        correlated = []
        for case in self.closed_cases.values():
            opened = case.get("opened_at")
            if not opened:
                continue
            opened_at = _parse_ts(opened)
            if not (start <= opened_at < cutoff):
                continue
            if case.get("customer_id") == customer_id:
                continue
            shares_device = bool(device_ids & set(case.get("device_ids", [])))
            if shares_device:
                correlated.append(
                    {
                        "case_id": case["case_id"],
                        "customer_id": case.get("customer_id", ""),
                        "pattern": case.get("pattern", ""),
                        "outcome": case.get("outcome", ""),
                        "opened_at": opened,
                        "link_reason": "shares a device profile",
                    }
                )
        return [{"correlated_triggers": correlated}]

    def _q_find_high_fanout_origins(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        window_start = _parse_ts(params["window_start"])
        window_end = _parse_ts(params["window_end"])
        min_customers = int(params.get("min_customers", 3))
        limit = int(params.get("max_results", 25))

        candidates = []
        for device_id, rows in self.by_device.items():
            active = [r for r in rows if window_start <= r.ts <= window_end]
            customers = {r.customer_id for r in active}
            if len(customers) < min_customers:
                continue
            meta = self.devices.get(device_id, {})
            candidates.append(
                {
                    "device_id": device_id,
                    "readable": meta.get("readable", ""),
                    "customer_count": len(customers),
                    "card_count": len({r.card_id for r in active}),
                    "txn_count": len(active),
                    "avg_risk_score": round(sum(r.risk_score for r in active) / len(active), 4),
                }
            )
        candidates.sort(key=lambda item: (-item["customer_count"], item["device_id"]))
        return [{"ring_candidates": candidates[:limit]}]

    def _q_connected_cards_component(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Bounded breadth-first expansion, mirroring the GSQL algorithm."""
        seed = str(params["seed_card_id"])
        window_start = _parse_ts(params["window_start"])
        window_end = _parse_ts(params["window_end"])
        max_hops = int(params.get("max_hops", 2))
        max_cards = int(params.get("max_cards", 50))

        component = {seed}
        bridging: set[str] = set()
        frontier = {seed}

        for _ in range(max_hops):
            if not frontier or len(component) >= max_cards:
                break
            devices = {
                row.device_profile_id
                for card in frontier
                for row in self.by_card.get(card, [])
                if row.device_profile_id and window_start <= row.ts <= window_end
            }
            bridging |= devices
            neighbours = {
                row.card_id
                for device in devices
                for row in self.by_device.get(device, [])
                if window_start <= row.ts <= window_end
            }
            frontier = neighbours - component
            component |= frontier

        return [
            {
                "component_cards": sorted(component)[:max_cards],
                "bridging_devices": sorted(bridging),
                "component_size": len(component),
            }
        ]

    def _q_get_case_history(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        case_id = str(params["case_id"])
        stored = self.written_cases.get(case_id)
        if stored is None:
            closed = self.closed_cases.get(case_id)
            if closed is None:
                return [
                    {"case_details": [], "evidence": [], "evidence_requests": [], "actions": []}
                ]
            return [
                {"case_details": [closed], "evidence": [], "evidence_requests": [], "actions": []}
            ]
        return [
            {
                "case_details": [stored.attributes],
                "evidence": stored.evidence,
                "evidence_requests": stored.requests,
                "actions": stored.actions,
                "transactions": [
                    {
                        "txn_id": txn_id,
                        "ts": _fmt(self.transactions[txn_id].ts),
                        "amount": self.transactions[txn_id].amount,
                        "channel": self.transactions[txn_id].channel,
                    }
                    for txn_id in stored.transactions
                    if txn_id in self.transactions
                ],
                "similar_cases": [{"case_id": value} for value in stored.similar],
            }
        ]

    def _q_get_case_graph(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        case_id = str(params["case_id"])
        stored = self.written_cases.get(case_id)
        if stored is None:
            return [{"case_node": [], "transactions": [], "devices": [], "connected_cards": []}]

        max_txns = int(params.get("max_transactions", 50))
        txn_ids = stored.transactions[:max_txns]
        rows = [self.transactions[t] for t in txn_ids if t in self.transactions]

        return [
            {
                "case_node": [stored.attributes],
                "customers": [{"customer_id": stored.attributes.get("customer_id", "")}],
                "cards": [{"card_id": stored.attributes.get("card_id", "")}],
                "transactions": [
                    {
                        "txn_id": r.txn_id,
                        "ts": _fmt(r.ts),
                        "amount": r.amount,
                        "channel": r.channel,
                        "risk_score": r.risk_score,
                        "device_profile_id": r.device_profile_id,
                    }
                    for r in rows
                ],
                "devices": [
                    {
                        "device_id": device_id,
                        "readable": self.devices.get(device_id, {}).get("readable", ""),
                        "card_fanout": len(
                            {row.card_id for row in self.by_device.get(device_id, [])}
                        ),
                    }
                    for device_id in stored.devices
                ],
                "connected_cards": [
                    {
                        "card_id": card_id,
                        "customer_id": self.cards.get(card_id, {}).get("customer_id", ""),
                    }
                    for card_id in stored.connected_cards
                ],
                "regions": [
                    {"region_code": region} for region in sorted({r.addr1 for r in rows if r.addr1})
                ],
                "similar_cases": [
                    {
                        "case_id": value,
                        "outcome": self.closed_cases.get(value, {}).get("outcome", ""),
                        "pattern": self.closed_cases.get(value, {}).get("pattern", ""),
                    }
                    for value in stored.similar
                ],
            }
        ]

    # -- write queries -----------------------------------------------------

    def _case(self, case_id: str) -> _StoredCase:
        return self.written_cases.setdefault(case_id, _StoredCase())

    def _q_upsert_case(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        case = self._case(str(params["case_id"]))
        case.attributes = dict(params)
        return [{"written_case_id": params["case_id"]}]

    def _q_link_case_transactions(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        case = self._case(str(params["case_id"]))
        known = [t for t in params.get("txn_ids", []) if t in self.transactions]
        for txn_id in known:
            if txn_id not in case.transactions:
                case.transactions.append(txn_id)
        return [{"linked_count": len(known)}]

    def _q_link_case_connections(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        case = self._case(str(params["case_id"]))
        cards = [c for c in params.get("connected_card_ids", []) if c in self.cards]
        devices = [d for d in params.get("device_ids", []) if d in self.devices]
        for card_id in cards:
            if card_id not in case.connected_cards:
                case.connected_cards.append(card_id)
        for device_id in devices:
            if device_id not in case.devices:
                case.devices.append(device_id)
        return [{"cards_linked": len(cards), "devices_linked": len(devices)}]

    def _q_add_case_evidence(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        case = self._case(str(params["case_id"]))
        evidence_id = f"{params['case_id']}:{params['seq']}"
        case.evidence.append({**params, "evidence_id": evidence_id})
        return [{"evidence_id": evidence_id}]

    def _q_add_evidence_request(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        case = self._case(str(params["case_id"]))
        request_id = f"{params['case_id']}:req:{params['request_no']}"
        case.requests.append({**params, "request_id": request_id})
        return [{"request_id": request_id}]

    def _q_add_action_decision(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        case = self._case(str(params["case_id"]))
        decision_id = f"{params['case_id']}:{params['stage']}:{params['ordinal']}"
        case.actions.append({**params, "decision_id": decision_id})
        return [{"decision_id": decision_id}]

    def _q_link_similar_cases(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        case = self._case(str(params["case_id"]))
        known = [c for c in params.get("prior_case_ids", []) if c in self.closed_cases]
        for case_id in known:
            if case_id not in case.similar:
                case.similar.append(case_id)
        return [{"linked_count": len(known)}]

    def _q_verify_case_bundle(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        case_id = str(params["case_id"])
        stored = self.written_cases.get(case_id)
        if stored is None:
            return [{"case_details": [], "evidence_count": 0}]
        return [
            {
                "case_details": [
                    {
                        "case_id": case_id,
                        "bundle_hash": stored.attributes.get("bundle_hash", ""),
                        "status": stored.attributes.get("status", ""),
                        "verdict": stored.attributes.get("verdict", ""),
                        "exposure_usd": stored.attributes.get("exposure_usd", 0.0),
                    }
                ],
                "evidence_count": len(stored.evidence),
                "request_count": len(stored.requests),
                "action_count": len(stored.actions),
                "transaction_count": len(stored.transactions),
                "connected_card_count": len(stored.connected_cards),
                "similar_case_count": len(stored.similar),
            }
        ]


def hash_result(payload: Any) -> str:
    """Stable hash of a query result, for evidence receipts."""
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]
