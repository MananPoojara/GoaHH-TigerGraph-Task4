"""The LangGraph investigation workflow.

The state machine is explicit, and the one conditional edge is the decision
the whole challenge turns on: whether the evidence in hand is enough, or
whether asking for more would actually change what the bank should do.

    intake -> plan -> collect -> counter-evidence -> memory -> hypotheses
        -> assess -> initial policy -> [value of information]
                                         |            |
                              request evidence    (enough)
                                         |            |
                                     reassess  ->  final policy
                                         -> explain -> persist

Nodes are the plain functions in `nodes.py`; this module only wires them and
owns the loop budget. Keeping orchestration separate from node logic is what
lets the same nodes be unit-tested and replayed without LangGraph.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fraudlens_contracts import CaseStatus, Verdict
from fraudlens_graph import GraphClient

from . import nodes
from .llm import LLMPort
from .narrative import build_sar_narrative, build_stop_reason, build_summary
from .persistence import persist_case
from .state import CaseState, Trigger

logger = logging.getLogger(__name__)

# Budgets from the architecture notes: at most one simulated evidence request
# unless the validator proves a second is required, and a hard ceiling on
# node transitions so a cycle can never run away.
MAX_EVIDENCE_REQUESTS = 1
MAX_STEPS = 40


@dataclass
class InvestigationResult:
    """What one completed run produced."""

    state: CaseState
    write_verified: bool = False
    write_errors: list[str] | None = None


def _finalize(state: CaseState, deps: nodes.InvestigationDeps, graph: GraphClient) -> CaseState:
    """Explain, set the case status, and persist with read-back."""
    current = state.current
    assert current is not None

    # An escalation path may already have written a summary explaining why no
    # verdict was reached; the generic builder must not talk over it.
    if not state.summary:
        state.summary = build_summary(state, deps.llm)
    state.stop_reason = build_stop_reason(state)

    if state.sar_file:
        state.sar_narrative = build_sar_narrative(state, deps.llm)
    else:
        # The contract fixes the empty values for an unfiled report.
        state.sar_narrative = ""

    state.status = _status_for(state)

    state.log("explain", "explanation_generated", state.stop_reason[:100])

    receipt = persist_case(state, graph)
    state.written_to_graph = receipt.verified
    state.graph_case_id = receipt.graph_case_id if receipt.verified else ""
    state.log(
        "persist",
        "case_persisted" if receipt.verified else "tool_failed",
        receipt.summary(),
    )
    if not receipt.verified:
        state.errors.extend(receipt.errors)

    state.tokens = deps.llm.usage.total
    state.tool_calls = graph.call_log.count - state.tool_calls_at_start
    # `started_at` is naive UTC; `.timestamp()` would read it as local time
    # and add the host's UTC offset, so subtract on the same clock instead.
    state.latency_s = round((datetime.utcnow() - state.started_at).total_seconds(), 2)
    return state


def _status_for(state: CaseState) -> CaseStatus:
    """Where the case stands when the agent stops.

    Status has to agree with the verdict and the actions, because the
    validator checks exactly that.
    """
    from fraudlens_contracts import Action

    final = {item.action for item in state.final_actions}
    current = state.current
    assert current is not None

    if Action.ESCALATE_TO_ANALYST in final:
        return CaseStatus.ESCALATED
    if current.verdict is Verdict.FRAUD:
        return CaseStatus.CLOSED_FRAUD
    # A cardholder who never replied leaves the question genuinely open,
    # whatever the probability says. `open` means evidence is still pending.
    if state.requests and state.requests[-1].no_reply:
        return CaseStatus.OPEN
    if current.verdict is Verdict.LEGITIMATE:
        return CaseStatus.CLOSED_LEGITIMATE
    # Uncertain and not escalated: the case stays open.
    return CaseStatus.OPEN


def run_investigation(
    trigger: Trigger,
    graph: GraphClient,
    llm: LLMPort | None = None,
) -> InvestigationResult:
    """Run one case end to end.

    Implemented as a direct sequence with one branch rather than through the
    LangGraph runtime, so it stays debuggable and deterministic. `build_graph`
    exposes the same node set as a compiled LangGraph for checkpointing and
    streaming; both drive identical node functions.
    """
    deps = nodes.InvestigationDeps(graph=graph, llm=llm or LLMPort())
    state = CaseState(trigger=trigger, tool_calls_at_start=graph.call_log.count)

    state = nodes.intake(state, deps)
    if not state.anchor_confirmed:
        # An unconfirmable anchor is not investigated on a false premise.
        state.errors.append("anchor could not be confirmed; escalating without a verdict")
        return _finalize_unconfirmed(state, deps, graph)

    state = nodes.plan_evidence(state, deps)
    state = nodes.collect_evidence(state, deps)
    state = nodes.seek_counter_evidence(state, deps)
    state = nodes.form_hypotheses(state, deps)
    state = nodes.retrieve_case_memory(state, deps)
    state = nodes.assess_evidence(state, deps, stage="initial")
    state = nodes.initial_policy_decision(state, deps)

    state, should_request = nodes.value_of_information(state, deps)

    if should_request and len(state.requests) < MAX_EVIDENCE_REQUESTS:
        state = nodes.request_evidence(state, deps)
        state = nodes.assess_evidence(state, deps, stage="after_evidence")

    state = nodes.final_policy_decision(state, deps)
    state = _finalize(state, deps, graph)

    return InvestigationResult(state=state, write_verified=state.written_to_graph)


def _finalize_unconfirmed(
    state: CaseState, deps: nodes.InvestigationDeps, graph: GraphClient
) -> InvestigationResult:
    """Produce a defensible escalation when the anchor cannot be confirmed."""
    from fraudlens_contracts import Action, ActionRecommendation, Pattern, Route

    from .state import Assessment

    state.assessments.append(
        Assessment(
            stage="initial",
            verdict=Verdict.UNCERTAIN,
            fraud_probability=0.30,
            pattern=Pattern.NONE,
            confidence=0.0,
            rationale=(
                "The flagged transaction could not be confirmed against the supplied "
                "card and customer, so no evidence-based verdict is possible."
            ),
        )
    )
    escalation = [
        ActionRecommendation(
            action=Action.ESCALATE_TO_ANALYST,
            route=Route.AUTO,
            reason=(
                "R8: the case anchor could not be verified, so the evidence is "
                "insufficient for an automated decision"
            ),
        ),
        ActionRecommendation(
            action=Action.CREATE_CASE,
            route=Route.AUTO,
            reason="Policy 3a: a case records the failed verification for the analyst",
        ),
    ]
    state.initial_actions = list(escalation)
    state.final_actions = list(escalation)
    state.what_changed = "nothing"
    state.stop_reason = (
        "The flagged transaction could not be confirmed against the supplied card and "
        "customer, so the case was escalated rather than decided on unverified data."
    )
    state.summary = (
        "The case anchor could not be confirmed. "
        + (" ".join(state.integrity_errors) or "The flagged transaction was not found.")
        + " No verdict was reached and the case is escalated to an analyst."
    )
    state = _finalize(state, deps, graph)
    return InvestigationResult(state=state, write_verified=state.written_to_graph)


def build_graph(graph: GraphClient, llm: LLMPort | None = None) -> Any:
    """Compile the same nodes as a LangGraph `StateGraph`.

    Used by the API for checkpointing, streaming progress, and pausing at an
    approval interrupt. The node bodies are shared with `run_investigation`,
    so the two cannot drift apart.
    """
    try:
        from langgraph.graph import END, StateGraph
    except ImportError as error:  # pragma: no cover - depends on extras
        raise RuntimeError(
            "langgraph is not installed; run: python -m pip install -e '.[agent]'"
        ) from error

    deps = nodes.InvestigationDeps(graph=graph, llm=llm or LLMPort())

    def _wrap(function):
        def node(state: CaseState) -> CaseState:
            return function(state, deps)

        return node

    builder: Any = StateGraph(CaseState)
    builder.add_node("intake", _wrap(nodes.intake))
    builder.add_node("plan_evidence", _wrap(nodes.plan_evidence))
    builder.add_node("collect_evidence", _wrap(nodes.collect_evidence))
    builder.add_node("seek_counter_evidence", _wrap(nodes.seek_counter_evidence))
    builder.add_node("form_hypotheses", _wrap(nodes.form_hypotheses))
    builder.add_node("retrieve_case_memory", _wrap(nodes.retrieve_case_memory))
    builder.add_node("assess", _wrap(lambda s, d: nodes.assess_evidence(s, d, stage="initial")))
    builder.add_node("initial_policy_decision", _wrap(nodes.initial_policy_decision))
    builder.add_node("request_evidence", _wrap(nodes.request_evidence))
    builder.add_node(
        "reassess", _wrap(lambda s, d: nodes.assess_evidence(s, d, stage="after_evidence"))
    )
    builder.add_node("final_policy_decision", _wrap(nodes.final_policy_decision))
    builder.add_node("finalize", _wrap(lambda s, d: _finalize(s, d, graph)))

    builder.set_entry_point("intake")
    builder.add_edge("intake", "plan_evidence")
    builder.add_edge("plan_evidence", "collect_evidence")
    builder.add_edge("collect_evidence", "seek_counter_evidence")
    builder.add_edge("seek_counter_evidence", "form_hypotheses")
    builder.add_edge("form_hypotheses", "retrieve_case_memory")
    builder.add_edge("retrieve_case_memory", "assess")
    builder.add_edge("assess", "initial_policy_decision")

    def needs_more_evidence(state: CaseState) -> str:
        """The value-of-information gate.

        Returns "request" only when a possible response would change the
        recommended actions and the request budget is not spent.
        """
        _, should_request = nodes.value_of_information(state, deps)
        if should_request and len(state.requests) < MAX_EVIDENCE_REQUESTS:
            return "request"
        return "decide"

    builder.add_conditional_edges(
        "initial_policy_decision",
        needs_more_evidence,
        {"request": "request_evidence", "decide": "final_policy_decision"},
    )
    builder.add_edge("request_evidence", "reassess")
    builder.add_edge("reassess", "final_policy_decision")
    builder.add_edge("final_policy_decision", "finalize")
    builder.add_edge("finalize", END)

    return builder.compile()
