"""Business-capability tools over the graph.

Each tool is small, typed, and named for what an investigator wants to know
rather than for the query that answers it. The agent selects among these; it
never composes GSQL and never receives a general "run this query" capability.

Every tool returns a result carrying a `QueryReceipt`, so any claim built from
it can be replayed with the same parameters and compared by hash.

Permission model: everything here is read-only and cutoff-bounded. Writes live
in `persistence.py` behind the validated case-bundle path.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .client import GraphClient, GraphError, QueryReceipt
from .fixture import hash_result

logger = logging.getLogger(__name__)

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


def _fmt(value: datetime | str) -> str:
    return value.strftime(TIMESTAMP_FORMAT) if isinstance(value, datetime) else str(value)


class ToolResult(BaseModel):
    """Common envelope: the data, plus how it was obtained."""

    # QueryReceipt is a dataclass, so arbitrary types must be permitted here.
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    data: dict[str, Any] = Field(default_factory=dict)
    receipt: QueryReceipt | None = None

    @property
    def ref(self) -> str:
        return self.receipt.as_ref() if self.receipt else "query:unknown"


def _call(
    client: GraphClient,
    query: str,
    params: dict[str, Any],
    cutoff: datetime | str,
) -> ToolResult:
    """Run an installed query and wrap the first result set with a receipt."""
    started = time.perf_counter()
    try:
        raw = client.run(query, params)
    except GraphError:
        logger.exception("tool call failed: %s", query)
        raise

    latency_ms = (time.perf_counter() - started) * 1000
    payload: dict[str, Any] = {}
    for block in raw:
        if isinstance(block, dict):
            payload.update(block)

    receipt = QueryReceipt(
        query=query,
        params={k: v for k, v in params.items() if k != "cutoff"},
        cutoff=_fmt(cutoff),
        backend=getattr(client, "backend", "unknown"),
        latency_ms=round(latency_ms, 2),
        result_hash=hash_result(payload),
    )
    return ToolResult(data=payload, receipt=receipt)


# ---------------------------------------------------------------------------
# Anchor and history
# ---------------------------------------------------------------------------


def get_case_anchor(
    client: GraphClient, *, txn_id: str, card_id: str, customer_id: str, cutoff: datetime
) -> ToolResult:
    """Confirm the trigger hangs together before investigating it.

    Returns the flagged transaction with its card and customer, plus any
    integrity errors. A case whose anchor cannot be confirmed is rejected at
    intake rather than investigated on a false premise.
    """
    return _call(
        client,
        "get_case_anchor",
        {"txn_id": txn_id, "card_id": card_id, "customer_id": customer_id},
        cutoff,
    )


def get_transaction_history(
    client: GraphClient,
    *,
    card_id: str,
    anchor_ts: datetime,
    cutoff: datetime,
    hours_before: int = 72,
    hours_after: int = 72,
    max_results: int = 200,
) -> ToolResult:
    """Ordered activity around the anchor on one card.

    The window is clamped to the cutoff, so `hours_after` can never reveal
    activity the investigation is not entitled to see.
    """
    return _call(
        client,
        "get_card_window",
        {
            "card_id": card_id,
            "anchor_ts": _fmt(anchor_ts),
            "hours_before": hours_before,
            "hours_after": hours_after,
            "cutoff": _fmt(cutoff),
            "max_results": max_results,
        },
        cutoff,
    )


def get_customer_baseline(
    client: GraphClient, *, customer_id: str, cutoff: datetime, lookback_days: int = 180
) -> ToolResult:
    """What normal looks like for this cardholder, strictly before the cutoff.

    Without this, "unusual amount" and "novel region" are opinions rather than
    measurements.
    """
    return _call(
        client,
        "get_customer_baseline",
        {"customer_id": customer_id, "cutoff": _fmt(cutoff), "lookback_days": lookback_days},
        cutoff,
    )


# ---------------------------------------------------------------------------
# Pattern observation
# ---------------------------------------------------------------------------


def detect_card_testing(
    client: GraphClient,
    *,
    card_id: str,
    cutoff: datetime,
    window_hours: int = 24,
    small_amount_max: float = 5.0,
) -> ToolResult:
    """Observe the R5 sequence components on one card.

    Returns counts and IDs, not a verdict: whether R5 applies is the policy
    engine's decision, not this tool's.
    """
    return _call(
        client,
        "detect_card_testing",
        {
            "card_id": card_id,
            "cutoff": _fmt(cutoff),
            "window_hours": window_hours,
            "small_amount_max": small_amount_max,
        },
        cutoff,
    )


def detect_cnp_burst(
    client: GraphClient, *, card_id: str, cutoff: datetime, window_hours: int = 48
) -> ToolResult:
    """Online burst shape, device novelty, and proxy use for one card."""
    return _call(
        client,
        "detect_cnp_burst",
        {"card_id": card_id, "cutoff": _fmt(cutoff), "window_hours": window_hours},
        cutoff,
    )


def detect_region_anomaly(
    client: GraphClient,
    *,
    customer_id: str,
    cutoff: datetime,
    window_hours: int = 72,
    baseline_days: int = 120,
) -> ToolResult:
    """Novel billing regions, and whether home activity continued alongside.

    The concurrency figure is what separates a cloned card from a traveller.
    """
    return _call(
        client,
        "detect_region_anomaly",
        {
            "customer_id": customer_id,
            "cutoff": _fmt(cutoff),
            "window_hours": window_hours,
            "baseline_days": baseline_days,
        },
        cutoff,
    )


def detect_account_takeover(
    client: GraphClient, *, customer_id: str, cutoff: datetime, window_hours: int = 72
) -> ToolResult:
    """Mixed-channel activity with device and match anomalies across the
    customer's cards. Reported as separate signals, since the pattern needs
    several independent ones."""
    return _call(
        client,
        "detect_account_takeover",
        {"customer_id": customer_id, "cutoff": _fmt(cutoff), "window_hours": window_hours},
        cutoff,
    )


def detect_recurring_charge(
    client: GraphClient,
    *,
    card_id: str,
    amount: float,
    product_cd: str,
    cutoff: datetime,
    lookback_days: int = 180,
    amount_tolerance: float = 1.0,
) -> ToolResult:
    """Has this cardholder paid roughly this amount for this product before?

    Feeds policy R7. A disputed charge that matches the cardholder's own
    recurring pattern must not be blocked, so this has to be checked before a
    dispute is acted on.
    """
    return _call(
        client,
        "detect_recurring_charge",
        {
            "card_id": card_id,
            "amount": amount,
            "product_cd": product_cd,
            "cutoff": _fmt(cutoff),
            "lookback_days": lookback_days,
            "amount_tolerance": amount_tolerance,
        },
        cutoff,
    )


# ---------------------------------------------------------------------------
# Relationships
# ---------------------------------------------------------------------------


def find_device_connections(
    client: GraphClient,
    *,
    card_id: str,
    cutoff: datetime,
    window_hours: int = 720,
    max_devices: int = 50,
) -> ToolResult:
    """Device profiles this card used, with fan-out recomputed as of the cutoff.

    High fan-out is context, never guilt by association.
    """
    return _call(
        client,
        "find_device_connections",
        {
            "card_id": card_id,
            "cutoff": _fmt(cutoff),
            "window_hours": window_hours,
            "max_devices": max_devices,
        },
        cutoff,
    )


def find_connected_accounts(
    client: GraphClient,
    *,
    origin_kind: str,
    origin_id: str,
    cutoff: datetime,
    exclude_card_id: str = "",
    window_hours: int = 720,
    max_cards: int = 50,
) -> ToolResult:
    """Other cards reached through a shared device, region, or recipient email.

    This is the traversal that answers "what happened on other cards?" and the
    one that turns a single alert into an R6 shared-origin finding.
    """
    if origin_kind not in {"device", "region", "recipient_email"}:
        raise ValueError(f"unsupported origin kind {origin_kind!r}")
    return _call(
        client,
        "get_shared_origin_ring",
        {
            "origin_kind": origin_kind,
            "origin_id": origin_id,
            "exclude_card_id": exclude_card_id,
            "cutoff": _fmt(cutoff),
            "window_hours": window_hours,
            "max_cards": max_cards,
        },
        cutoff,
    )


def trace_money_flow(
    client: GraphClient,
    *,
    seed_card_id: str,
    window_start: datetime,
    window_end: datetime,
    max_hops: int = 2,
    max_cards: int = 50,
) -> ToolResult:
    """The connected component of cards reachable through shared devices.

    Named for the investigative question rather than the algorithm: it answers
    "how far does this compromise reach?" by bounded expansion from the seed.
    """
    return _call(
        client,
        "connected_cards_component",
        {
            "seed_card_id": seed_card_id,
            "window_start": _fmt(window_start),
            "window_end": _fmt(window_end),
            "max_hops": max_hops,
            "max_cards": max_cards,
        },
        window_end,
    )


# ---------------------------------------------------------------------------
# Case memory
# ---------------------------------------------------------------------------


def find_similar_cases(
    client: GraphClient,
    *,
    customer_id: str,
    card_id: str,
    cutoff: datetime,
    device_ids: list[str] | None = None,
    pattern_hint: str = "",
    max_cases: int = 5,
) -> ToolResult:
    """Closed cases sharing concrete structure with this one.

    Only history closed before the cutoff is visible, so a case can never be
    informed by an investigation that had not finished yet.
    """
    return _call(
        client,
        "find_similar_cases",
        {
            "customer_id": customer_id,
            "card_id": card_id,
            "device_ids": device_ids or [],
            "pattern_hint": pattern_hint,
            "cutoff": _fmt(cutoff),
            "max_cases": max_cases,
        },
        cutoff,
    )


def get_case_history(client: GraphClient, *, case_id: str) -> ToolResult:
    """The stored record of one case: evidence, requests, and decisions."""
    return _call(client, "get_case_history", {"case_id": case_id}, "n/a")


def get_case_graph(
    client: GraphClient, *, case_id: str, max_transactions: int = 50, max_connected_cards: int = 25
) -> ToolResult:
    """A bounded evidence subgraph for the analyst UI."""
    return _call(
        client,
        "get_case_graph",
        {
            "case_id": case_id,
            "max_transactions": max_transactions,
            "max_connected_cards": max_connected_cards,
        },
        "n/a",
    )


def get_correlated_triggers(
    client: GraphClient,
    *,
    customer_id: str,
    cutoff: datetime,
    device_ids: list[str] | None = None,
    window_days: int = 30,
    max_results: int = 10,
) -> ToolResult:
    """Nearby alerts that may be the same incident. Deliberately does not merge
    them; that is an analyst's call."""
    return _call(
        client,
        "get_correlated_case_triggers",
        {
            "customer_id": customer_id,
            "device_ids": device_ids or [],
            "cutoff": _fmt(cutoff),
            "window_days": window_days,
            "max_results": max_results,
        },
        cutoff,
    )


# The tools the investigator may select from, by name.
INVESTIGATION_TOOLS = {
    "get_case_anchor": get_case_anchor,
    "get_transaction_history": get_transaction_history,
    "get_customer_baseline": get_customer_baseline,
    "detect_card_testing": detect_card_testing,
    "detect_cnp_burst": detect_cnp_burst,
    "detect_region_anomaly": detect_region_anomaly,
    "detect_account_takeover": detect_account_takeover,
    "detect_recurring_charge": detect_recurring_charge,
    "find_device_connections": find_device_connections,
    "find_connected_accounts": find_connected_accounts,
    "trace_money_flow": trace_money_flow,
    "find_similar_cases": find_similar_cases,
    "get_correlated_triggers": get_correlated_triggers,
}
