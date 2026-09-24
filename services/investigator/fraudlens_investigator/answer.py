"""Build the submitted answer file from investigation state.

Every field here is copied from validated state rather than regenerated, so
the JSON cannot disagree with the case the agent actually ran. The model is
constructed through `CaseAnswer`, which enforces the structural invariants;
anything it rejects is a bug in the workflow, not something to work around.
"""

from __future__ import annotations

import logging

from fraudlens_contracts import (
    Action,
    CaseAnswer,
    CaseRecord,
    EvidenceItem,
    EvidenceRequest,
    NextBestActions,
    Pattern,
    Sar,
    Verdict,
)

from .narrative import _activity_dates
from .state import CaseState

logger = logging.getLogger(__name__)


def build_answer(state: CaseState) -> CaseAnswer:
    """Assemble the answer file for one case."""
    current = state.current
    if current is None:
        raise ValueError(f"case {state.trigger.case_id} has no assessment to report")

    # A legitimate verdict carries no episode, no exposure, and no report.
    legitimate = current.verdict is Verdict.LEGITIMATE
    affected = [] if legitimate else list(state.affected_txn_ids)
    exposure = 0.0 if legitimate else round(state.exposure_usd, 2)
    first_suspicious = "" if legitimate else state.first_suspicious_txn_id

    files_report = any(item.action is Action.FILE_REPORT for item in state.final_actions)

    case = CaseRecord(
        status=state.status,
        verdict=current.verdict,
        fraud_probability=current.fraud_probability,
        pattern=Pattern.NONE if legitimate else current.pattern,
        pattern_description=(
            current.pattern_description
            if current.pattern is Pattern.UNDOCUMENTED and not legitimate
            else ""
        ),
        affected_txn_ids=affected,
        first_suspicious_txn_id=first_suspicious,
        connected_card_ids=list(dict.fromkeys(state.connected_card_ids)),
        connected_device_profiles=list(dict.fromkeys(state.connected_device_profiles)),
        exposure_usd=exposure,
        evidence=[
            EvidenceItem(
                claim=record.claim,
                source=record.source,
                ref=record.ref,
                entity_ids=record.entity_ids,
            )
            for record in state.evidence
        ],
        similar_prior_cases=list(dict.fromkeys(case.case_id for case in state.prior_cases)),
        summary=state.summary or "No summary was produced.",
        written_to_graph=state.written_to_graph,
        graph_case_id=state.graph_case_id,
    )

    first_date, last_date = _activity_dates(state)
    sar = (
        Sar(
            file=True,
            reason=state.sar_reason or "Policy 3a: a filing predicate is satisfied.",
            narrative=state.sar_narrative,
            subjects=_sar_subjects(state),
            total_amount_usd=exposure,
            activity_dates=[first_date, last_date],
        )
        if files_report
        else Sar(
            file=False,
            reason=state.sar_reason
            or "Policy 3a: no filing predicate is satisfied, so a case alone is sufficient.",
        )
    )

    return CaseAnswer(
        case_id=state.trigger.case_id,
        case=case,
        evidence_requests=[
            EvidenceRequest(
                type=request.request_type,
                asked_after_step=request.asked_after_step,
                assumed_response=request.assumed_response,
            )
            for request in state.requests
        ],
        next_best_actions=NextBestActions(
            initial=list(state.initial_actions),
            final=list(state.final_actions),
            what_changed=state.what_changed or "nothing",
        ),
        sar=sar,
        stop_reason=state.stop_reason or "The investigation reached a defensible decision.",
        tool_calls=state.tool_calls,
        tokens=state.tokens,
        latency_s=state.latency_s,
    )


def _sar_subjects(state: CaseState) -> list[str]:
    """IDs named in the narrative: the customer, the cards, and the devices.

    Device profiles are descriptive strings rather than dataset IDs, so they
    are included as the README's example does, after the entity IDs.
    """
    subjects: list[str] = [state.trigger.customer_id, state.trigger.card_id]
    subjects.extend(state.connected_card_ids)
    subjects.extend(state.connected_device_profiles[:2])
    # Preserve order, drop blanks and duplicates.
    return list(dict.fromkeys(value for value in subjects if value))
