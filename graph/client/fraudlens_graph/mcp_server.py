"""MCP server exposing the graph as investigation tools.

Run it over stdio:

    python -m fraudlens_graph.mcp_server

Why a server of our own rather than the generic TigerGraph MCP server: the
generic one exposes schema access and arbitrary GSQL, which is more authority
than an investigating agent should hold. The tools here are business
capabilities with typed, bounded parameters -- `find_connected_accounts`, not
`run_query`. An agent that can only ask these questions cannot mutate the
graph, cannot read past a case cutoff, and cannot invent a query.

Every tool requires an explicit `cutoff`. That is the single most important
constraint in the system: a case opened on 2016-12-05 must not be able to see
what happened on 2016-12-06, and making the cutoff a required parameter means
a caller cannot omit it by accident.

The write path is deliberately absent. Case persistence goes through the
validated bundle adapter, never through a model-reachable tool.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from . import tools
from .client import CallLog, GraphClient
from .fixture import FixtureGraphClient

logger = logging.getLogger(__name__)

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


def _parse_cutoff(value: str) -> datetime:
    try:
        return datetime.strptime(value, TIMESTAMP_FORMAT)
    except ValueError as error:
        raise ValueError(f"cutoff must be 'YYYY-MM-DD HH:MM:SS', got {value!r}") from error


def build_graph_client() -> GraphClient:
    """Pick the backend from configuration, preferring a live TigerGraph."""
    # Imported lazily so the module is usable without the API package.
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from app.core.config import get_settings

    from .client import TigerGraphClient

    settings = get_settings()
    call_log = CallLog()

    if settings.tigergraph_configured:
        client = TigerGraphClient(
            host=settings.tg_host,
            graphname=settings.tg_graphname,
            api_token=settings.tg_api_token.get_secret_value(),
            username=settings.tg_username,
            password=settings.tg_password.get_secret_value(),
            timeout=settings.tg_timeout_seconds,
            call_log=call_log,
        )
        if client.is_live():
            return client
        logger.warning("TigerGraph unreachable; serving the fixture backend")

    return FixtureGraphClient(settings.processed_data_dir, call_log=call_log)


def build_server() -> Any:
    """Construct the MCP server with the investigation tool set."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as error:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "the mcp package is not installed; run: python -m pip install 'mcp[cli]'"
        ) from error

    server = FastMCP("fraudlens-graph")
    graph = build_graph_client()

    def _emit(result: tools.ToolResult) -> str:
        """Return data plus its receipt, so a claim stays traceable."""
        return json.dumps(
            {
                "data": result.data,
                "ref": result.ref,
                "result_hash": result.receipt.result_hash if result.receipt else "",
                "backend": result.receipt.backend if result.receipt else "unknown",
            },
            default=str,
            indent=2,
        )

    @server.tool()
    def get_case_anchor(txn_id: str, card_id: str, customer_id: str, cutoff: str) -> str:
        """Confirm a flagged transaction belongs to the named card and customer.

        Call this first. If it reports integrity errors, the trigger does not
        hang together and the case must be escalated rather than investigated.
        """
        return _emit(
            tools.get_case_anchor(
                graph,
                txn_id=txn_id,
                card_id=card_id,
                customer_id=customer_id,
                cutoff=_parse_cutoff(cutoff),
            )
        )

    @server.tool()
    def get_transaction_history(
        card_id: str,
        anchor_ts: str,
        cutoff: str,
        hours_before: int = 72,
        hours_after: int = 72,
    ) -> str:
        """Ordered activity on one card around the anchor time.

        The window is clamped to the cutoff, so `hours_after` can never reveal
        activity later than the case decision time.
        """
        return _emit(
            tools.get_transaction_history(
                graph,
                card_id=card_id,
                anchor_ts=_parse_cutoff(anchor_ts),
                cutoff=_parse_cutoff(cutoff),
                hours_before=hours_before,
                hours_after=hours_after,
            )
        )

    @server.tool()
    def get_customer_baseline(customer_id: str, cutoff: str, lookback_days: int = 180) -> str:
        """What normal looks like for this cardholder, strictly before the cutoff.

        Use this before calling any activity unusual. Amounts, regions,
        products, and devices are only anomalous relative to this.
        """
        return _emit(
            tools.get_customer_baseline(
                graph,
                customer_id=customer_id,
                cutoff=_parse_cutoff(cutoff),
                lookback_days=lookback_days,
            )
        )

    @server.tool()
    def detect_card_testing(
        card_id: str, cutoff: str, window_hours: int = 24, small_amount_max: float = 5.0
    ) -> str:
        """Observe the card-testing sequence components on one card.

        Returns counts and transaction IDs, not a verdict. Policy rule R5
        decides whether the sequence warrants action.
        """
        return _emit(
            tools.detect_card_testing(
                graph,
                card_id=card_id,
                cutoff=_parse_cutoff(cutoff),
                window_hours=window_hours,
                small_amount_max=small_amount_max,
            )
        )

    @server.tool()
    def detect_cnp_burst(card_id: str, cutoff: str, window_hours: int = 48) -> str:
        """Online burst shape, device novelty, and proxy use for one card.

        A single unusual online purchase is ambiguous, and a device marked New
        is not proof: people buy new phones. Weigh accordingly.
        """
        return _emit(
            tools.detect_cnp_burst(
                graph, card_id=card_id, cutoff=_parse_cutoff(cutoff), window_hours=window_hours
            )
        )

    @server.tool()
    def detect_region_anomaly(
        customer_id: str, cutoff: str, window_hours: int = 72, baseline_days: int = 120
    ) -> str:
        """Novel billing regions, and whether home activity continued alongside.

        Concurrent activity in a known region is what separates a cloned card
        from a cardholder who is simply travelling.
        """
        return _emit(
            tools.detect_region_anomaly(
                graph,
                customer_id=customer_id,
                cutoff=_parse_cutoff(cutoff),
                window_hours=window_hours,
                baseline_days=baseline_days,
            )
        )

    @server.tool()
    def detect_account_takeover(customer_id: str, cutoff: str, window_hours: int = 72) -> str:
        """Mixed-channel activity with device and match anomalies.

        Returns each signal separately; the pattern needs several independent
        ones before it is credible.
        """
        return _emit(
            tools.detect_account_takeover(
                graph,
                customer_id=customer_id,
                cutoff=_parse_cutoff(cutoff),
                window_hours=window_hours,
            )
        )

    @server.tool()
    def find_device_connections(card_id: str, cutoff: str, window_hours: int = 720) -> str:
        """Device profiles this card used, with fan-out as of the cutoff.

        High fan-out is context, never guilt by association. Corroborate it
        before treating it as evidence of fraud.
        """
        return _emit(
            tools.find_device_connections(
                graph, card_id=card_id, cutoff=_parse_cutoff(cutoff), window_hours=window_hours
            )
        )

    @server.tool()
    def find_connected_accounts(
        origin_kind: str,
        origin_id: str,
        cutoff: str,
        exclude_card_id: str = "",
        window_hours: int = 720,
    ) -> str:
        """Other cards reached through a shared device, region, or recipient email.

        `origin_kind` is one of: device, region, recipient_email. This answers
        "what happened on other cards?" and is what turns a single alert into
        a shared-origin finding under R6.
        """
        return _emit(
            tools.find_connected_accounts(
                graph,
                origin_kind=origin_kind,
                origin_id=origin_id,
                cutoff=_parse_cutoff(cutoff),
                exclude_card_id=exclude_card_id,
                window_hours=window_hours,
            )
        )

    @server.tool()
    def trace_money_flow(
        seed_card_id: str, window_start: str, window_end: str, max_hops: int = 2
    ) -> str:
        """How far a compromise reaches, by bounded expansion from one card."""
        return _emit(
            tools.trace_money_flow(
                graph,
                seed_card_id=seed_card_id,
                window_start=_parse_cutoff(window_start),
                window_end=_parse_cutoff(window_end),
                max_hops=max_hops,
            )
        )

    @server.tool()
    def find_similar_cases(
        customer_id: str,
        card_id: str,
        cutoff: str,
        device_ids: list[str] | None = None,
        pattern_hint: str = "",
        max_cases: int = 5,
    ) -> str:
        """Closed cases sharing structure with this one, as investigation memory.

        Only history the bank closed before the cutoff is visible, so a case
        can never be informed by an investigation that had not finished yet.
        """
        return _emit(
            tools.find_similar_cases(
                graph,
                customer_id=customer_id,
                card_id=card_id,
                cutoff=_parse_cutoff(cutoff),
                device_ids=device_ids or [],
                pattern_hint=pattern_hint,
                max_cases=max_cases,
            )
        )

    @server.tool()
    def get_case_history(case_id: str) -> str:
        """The stored record of one case: evidence, requests, and decisions."""
        return _emit(tools.get_case_history(graph, case_id=case_id))

    return server


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    server = build_server()
    logger.info("fraudlens-graph MCP server starting on stdio")
    server.run()


if __name__ == "__main__":
    main()
