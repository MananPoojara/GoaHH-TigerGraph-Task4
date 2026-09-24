"""Graph access boundary.

`GraphClient` is the only way the investigator reaches graph data. It exposes
installed queries by name and nothing else: there is no method that runs
arbitrary GSQL, so a compromised prompt cannot mutate the graph or read past
its case cutoff.

Two implementations exist:

  * `TigerGraphClient` -- the real one, running installed GSQL against
    TigerGraph. This is the production path and the source of graph truth.
  * `FixtureGraphClient` (in `fixture.py`) -- a test double over preprocessed
    CSVs, so tests and offline UI work do not need a live workspace.

The double is a test affordance, not an alternative architecture. Anything it
computes in Python is computed in GSQL on the real path, and a scored run must
use `TigerGraphClient`.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

_VERTEX_ROW_KEYS = {"v_id", "v_type", "attributes"}


def _flatten_vertex_row(row: Any) -> Any:
    """Collapse a raw TigerGraph vertex row to its flat attribute dict.

    `PRINT SomeVertexSet` returns `{"v_id": ..., "v_type": ..., "attributes":
    {...}}` per row. Every other consumer here (`FixtureGraphClient`, tool
    docstrings, prompts) is written against the flat `attributes` shape, so
    the live client normalises here rather than leaking the REST wrapper.
    """
    if isinstance(row, dict) and _VERTEX_ROW_KEYS <= row.keys():
        return row["attributes"]
    return row


def _flatten_vertex_blocks(result: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened = []
    for block in result:
        if not isinstance(block, dict):
            flattened.append(block)
            continue
        new_block = {}
        for key, value in block.items():
            if isinstance(value, list):
                new_block[key] = [_flatten_vertex_row(item) for item in value]
            else:
                new_block[key] = value
        flattened.append(new_block)
    return flattened


class GraphError(RuntimeError):
    """A graph call failed. Carries enough context to debug without secrets."""

    def __init__(self, query: str, message: str, *, params: dict[str, Any] | None = None):
        self.query = query
        self.params = params or {}
        super().__init__(f"graph query {query!r} failed: {message}")


class GraphUnavailable(GraphError):
    """No graph is configured or reachable."""


@dataclass
class QueryReceipt:
    """Proof that a specific query ran with specific parameters.

    Attached to every piece of graph evidence so a claim can be replayed
    rather than taken on trust.
    """

    query: str
    params: dict[str, Any]
    cutoff: str
    backend: str
    latency_ms: float
    result_hash: str
    query_version: str = "1.0"

    def as_ref(self) -> str:
        """The compact `ref` string used in the answer file's evidence list."""
        rendered = ", ".join(f"{key}={value}" for key, value in sorted(self.params.items()))
        return f"query:{self.query}({rendered})"


@runtime_checkable
class GraphClient(Protocol):
    """The narrow surface the investigator is allowed to use."""

    backend: str

    def is_live(self) -> bool:
        """Whether this client is talking to a real TigerGraph instance."""
        ...

    def run(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Run an installed query by name and return its result sets."""
        ...


# Installed read queries the runtime investigator may call. Anything absent
# here is refused before a request is built, so adding a capability is a
# deliberate change rather than a prompt away.
ALLOWED_READ_QUERIES: frozenset[str] = frozenset(
    {
        "get_case_anchor",
        "get_card_window",
        "get_customer_baseline",
        "detect_card_testing",
        "detect_cnp_burst",
        "detect_region_anomaly",
        "detect_account_takeover",
        "detect_recurring_charge",
        "get_shared_origin_ring",
        "find_device_connections",
        "find_similar_cases",
        "get_case_history",
        "get_case_graph",
        "get_correlated_case_triggers",
        "find_high_fanout_origins",
        "connected_cards_component",
    }
)

# Mutating queries, reachable only through the persistence adapter.
ALLOWED_WRITE_QUERIES: frozenset[str] = frozenset(
    {
        "upsert_case",
        "link_case_transactions",
        "link_case_connections",
        "add_case_evidence",
        "add_evidence_request",
        "add_action_decision",
        "link_similar_cases",
        "verify_case_bundle",
    }
)


@dataclass
class CallLog:
    """Per-case record of graph calls, for the answer file's `tool_calls`."""

    calls: list[tuple[str, float]] = field(default_factory=list)

    def record(self, query: str, latency_ms: float) -> None:
        self.calls.append((query, latency_ms))

    @property
    def count(self) -> int:
        return len(self.calls)

    @property
    def total_latency_ms(self) -> float:
        return sum(latency for _, latency in self.calls)

    def reset(self) -> None:
        self.calls.clear()


class TigerGraphClient:
    """Runs installed GSQL queries against TigerGraph via pyTigerGraph.

    Connection details come from the central settings object; no credential is
    ever passed through a prompt or written to a trace.
    """

    backend = "tigergraph"

    def __init__(
        self,
        host: str,
        graphname: str,
        *,
        api_token: str = "",
        username: str = "tigergraph",
        password: str = "",
        timeout: float = 30.0,
        call_log: CallLog | None = None,
    ) -> None:
        self._host = host
        self._graphname = graphname
        self._api_token = api_token
        self._username = username
        self._password = password
        self._timeout = timeout
        self.call_log = call_log or CallLog()
        self._connection: Any | None = None

    def _connect(self) -> Any:
        if self._connection is not None:
            return self._connection
        try:
            import pyTigerGraph as tg
        except ImportError as error:  # pragma: no cover - depends on extras
            raise GraphUnavailable(
                "connect",
                "pyTigerGraph is not installed; run: python -m pip install -e '.[graph]'",
            ) from error

        try:
            connection = tg.TigerGraphConnection(
                host=self._host,
                graphname=self._graphname,
                username=self._username,
                password=self._password,
                apiToken=self._api_token or None,
            )
            if not self._api_token:
                connection.getToken(connection.createSecret())
        except Exception as error:
            # Never echo the credential itself into the message.
            raise GraphUnavailable(
                "connect", f"could not connect to {self._host}: {type(error).__name__}"
            ) from error

        self._connection = connection
        return connection

    def is_live(self) -> bool:
        try:
            connection = self._connect()
            connection.echo()
            return True
        except Exception:
            logger.warning("TigerGraph is configured but not reachable", exc_info=True)
            return False

    def run(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        if query not in ALLOWED_READ_QUERIES and query not in ALLOWED_WRITE_QUERIES:
            raise GraphError(query, "query is not in the allow-list")

        connection = self._connect()
        started = time.perf_counter()
        try:
            result = connection.runInstalledQuery(
                query, params=params, timeout=int(self._timeout * 1000)
            )
        except Exception as error:
            logger.exception("installed query failed: %s", query)
            raise GraphError(query, str(error), params=params) from error

        latency_ms = (time.perf_counter() - started) * 1000
        self.call_log.record(query, latency_ms)
        logger.info("graph query %s completed in %.1f ms", query, latency_ms)
        return _flatten_vertex_blocks(result or [])
