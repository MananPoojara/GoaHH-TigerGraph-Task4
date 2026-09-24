"""Process-wide wiring and the in-memory case registry.

The registry holds completed investigations for the analyst workbench to read.
It is deliberately simple: TigerGraph is the system of record, and anything
that must survive a restart is written there. This is a read cache for the UI,
not a second source of truth.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime

from fraudlens_contracts import CasePackEntry, load_case_pack
from fraudlens_graph import FixtureGraphClient, GraphClient, TigerGraphClient
from fraudlens_investigator import CaseState, LLMPort, Trigger

from ..core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class CaseRegistry:
    """Thread-safe store of investigation state, keyed by case ID."""

    def __init__(self) -> None:
        self._states: dict[str, CaseState] = {}
        self._lock = threading.Lock()

    def put(self, state: CaseState) -> None:
        with self._lock:
            self._states[state.trigger.case_id] = state

    def get(self, case_id: str) -> CaseState | None:
        with self._lock:
            return self._states.get(case_id)

    def all(self) -> list[CaseState]:
        with self._lock:
            return list(self._states.values())

    def clear(self) -> None:
        with self._lock:
            self._states.clear()


class Runtime:
    """Everything the API needs, assembled once at startup."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.registry = CaseRegistry()
        self._graph: GraphClient | None = None
        self._llm: LLMPort | None = None
        self._case_pack: list[CasePackEntry] | None = None

    # -- graph -------------------------------------------------------------

    @property
    def graph(self) -> GraphClient:
        """The graph backend.

        TigerGraph when configured and reachable; otherwise the fixture
        backend, so the workbench still runs during development. The choice is
        reported by `/health` so it is never silently ambiguous.
        """
        if self._graph is not None:
            return self._graph

        settings = self.settings
        if settings.tigergraph_configured:
            client = TigerGraphClient(
                host=settings.tg_host,
                graphname=settings.tg_graphname,
                api_token=settings.tg_api_token.get_secret_value(),
                username=settings.tg_username,
                password=settings.tg_password.get_secret_value(),
                timeout=settings.tg_timeout_seconds,
            )
            if client.is_live():
                logger.info("using TigerGraph backend at %s", settings.tg_host)
                self._graph = client
                return client
            logger.warning(
                "TigerGraph is configured but unreachable; falling back to the "
                "fixture backend. Scored runs require a live graph."
            )

        processed = settings.processed_data_dir
        if not (processed / "transactions.csv").exists():
            logger.warning(
                "no processed load files at %s; run scripts/prepare_data.py first",
                processed,
            )
        self._graph = FixtureGraphClient(processed)
        return self._graph

    @property
    def backend_name(self) -> str:
        return getattr(self.graph, "backend", "unknown")

    # -- llm ---------------------------------------------------------------

    @property
    def llm(self) -> LLMPort:
        if self._llm is None:
            self._llm = LLMPort(
                provider=self.settings.llm_provider,
                model=self.settings.llm_model,
                api_key=self.settings.llm_api_key.get_secret_value(),
                temperature=self.settings.llm_temperature,
            )
        return self._llm

    # -- case pack ---------------------------------------------------------

    @property
    def case_pack(self) -> list[CasePackEntry]:
        """The 20 official benchmark triggers, if present."""
        if self._case_pack is not None:
            return self._case_pack

        for candidate in (
            self.settings.raw_data_dir / "case_pack.csv",
            self.settings.processed_data_dir / "case_pack.csv",
            self.settings.fixtures_dir / "case_pack.csv",
        ):
            if candidate.exists():
                self._case_pack = load_case_pack(candidate)
                logger.info("loaded %d case pack entries from %s", len(self._case_pack), candidate)
                return self._case_pack

        logger.warning("no case_pack.csv found; the queue will be empty")
        self._case_pack = []
        return self._case_pack

    def trigger_for(self, case_id: str) -> Trigger | None:
        for entry in self.case_pack:
            if entry.case_id == case_id:
                return Trigger(
                    case_id=entry.case_id,
                    trigger_type=entry.trigger_type,
                    trigger_text=entry.trigger_text,
                    flagged_txn_id=entry.flagged_txn_id,
                    card_id=entry.card_id,
                    customer_id=entry.customer_id,
                    opened_at=entry.opened_at,
                    risk_score=entry.risk_score,
                )
        return None

    def health(self) -> dict[str, object]:
        """Safe status for the UI. Never exposes a credential."""
        return {
            "status": "ok",
            "graph_backend": self.backend_name,
            "graph_live": self.graph.is_live(),
            "llm_available": self.llm.available,
            "case_pack_size": len(self.case_pack),
            "cases_investigated": len(self.registry.all()),
            "checked_at": datetime.utcnow().isoformat(timespec="seconds"),
            **self.settings.redacted(),
        }


_runtime: Runtime | None = None


def get_runtime() -> Runtime:
    """FastAPI dependency: the shared runtime."""
    global _runtime
    if _runtime is None:
        _runtime = Runtime()
    return _runtime


def reset_runtime(settings: Settings | None = None) -> Runtime:
    """Rebuild the runtime. Used by tests to swap in a fixture backend."""
    global _runtime
    _runtime = Runtime(settings)
    return _runtime
