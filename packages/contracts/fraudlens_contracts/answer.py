"""The submitted answer contract, exactly as the dataset README defines it.

One JSON file per case, named `<case_id>.json`. Field names, types, and
enumerations below are fixed by the README "Answer Format" section; they are
not a design choice and must not drift.

Structural invariants that depend only on the answer itself are enforced here.
Invariants that need the dataset (ID existence, exposure arithmetic) live in
`fraudlens_contracts.validation`, which takes a resolver.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import (
    Action,
    CaseStatus,
    EvidenceRequestType,
    EvidenceSource,
    Pattern,
    Route,
    Verdict,
)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Sentence-ending punctuation used for the SAR narrative sentence count.
_SENTENCE_END_RE = re.compile(r"[.!?](?:\s|$)")

SAR_NARRATIVE_MIN_SENTENCES = 6
SAR_NARRATIVE_MAX_SENTENCES = 12


def count_sentences(text: str) -> int:
    """Count sentences the way a reviewer would: terminal punctuation runs.

    Decimal amounts such as `$268.43` must not read as a sentence break, so a
    terminator only counts when followed by whitespace or end of string.
    """
    return len(_SENTENCE_END_RE.findall(text.strip()))


class StrictModel(BaseModel):
    """Reject unknown fields so a typo never silently ships in an answer."""

    model_config = ConfigDict(extra="forbid", use_enum_values=False)


class EvidenceItem(StrictModel):
    """One atomic, attributable claim.

    `ref` must be reproducible: an installed query invocation, a document
    section, or an evidence-request id. A claim with no `ref` is inference,
    not evidence, and does not belong in this list.
    """

    claim: str = Field(min_length=1)
    source: EvidenceSource
    ref: str = Field(min_length=1)
    entity_ids: list[str] = Field(default_factory=list)


class EvidenceRequest(StrictModel):
    """A controlled request for evidence the dataset does not supply.

    Responses are simulated for this benchmark; `assumed_response` records
    exactly what was assumed so a reviewer can see the decision basis.
    """

    type: EvidenceRequestType
    asked_after_step: int = Field(ge=0)
    assumed_response: str = Field(min_length=1)


class ActionRecommendation(StrictModel):
    """A recommended action with its approval route and policy citation."""

    action: Action
    route: Route
    reason: str = Field(min_length=1)


class NextBestActions(StrictModel):
    """Initial and final recommendations, and why they differ.

    The README requires `final == initial` when nothing was requested; that
    cross-field rule is checked on the whole answer, where the request list is
    visible.
    """

    initial: list[ActionRecommendation] = Field(default_factory=list)
    final: list[ActionRecommendation] = Field(default_factory=list)
    what_changed: str = Field(min_length=1)


class Sar(StrictModel):
    """The regulatory filing. Most cases never need one."""

    file: bool
    reason: str = Field(min_length=1)
    narrative: str = ""
    subjects: list[str] = Field(default_factory=list)
    total_amount_usd: float = 0.0
    activity_dates: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_filing_shape(self) -> Sar:
        if not self.file:
            # The README fixes the exact empty values for an unfiled report.
            if self.narrative != "":
                raise ValueError("sar.narrative must be empty when sar.file is false")
            if self.subjects:
                raise ValueError("sar.subjects must be empty when sar.file is false")
            if self.total_amount_usd != 0:
                raise ValueError("sar.total_amount_usd must be 0 when sar.file is false")
            if self.activity_dates:
                raise ValueError("sar.activity_dates must be empty when sar.file is false")
            return self

        if not self.narrative.strip():
            raise ValueError("sar.narrative is required when sar.file is true")
        sentences = count_sentences(self.narrative)
        if not SAR_NARRATIVE_MIN_SENTENCES <= sentences <= SAR_NARRATIVE_MAX_SENTENCES:
            raise ValueError(
                f"sar.narrative must be {SAR_NARRATIVE_MIN_SENTENCES}-"
                f"{SAR_NARRATIVE_MAX_SENTENCES} sentences, found {sentences}"
            )
        if not self.subjects:
            raise ValueError("sar.subjects is required when sar.file is true")
        if len(self.activity_dates) != 2:
            raise ValueError("sar.activity_dates must hold exactly a first and last date")
        for value in self.activity_dates:
            if not _DATE_RE.match(value):
                raise ValueError(f"sar.activity_dates entries must be YYYY-MM-DD, got {value!r}")
        if self.activity_dates[0] > self.activity_dates[1]:
            raise ValueError("sar.activity_dates must be ordered first then last")
        if self.total_amount_usd < 0:
            raise ValueError("sar.total_amount_usd must not be negative")
        return self


class CaseRecord(StrictModel):
    """Part 1: the bank's internal investigation record."""

    status: CaseStatus
    verdict: Verdict
    fraud_probability: float = Field(ge=0.0, le=1.0)
    pattern: Pattern
    pattern_description: str = ""
    affected_txn_ids: list[str] = Field(default_factory=list)
    first_suspicious_txn_id: str = ""
    connected_card_ids: list[str] = Field(default_factory=list)
    connected_device_profiles: list[str] = Field(default_factory=list)
    exposure_usd: float = Field(default=0.0, ge=0.0)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    similar_prior_cases: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1)
    written_to_graph: bool = False
    graph_case_id: str = ""

    @model_validator(mode="after")
    def _check_case_shape(self) -> CaseRecord:
        if self.pattern is Pattern.UNDOCUMENTED:
            if not self.pattern_description.strip():
                raise ValueError("pattern_description is required when pattern is 'undocumented'")
        elif self.pattern_description != "":
            raise ValueError("pattern_description must be empty unless pattern is 'undocumented'")

        # README: "For a legitimate verdict, affected_txn_ids is empty,
        # exposure_usd is 0, and sar.file is false."
        if self.verdict is Verdict.LEGITIMATE:
            if self.affected_txn_ids:
                raise ValueError("a legitimate verdict must have no affected transactions")
            if self.exposure_usd != 0:
                raise ValueError("a legitimate verdict must have zero exposure")
            if self.first_suspicious_txn_id:
                raise ValueError("a legitimate verdict must have no first suspicious transaction")

        if self.first_suspicious_txn_id and (
            self.first_suspicious_txn_id not in self.affected_txn_ids
        ):
            raise ValueError("first_suspicious_txn_id must be one of affected_txn_ids")

        if self.affected_txn_ids and not self.first_suspicious_txn_id:
            raise ValueError("affected transactions require a first_suspicious_txn_id")

        for field_name in ("affected_txn_ids", "connected_card_ids", "similar_prior_cases"):
            values = getattr(self, field_name)
            if len(set(values)) != len(values):
                raise ValueError(f"{field_name} must not contain duplicates")

        if self.written_to_graph and not self.graph_case_id:
            raise ValueError("graph_case_id is required when written_to_graph is true")

        return self


class CaseAnswer(StrictModel):
    """The complete answer file for one case."""

    case_id: str = Field(min_length=1)
    case: CaseRecord
    evidence_requests: list[EvidenceRequest] = Field(default_factory=list)
    next_best_actions: NextBestActions
    sar: Sar
    stop_reason: str = Field(min_length=1)
    tool_calls: int = Field(ge=0)
    tokens: int = Field(ge=0)
    latency_s: float = Field(ge=0.0)

    @model_validator(mode="after")
    def _check_cross_field(self) -> CaseAnswer:
        final_actions = [item.action for item in self.next_best_actions.final]

        # README: sar.file "must agree with whether FILE_REPORT appears in
        # your final actions".
        files_report = Action.FILE_REPORT in final_actions
        if self.sar.file != files_report:
            raise ValueError(
                "sar.file must agree with the presence of FILE_REPORT in final actions"
            )

        # Policy 3a: "A report always has a case behind it."
        if files_report and Action.CREATE_CASE not in final_actions:
            raise ValueError("FILE_REPORT requires CREATE_CASE in the same final actions")

        # README: "If you requested nothing, final equals initial."
        if not self.evidence_requests:
            initial = [(i.action, i.route) for i in self.next_best_actions.initial]
            final = [(f.action, f.route) for f in self.next_best_actions.final]
            if initial != final:
                raise ValueError(
                    "final actions must equal initial actions when no evidence was requested"
                )
            if self.next_best_actions.what_changed.strip().lower() != "nothing":
                raise ValueError("what_changed must be 'nothing' when no evidence was requested")

        if self.case.verdict is Verdict.LEGITIMATE and self.sar.file:
            raise ValueError("a legitimate verdict must not file a report")

        if not self.next_best_actions.final:
            raise ValueError("at least one final action is required")

        return self
