"""Closed vocabularies fixed by the challenge dataset README and Fraud Policy v1.0.

Every literal here is copied from the authoritative dataset README. Nothing in
this module may be widened without a corresponding change in the README.
"""

from __future__ import annotations

from enum import StrEnum


class TriggerType(StrEnum):
    """Why an alert exists (`case_pack.csv.trigger_type`)."""

    RISK_SCORE = "risk_score"
    CUSTOMER_REPORT = "customer_report"
    ANALYST_REQUEST = "analyst_request"


class CaseStatus(StrEnum):
    """Where the case stands when the agent stops."""

    OPEN = "open"
    CLOSED_FRAUD = "closed_fraud"
    CLOSED_LEGITIMATE = "closed_legitimate"
    ESCALATED = "escalated"


class Verdict(StrEnum):
    FRAUD = "fraud"
    LEGITIMATE = "legitimate"
    UNCERTAIN = "uncertain"


class Pattern(StrEnum):
    """The five documented patterns, plus `undocumented` and `none`."""

    CARD_TESTING = "card_testing"
    CARD_NOT_PRESENT_FRAUD = "card_not_present_fraud"
    CARD_NOT_PRESENT_NEW_DEVICE = "card_not_present_new_device"
    OUT_OF_REGION_USE = "out_of_region_use"
    ACCOUNT_TAKEOVER = "account_takeover"
    UNDOCUMENTED = "undocumented"
    NONE = "none"


KNOWN_PATTERNS: frozenset[Pattern] = frozenset(
    {
        Pattern.CARD_TESTING,
        Pattern.CARD_NOT_PRESENT_FRAUD,
        Pattern.CARD_NOT_PRESENT_NEW_DEVICE,
        Pattern.OUT_OF_REGION_USE,
        Pattern.ACCOUNT_TAKEOVER,
    }
)


class EvidenceSource(StrEnum):
    """Where an evidence claim came from. Distinguishes fact from inference."""

    GRAPH = "graph"
    DOCUMENT = "document"
    CUSTOMER = "customer"
    EXTERNAL = "external"


class EvidenceDirection(StrEnum):
    """Whether an evidence item argues for fraud, against it, or neither.

    Not part of the submitted answer schema; used internally so the agent can
    be forced to seek and record counter-evidence.
    """

    SUPPORTS_FRAUD = "supports_fraud"
    SUPPORTS_LEGITIMATE = "supports_legitimate"
    CONTEXT = "context"


class EvidenceRequestType(StrEnum):
    """The only evidence requests the policy allows without approval (policy 5)."""

    CUSTOMER_VALIDATION = "customer_validation"
    STEP_UP_AUTH = "step_up_auth"
    ANALYST_INFO = "analyst_info"


class Action(StrEnum):
    """Fraud Policy v1.0 section 1. Identifiers must be used exactly."""

    ALLOW_TRANSACTION = "ALLOW_TRANSACTION"
    DECLINE_TRANSACTION = "DECLINE_TRANSACTION"
    MONITOR_CARD = "MONITOR_CARD"
    MONITOR_CONNECTED_CARDS = "MONITOR_CONNECTED_CARDS"
    WARN_CUSTOMER = "WARN_CUSTOMER"
    VERIFY_WITH_CUSTOMER = "VERIFY_WITH_CUSTOMER"
    STEP_UP_AUTH = "STEP_UP_AUTH"
    BLOCK_CARD = "BLOCK_CARD"
    BLOCK_ALL_CARDS = "BLOCK_ALL_CARDS"
    GENERATE_REPORT = "GENERATE_REPORT"
    CREATE_CASE = "CREATE_CASE"
    FILE_REPORT = "FILE_REPORT"
    ESCALATE_TO_ANALYST = "ESCALATE_TO_ANALYST"
    CLOSE_NO_FRAUD = "CLOSE_NO_FRAUD"


class Route(StrEnum):
    """Approval route. Only `auto` may be executed by the agent."""

    AUTO = "auto"
    L1 = "L1"
    L2 = "L2"


class ActionState(StrEnum):
    """Lifecycle of a recommended action. Recommendation != execution."""

    RECOMMENDED = "recommended"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"


class UncertaintyType(StrEnum):
    MISSING_EVIDENCE = "missing_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    BOTH = "both"
    NONE = "none"


class Channel(StrEnum):
    IN_PERSON = "in_person"
    ONLINE = "online"


class CaseTrustTier(StrEnum):
    """Provenance of a Case vertex used as memory.

    `labeled_history` is the bank's own closed-case truth. `agent_derived`
    cases are this system's own conclusions and must never be presented with
    the same authority.
    """

    LABELED_HISTORY = "labeled_history"
    AGENT_DERIVED = "agent_derived"
    BENCHMARK_OPEN = "benchmark_open"
