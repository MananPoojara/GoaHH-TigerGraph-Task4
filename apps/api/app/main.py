"""FastAPI control plane for the analyst workbench.

Endpoints represent business operations, not internals. The API contains no
fraud-detection logic: it starts investigations, serves their state, and
records approvals. Every decision it exposes was made by the investigator and
the policy engine.

The approval boundary is enforced here as well as in the engine. `/execute`
refuses any action whose route is not `auto` unless a recorded human approval
exists, so a client cannot execute a blocked action by calling the API
directly.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fraudlens_contracts import Action, Route
from fraudlens_investigator import build_answer, run_investigation
from fraudlens_investigator.state import ApprovalRecord
from fraudlens_policy import is_auto_executable, route_for
from pydantic import BaseModel, Field

from .core.config import get_settings
from .services.registry import Runtime, get_runtime

logger = logging.getLogger(__name__)

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(
    title="FraudLens API",
    version="0.1.0",
    description="Agentic fraud investigation over TigerGraph",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin, "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------


class StartInvestigation(BaseModel):
    case_id: str = Field(min_length=1)


class ApprovalRequest(BaseModel):
    action: Action
    decision: str = Field(pattern="^(approved|rejected)$")
    analyst: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class ExecuteRequest(BaseModel):
    action: Action


# ---------------------------------------------------------------------------
# Health and queue
# ---------------------------------------------------------------------------


@app.get("/health")
def health(runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    """Backend readiness. Reports which graph is in use; never a credential."""
    return runtime.health()


@app.get("/cases")
def list_cases(runtime: Runtime = Depends(get_runtime)) -> list[dict[str, Any]]:
    """The analyst queue: every benchmark trigger and its investigation status."""
    rows: list[dict[str, Any]] = []
    for entry in runtime.case_pack:
        state = runtime.registry.get(entry.case_id)
        current = state.current if state else None
        rows.append(
            {
                "case_id": entry.case_id,
                "opened_at": entry.opened_at.isoformat(),
                "trigger_type": entry.trigger_type.value,
                "trigger_text": entry.trigger_text,
                "flagged_txn_id": entry.flagged_txn_id,
                "card_id": entry.card_id,
                "customer_id": entry.customer_id,
                "risk_score": entry.risk_score,
                "investigated": state is not None,
                "status": state.status.value if state else "not_started",
                "verdict": current.verdict.value if current else None,
                "fraud_probability": current.fraud_probability if current else None,
                "pattern": current.pattern.value if current else None,
                "exposure_usd": state.exposure_usd if state else None,
                "pending_approvals": (
                    len([i for i in state.final_actions if i.route is not Route.AUTO])
                    if state
                    else 0
                ),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Investigations
# ---------------------------------------------------------------------------


@app.post("/investigations", status_code=status.HTTP_201_CREATED)
def start_investigation(
    body: StartInvestigation, runtime: Runtime = Depends(get_runtime)
) -> dict[str, Any]:
    """Trigger an investigation and run it to a decision."""
    trigger = runtime.trigger_for(body.case_id)
    if trigger is None:
        raise HTTPException(
            status_code=404, detail=f"case {body.case_id!r} is not in the case pack"
        )

    logger.info("investigation_started case=%s", body.case_id)
    result = run_investigation(trigger, runtime.graph, runtime.llm)
    runtime.registry.put(result.state)

    return _case_payload(result.state)


@app.get("/investigations/{case_id}")
def get_investigation(case_id: str, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return _case_payload(_require_state(runtime, case_id))


# ---------------------------------------------------------------------------
# Case views
# ---------------------------------------------------------------------------


@app.get("/cases/{case_id}")
def get_case(case_id: str, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return _case_payload(_require_state(runtime, case_id))


@app.get("/cases/{case_id}/answer")
def get_case_answer(case_id: str, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    """The exact submission JSON for this case."""
    state = _require_state(runtime, case_id)
    return build_answer(state).model_dump(mode="json")


@app.get("/cases/{case_id}/evidence")
def get_case_evidence(
    case_id: str, runtime: Runtime = Depends(get_runtime)
) -> list[dict[str, Any]]:
    """The evidence ledger, with each claim's direction and provenance."""
    state = _require_state(runtime, case_id)
    return [
        {
            "seq": record.seq,
            "claim": record.claim,
            "source": record.source.value,
            "ref": record.ref,
            "entity_ids": record.entity_ids,
            "direction": record.direction.value,
            "source_family": record.source_family,
            "result_hash": record.result_hash,
        }
        for record in state.evidence
    ]


@app.get("/cases/{case_id}/timeline")
def get_case_timeline(
    case_id: str, runtime: Runtime = Depends(get_runtime)
) -> list[dict[str, Any]]:
    state = _require_state(runtime, case_id)
    return [
        {
            "step": event.step,
            "at": event.at.isoformat(timespec="seconds"),
            "node": event.node,
            "event": event.event,
            "detail": event.detail,
        }
        for event in state.timeline
    ]


@app.get("/cases/{case_id}/actions")
def get_case_actions(case_id: str, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    state = _require_state(runtime, case_id)
    return {
        "initial": [_action_payload(state, i, "initial") for i in state.initial_actions],
        "final": [_action_payload(state, i, "final") for i in state.final_actions],
        "what_changed": state.what_changed,
        "triggered_rules": state.triggered_rules,
        "barred_actions": state.barred_actions,
        "executed": [action.value for action in state.executed_actions],
        "approvals": [
            {
                "action": record.action.value,
                "route": record.route,
                "decided_by": record.decided_by,
                "decision": record.decision,
                "rationale": record.rationale,
                "decided_at": record.decided_at.isoformat(timespec="seconds"),
            }
            for record in state.approvals
        ],
    }


@app.get("/cases/{case_id}/graph")
def get_case_graph(case_id: str, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    """A bounded evidence subgraph for the relationship view."""
    state = _require_state(runtime, case_id)
    return _build_subgraph(state)


# ---------------------------------------------------------------------------
# Approval and execution
# ---------------------------------------------------------------------------


@app.post("/cases/{case_id}/approve")
def approve_action(
    case_id: str, body: ApprovalRequest, runtime: Runtime = Depends(get_runtime)
) -> dict[str, Any]:
    """Record a named analyst's decision on an L1/L2 action.

    The record is appended. It never rewrites what the agent recommended,
    because an override is a separate event in the audit trail.
    """
    state = _require_state(runtime, case_id)

    match = next((i for i in state.final_actions if i.action is body.action), None)
    if match is None:
        raise HTTPException(
            status_code=400,
            detail=f"{body.action.value} is not among the final recommended actions",
        )
    if match.route is Route.AUTO:
        raise HTTPException(
            status_code=400,
            detail=f"{body.action.value} routes auto and does not require approval",
        )

    state.approvals.append(
        ApprovalRecord(
            action=body.action,
            route=match.route.value,
            decided_by=body.analyst,
            decision=body.decision,
            rationale=body.rationale,
        )
    )
    state.log(
        "human_approval",
        "approval_recorded",
        f"{body.action.value} {body.decision} by {body.analyst}",
    )
    runtime.registry.put(state)
    logger.info(
        "approval_recorded case=%s action=%s decision=%s",
        case_id,
        body.action.value,
        body.decision,
    )
    return get_case_actions(case_id, runtime)


@app.post("/cases/{case_id}/execute")
def execute_action(
    case_id: str, body: ExecuteRequest, runtime: Runtime = Depends(get_runtime)
) -> dict[str, Any]:
    """Execute an action, if and only if it is permitted.

    Financial effects are simulated for this prototype. The authorization
    check is not: an action that needs approval is refused here even when the
    caller asks nicely, which is the whole point of the boundary.
    """
    state = _require_state(runtime, case_id)

    match = next((i for i in state.final_actions if i.action is body.action), None)
    if match is None:
        raise HTTPException(
            status_code=400,
            detail=f"{body.action.value} is not among the final recommended actions",
        )

    expected_route = route_for(body.action, state.exposure_usd)
    if not is_auto_executable(body.action):
        approved = any(
            record.action is body.action and record.decision == "approved"
            for record in state.approvals
        )
        if not approved:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"{body.action.value} requires {expected_route.value} approval "
                    "before it can be executed"
                ),
            )

    if body.action not in state.executed_actions:
        state.executed_actions.append(body.action)
    state.log(
        "execute",
        "action_executed",
        f"{body.action.value} executed (simulated={runtime.settings.simulate_external_actions})",
    )
    runtime.registry.put(state)
    logger.info("action_executed case=%s action=%s", case_id, body.action.value)

    return {
        "case_id": case_id,
        "action": body.action.value,
        "route": expected_route.value,
        "executed": True,
        "simulated": runtime.settings.simulate_external_actions,
        "executed_at": datetime.utcnow().isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_state(runtime: Runtime, case_id: str):
    state = runtime.registry.get(case_id)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail=f"case {case_id!r} has not been investigated yet",
        )
    return state


def _action_payload(state, item, stage: str) -> dict[str, Any]:
    approval = next(
        (record for record in reversed(state.approvals) if record.action is item.action),
        None,
    )
    if item.route is Route.AUTO:
        action_state = "executed" if item.action in state.executed_actions else "recommended"
    elif approval is None:
        action_state = "pending_approval"
    elif approval.decision == "approved":
        action_state = "executed" if item.action in state.executed_actions else "approved"
    else:
        action_state = "rejected"

    return {
        "action": item.action.value,
        "route": item.route.value,
        "reason": item.reason,
        "stage": stage,
        "state": action_state,
        "requires_approval": item.route is not Route.AUTO,
    }


def _case_payload(state) -> dict[str, Any]:
    current = state.current
    return {
        "case_id": state.trigger.case_id,
        "run_id": state.run_id,
        "status": state.status.value,
        "trigger": {
            "type": state.trigger.trigger_type.value,
            "text": state.trigger.trigger_text,
            "flagged_txn_id": state.trigger.flagged_txn_id,
            "card_id": state.trigger.card_id,
            "customer_id": state.trigger.customer_id,
            "opened_at": state.trigger.opened_at.isoformat(),
            "risk_score": state.trigger.risk_score,
        },
        "assessment": (
            {
                "verdict": current.verdict.value,
                "fraud_probability": current.fraud_probability,
                "pattern": current.pattern.value,
                "pattern_description": current.pattern_description,
                "confidence": current.confidence,
                "uncertainty": current.uncertainty.value,
                "independent_signal_count": current.independent_signal_count,
                "conflicting_evidence": current.conflicting_evidence,
                "rationale": current.rationale,
                "trigger_risk_score": current.trigger_risk_score,
            }
            if current
            else None
        ),
        "assessment_history": [
            {
                "stage": item.stage,
                "verdict": item.verdict.value,
                "fraud_probability": item.fraud_probability,
                "pattern": item.pattern.value,
            }
            for item in state.assessments
        ],
        "hypotheses": [
            {"pattern": h.pattern.value, "score": h.score, "rationale": h.rationale}
            for h in state.hypotheses
        ],
        "scope": {
            "affected_txn_ids": state.affected_txn_ids,
            "first_suspicious_txn_id": state.first_suspicious_txn_id,
            "exposure_usd": state.exposure_usd,
            "connected_card_ids": state.connected_card_ids,
            "connected_device_profiles": state.connected_device_profiles,
        },
        "evidence_count": len(state.evidence),
        "counter_evidence_count": len(state.counter_evidence()),
        "prior_cases": [
            {
                "case_id": c.case_id,
                "outcome": c.outcome,
                "pattern": c.pattern,
                "link_reason": c.link_reason,
                "structural_score": c.structural_score,
                "analyst_notes": c.analyst_notes[:400],
            }
            for c in state.prior_cases
        ],
        "evidence_requests": [
            {
                "request_no": r.request_no,
                "type": r.request_type.value,
                "asked_after_step": r.asked_after_step,
                "reason": r.reason,
                "assumed_response": r.assumed_response,
                "simulated": r.simulated,
            }
            for r in state.requests
        ],
        "sar": {
            "file": state.sar_file,
            "reason": state.sar_reason,
            "narrative": state.sar_narrative,
        },
        "summary": state.summary,
        "stop_reason": state.stop_reason,
        "written_to_graph": state.written_to_graph,
        "graph_case_id": state.graph_case_id,
        "telemetry": {
            "tool_calls": state.tool_calls,
            "tokens": state.tokens,
            "latency_s": state.latency_s,
            "steps": state.step,
        },
        "errors": state.errors,
    }


def _build_subgraph(state) -> dict[str, Any]:
    """Nodes and edges for the relationship view, bounded for readability."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_node(node_id: str, label: str, kind: str, **extra: Any) -> None:
        if node_id and node_id not in seen:
            seen.add(node_id)
            nodes.append({"id": node_id, "label": label, "kind": kind, **extra})

    customer = state.trigger.customer_id
    card = state.trigger.card_id
    add_node(customer, customer, "customer")
    add_node(card, card, "card")
    edges.append({"source": customer, "target": card, "label": "OWNS"})

    amounts: dict[str, float] = {}
    for row in state.observations.get("window", {}).get("window") or []:
        amounts[row["txn_id"]] = float(row.get("amount", 0) or 0)

    for txn_id in state.affected_txn_ids[:25]:
        amount = amounts.get(txn_id, 0.0)
        add_node(
            txn_id,
            f"{txn_id} (${abs(amount):,.2f})",
            "transaction",
            affected=True,
            amount=amount,
        )
        edges.append({"source": card, "target": txn_id, "label": "MADE"})

    for index, device in enumerate(state.connected_device_ids[:5]):
        readable = (
            state.connected_device_profiles[index]
            if index < len(state.connected_device_profiles)
            else device
        )
        add_node(device, readable, "device")
        for txn_id in state.affected_txn_ids[:25]:
            edges.append({"source": txn_id, "target": device, "label": "FROM_DEVICE"})
            break

    for other in state.connected_card_ids[:10]:
        add_node(other, other, "connected_card")
        if state.connected_device_ids:
            edges.append(
                {
                    "source": state.connected_device_ids[0],
                    "target": other,
                    "label": "ALSO_USED_BY",
                }
            )

    for prior in state.prior_cases[:5]:
        add_node(prior.case_id, f"{prior.case_id} ({prior.outcome})", "prior_case")
        edges.append(
            {"source": card, "target": prior.case_id, "label": prior.link_reason or "SIMILAR_TO"}
        )

    return {"nodes": nodes, "edges": edges}
