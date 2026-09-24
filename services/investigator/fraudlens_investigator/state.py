"""The investigation state.

One typed object is threaded through every node and checkpointed between
them. Prose is always a derived view: the ledgers below stay structured so a
run can be replayed, diffed, and audited without re-reading a narrative.

The separation that matters most here is evidence from inference. `evidence`
holds facts with a source and a replayable reference. `hypotheses` and
`assessment` hold what the agent concluded from them. Nothing may move from
the second list into the first.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fraudlens_contracts import (
    Action,
    ActionRecommendation,
    CaseStatus,
    EvidenceDirection,
    EvidenceRequestType,
    EvidenceSource,
    Pattern,
    TriggerType,
    UncertaintyType,
    Verdict,
)
from pydantic import BaseModel, ConfigDict, Field


class StateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)


class Trigger(StateModel):
    """Why this investigation exists."""

    case_id: str
    trigger_type: TriggerType
    trigger_text: str
    flagged_txn_id: str
    card_id: str
    customer_id: str
    opened_at: datetime
    risk_score: float | None = None

    @property
    def cutoff(self) -> datetime:
        """Decision time. Nothing after this may inform the case."""
        return self.opened_at

    @property
    def customer_disputed(self) -> bool:
        return self.trigger_type is TriggerType.CUSTOMER_REPORT


class EvidenceRecord(StateModel):
    """One fact, with provenance sufficient to replay it."""

    seq: int
    claim: str
    source: EvidenceSource
    ref: str
    entity_ids: list[str] = Field(default_factory=list)
    direction: EvidenceDirection = EvidenceDirection.CONTEXT
    # Evidence from the same family is not independent: a risk score and a
    # feature derived from it must not count as two corroborating signals.
    source_family: str = "graph"
    collected_at: datetime = Field(default_factory=datetime.utcnow)
    result_hash: str = ""
    query_version: str = "1.0"

    @property
    def supports_fraud(self) -> bool:
        return self.direction is EvidenceDirection.SUPPORTS_FRAUD

    @property
    def supports_legitimate(self) -> bool:
        return self.direction is EvidenceDirection.SUPPORTS_LEGITIMATE


class Hypothesis(StateModel):
    """A candidate explanation, kept alive until evidence rules it out."""

    pattern: Pattern
    score: float = Field(ge=0.0, le=1.0)
    rationale: str = ""
    supporting_evidence: list[int] = Field(default_factory=list)
    contradicting_evidence: list[int] = Field(default_factory=list)


class PriorCase(StateModel):
    """A retrieved closed case used as memory."""

    case_id: str
    outcome: str
    pattern: str
    customer_id: str = ""
    card_id: str = ""
    exposure_usd: float = 0.0
    structural_score: float = 0.0
    semantic_score: float = 0.0
    link_reason: str = ""
    analyst_notes: str = ""


class RequestRecord(StateModel):
    """A controlled evidence request and the response assumed for it."""

    request_no: int
    request_type: EvidenceRequestType
    asked_after_step: int
    reason: str
    assumed_response: str
    simulated: bool = True
    simulator_version: str = "1.0"
    customer_denied: bool = False
    customer_confirmed: bool = False
    no_reply: bool = False


class Assessment(StateModel):
    """A probability and its justification at one point in the run.

    Assessments are appended, never edited, so the change a piece of evidence
    caused stays visible.
    """

    stage: str
    verdict: Verdict
    fraud_probability: float = Field(ge=0.0, le=1.0)
    pattern: Pattern
    pattern_description: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    uncertainty: UncertaintyType = UncertaintyType.NONE
    independent_signal_count: int = 0
    conflicting_evidence: bool = False
    rationale: str = ""
    # The supplied risk score is recorded alongside, never copied into the
    # probability: the README warns it is an input, not an answer.
    trigger_risk_score: float | None = None


class TimelineEvent(StateModel):
    """One step, for the UI timeline and the audit trail."""

    at: datetime = Field(default_factory=datetime.utcnow)
    step: int
    node: str
    event: str
    detail: str = ""


class ApprovalRecord(StateModel):
    """A human decision on an L1/L2 action.

    Appended rather than applied in place: an override must not rewrite what
    the agent recommended.
    """

    action: Action
    route: str
    decided_by: str
    decision: str  # approved | rejected
    rationale: str
    decided_at: datetime = Field(default_factory=datetime.utcnow)
    evidence_snapshot_hash: str = ""


class CaseState(StateModel):
    """Everything known about one investigation."""

    # --- identity ---------------------------------------------------------
    trigger: Trigger
    run_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: CaseStatus = CaseStatus.OPEN
    step: int = 0

    # --- anchor -----------------------------------------------------------
    anchor: dict[str, Any] = Field(default_factory=dict)
    anchor_confirmed: bool = False
    integrity_errors: list[str] = Field(default_factory=list)

    # --- evidence ---------------------------------------------------------
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    baseline: dict[str, Any] = Field(default_factory=dict)
    observations: dict[str, Any] = Field(default_factory=dict)

    # --- reasoning --------------------------------------------------------
    plan: list[str] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    assessments: list[Assessment] = Field(default_factory=list)

    # --- scope ------------------------------------------------------------
    affected_txn_ids: list[str] = Field(default_factory=list)
    first_suspicious_txn_id: str = ""
    exposure_usd: float = 0.0
    connected_card_ids: list[str] = Field(default_factory=list)
    connected_device_ids: list[str] = Field(default_factory=list)
    connected_device_profiles: list[str] = Field(default_factory=list)

    # --- memory -----------------------------------------------------------
    prior_cases: list[PriorCase] = Field(default_factory=list)
    policy_citations: list[str] = Field(default_factory=list)

    # --- requests and decisions -------------------------------------------
    requests: list[RequestRecord] = Field(default_factory=list)
    initial_actions: list[ActionRecommendation] = Field(default_factory=list)
    final_actions: list[ActionRecommendation] = Field(default_factory=list)
    triggered_rules: list[str] = Field(default_factory=list)
    barred_actions: list[str] = Field(default_factory=list)
    approvals: list[ApprovalRecord] = Field(default_factory=list)
    executed_actions: list[Action] = Field(default_factory=list)

    # --- output -----------------------------------------------------------
    what_changed: str = "nothing"
    stop_reason: str = ""
    summary: str = ""
    sar_file: bool = False
    sar_reason: str = ""
    sar_narrative: str = ""
    written_to_graph: bool = False
    graph_case_id: str = ""

    # --- telemetry --------------------------------------------------------
    timeline: list[TimelineEvent] = Field(default_factory=list)
    tool_calls: int = 0
    # The graph client is reused across the 20 cases, so per-case tool counts
    # are a delta from this baseline rather than the client's lifetime total.
    tool_calls_at_start: int = 0
    tokens: int = 0
    started_at: datetime = Field(default_factory=datetime.utcnow)
    latency_s: float = 0.0
    errors: list[str] = Field(default_factory=list)

    # --- helpers ----------------------------------------------------------

    @property
    def current(self) -> Assessment | None:
        """The latest assessment, or None before the first one."""
        return self.assessments[-1] if self.assessments else None

    @property
    def evidence_requested(self) -> bool:
        return bool(self.requests)

    def log(self, node: str, event: str, detail: str = "") -> None:
        """Record a timeline step. This is the audit trail and the UI feed."""
        self.step += 1
        self.timeline.append(TimelineEvent(step=self.step, node=node, event=event, detail=detail))

    def add_evidence(
        self,
        claim: str,
        source: EvidenceSource,
        ref: str,
        *,
        entity_ids: list[str] | None = None,
        direction: EvidenceDirection = EvidenceDirection.CONTEXT,
        source_family: str = "graph",
        result_hash: str = "",
    ) -> EvidenceRecord:
        """Append one fact to the ledger.

        Returns the record so a caller can reference its sequence number when
        linking a hypothesis to the evidence behind it.
        """
        record = EvidenceRecord(
            seq=len(self.evidence) + 1,
            claim=claim,
            source=source,
            ref=ref,
            entity_ids=entity_ids or [],
            direction=direction,
            source_family=source_family,
            result_hash=result_hash,
        )
        self.evidence.append(record)
        return record

    def independent_families(self) -> set[str]:
        """Distinct source families among fraud-supporting evidence.

        Independence is counted by family, not by item: three claims derived
        from the same risk score are one signal, not three.
        """
        return {
            record.source_family
            for record in self.evidence
            if record.direction is EvidenceDirection.SUPPORTS_FRAUD
        }

    def counter_evidence(self) -> list[EvidenceRecord]:
        return [record for record in self.evidence if record.supports_legitimate]

    def latest_customer_response(self) -> RequestRecord | None:
        return self.requests[-1] if self.requests else None
