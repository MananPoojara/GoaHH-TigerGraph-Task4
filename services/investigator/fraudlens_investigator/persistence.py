"""Case write-back and read-back verification.

This is the only component permitted to mutate the graph. It writes a case
bundle with deterministic IDs, then reads it back and compares counts and the
bundle hash. `written_to_graph` in the answer file may only be set true when
that comparison succeeds -- claiming persistence that did not happen would
make the case memory a lie for every later investigation.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime

from fraudlens_graph import GraphClient, GraphError

from .state import CaseState

logger = logging.getLogger(__name__)

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


@dataclass
class WriteReceipt:
    """What was written, and whether the read-back agreed."""

    case_id: str
    graph_case_id: str
    bundle_hash: str
    verified: bool = False
    expected: dict[str, int] = field(default_factory=dict)
    actual: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.verified:
            return f"{self.case_id}: written and verified as {self.graph_case_id}"
        return f"{self.case_id}: write-back NOT verified ({'; '.join(self.errors)})"


def compute_bundle_hash(state: CaseState) -> str:
    """A stable hash over the material contents of the case bundle.

    Covers what a later reader would rely on. Excludes latency and token
    counts, which vary between runs without changing the case.
    """
    payload = {
        "case_id": state.trigger.case_id,
        "verdict": state.current.verdict.value if state.current else "",
        "probability": state.current.fraud_probability if state.current else 0.0,
        "pattern": state.current.pattern.value if state.current else "",
        "exposure": round(state.exposure_usd, 2),
        "affected": sorted(state.affected_txn_ids),
        "connected_cards": sorted(state.connected_card_ids),
        "devices": sorted(state.connected_device_ids),
        "evidence": [record.claim for record in state.evidence],
        "final_actions": [(item.action.value, item.route.value) for item in state.final_actions],
        "sar_file": state.sar_file,
    }
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:32]


def graph_case_id_for(state: CaseState) -> str:
    """Deterministic graph case ID, so a retry overwrites rather than duplicates."""
    return f"CASE-{state.trigger.opened_at.year}-{state.trigger.case_id}"


def persist_case(state: CaseState, graph: GraphClient) -> WriteReceipt:
    """Write the case bundle, then read it back and verify.

    Failure is reported, never swallowed: an unverified write leaves
    `written_to_graph` false and the reason in the receipt.
    """
    graph_case_id = graph_case_id_for(state)
    bundle_hash = compute_bundle_hash(state)
    current = state.current

    receipt = WriteReceipt(
        case_id=state.trigger.case_id,
        graph_case_id=graph_case_id,
        bundle_hash=bundle_hash,
    )

    try:
        graph.run(
            "upsert_case",
            {
                "case_id": graph_case_id,
                "source": "agent",
                # Our own conclusion, never the bank's labelled truth.
                "trust_tier": "agent_derived",
                "customer_id": state.trigger.customer_id,
                "card_id": state.trigger.card_id,
                "opened_at": state.trigger.opened_at.strftime(TIMESTAMP_FORMAT),
                "closed_at": datetime.utcnow().strftime(TIMESTAMP_FORMAT),
                "status": state.status.value,
                "verdict": current.verdict.value if current else "",
                "outcome": current.verdict.value if current else "",
                "pattern": current.pattern.value if current else "",
                "pattern_description": current.pattern_description if current else "",
                "fraud_probability": current.fraud_probability if current else 0.0,
                "exposure_usd": round(state.exposure_usd, 2),
                "n_txns": len(state.affected_txn_ids),
                "report_filed": state.sar_file,
                "trigger_type": state.trigger.trigger_type.value,
                "trigger_text": state.trigger.trigger_text,
                "stop_reason": state.stop_reason,
                "summary": state.summary,
                "run_id": state.run_id,
                "bundle_hash": bundle_hash,
            },
        )

        if state.affected_txn_ids:
            graph.run(
                "link_case_transactions",
                {
                    "case_id": graph_case_id,
                    "txn_ids": state.affected_txn_ids,
                    "affected": True,
                    "role": "episode",
                },
            )

        if state.connected_card_ids or state.connected_device_ids:
            graph.run(
                "link_case_connections",
                {
                    "case_id": graph_case_id,
                    "connected_card_ids": state.connected_card_ids,
                    "device_ids": state.connected_device_ids,
                    "link_reason": "shared device profile",
                },
            )

        for record in state.evidence:
            graph.run(
                "add_case_evidence",
                {
                    "case_id": graph_case_id,
                    "seq": record.seq,
                    "claim": record.claim,
                    "source": record.source.value,
                    "ref": record.ref,
                    "direction": record.direction.value,
                    "source_family": record.source_family,
                    "collected_at": record.collected_at.strftime(TIMESTAMP_FORMAT),
                    "cutoff": state.trigger.cutoff.strftime(TIMESTAMP_FORMAT),
                    "query_version": record.query_version,
                    "result_hash": record.result_hash,
                    "entity_txn_ids": [value for value in record.entity_ids if value.isdigit()],
                },
            )

        for request in state.requests:
            graph.run(
                "add_evidence_request",
                {
                    "case_id": graph_case_id,
                    "request_no": request.request_no,
                    "req_type": request.request_type.value,
                    "asked_after_step": request.asked_after_step,
                    "reason": request.reason,
                    "assumed_response": request.assumed_response,
                    "simulator_version": request.simulator_version,
                    "requested_at": datetime.utcnow().strftime(TIMESTAMP_FORMAT),
                },
            )

        for stage, actions in (("initial", state.initial_actions), ("final", state.final_actions)):
            for ordinal, item in enumerate(actions, start=1):
                graph.run(
                    "add_action_decision",
                    {
                        "case_id": graph_case_id,
                        "stage": stage,
                        "ordinal": ordinal,
                        "action": item.action.value,
                        "route": item.route.value,
                        "reason": item.reason,
                        "state": (
                            "executed"
                            if stage == "final" and item.action in state.executed_actions
                            else "recommended"
                        ),
                        "rule_ids": ",".join(state.triggered_rules),
                    },
                )

        if state.prior_cases:
            graph.run(
                "link_similar_cases",
                {
                    "case_id": graph_case_id,
                    "prior_case_ids": [case.case_id for case in state.prior_cases],
                    "structural_score": state.prior_cases[0].structural_score,
                    "semantic_score": 0.0,
                    "fused_score": state.prior_cases[0].structural_score,
                    "retrieved_at": datetime.utcnow().strftime(TIMESTAMP_FORMAT),
                },
            )

    except GraphError as error:
        logger.exception("case write-back failed for %s", state.trigger.case_id)
        receipt.errors.append(str(error))
        return receipt

    return verify_case(state, graph, receipt)


def verify_case(state: CaseState, graph: GraphClient, receipt: WriteReceipt) -> WriteReceipt:
    """Read the bundle back and compare it with what we sent."""
    receipt.expected = {
        "evidence_count": len(state.evidence),
        "request_count": len(state.requests),
        "action_count": len(state.initial_actions) + len(state.final_actions),
        "transaction_count": len(state.affected_txn_ids),
        "connected_card_count": len(state.connected_card_ids),
    }

    try:
        result = graph.run("verify_case_bundle", {"case_id": receipt.graph_case_id})
    except GraphError as error:
        logger.exception("case read-back failed for %s", state.trigger.case_id)
        receipt.errors.append(f"read-back failed: {error}")
        return receipt

    payload: dict = {}
    for block in result:
        if isinstance(block, dict):
            payload.update(block)

    case_rows = payload.get("case_details") or []
    if not case_rows:
        receipt.errors.append("case vertex not found on read-back")
        return receipt

    stored_hash = str(case_rows[0].get("bundle_hash", ""))
    if stored_hash != receipt.bundle_hash:
        receipt.errors.append(
            f"bundle hash mismatch: wrote {receipt.bundle_hash}, read {stored_hash}"
        )

    receipt.actual = {key: int(payload.get(key, 0)) for key in receipt.expected}
    for key, expected in receipt.expected.items():
        actual = receipt.actual.get(key, 0)
        if actual != expected:
            receipt.errors.append(f"{key}: wrote {expected}, read back {actual}")

    receipt.verified = not receipt.errors
    if receipt.verified:
        logger.info(
            "case_persisted case=%s graph_id=%s", state.trigger.case_id, receipt.graph_case_id
        )
    else:
        logger.error("case write-back not verified: %s", receipt.summary())
    return receipt
