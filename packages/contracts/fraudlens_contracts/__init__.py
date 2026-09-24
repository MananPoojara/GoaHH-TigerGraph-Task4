"""Shared typed contracts for FraudLens.

This package is the single source of truth for the submitted answer schema and
the supplied-data readers. It performs no I/O against TigerGraph or an LLM and
has no runtime side effects, so every other layer can depend on it safely.
"""

from .answer import (
    ActionRecommendation,
    CaseAnswer,
    CaseRecord,
    EvidenceItem,
    EvidenceRequest,
    NextBestActions,
    Sar,
    count_sentences,
)
from .casepack import (
    CasePackEntry,
    ClosedCase,
    iter_closed_cases,
    load_case_pack,
    load_closed_cases,
)
from .enums import (
    KNOWN_PATTERNS,
    Action,
    CaseStatus,
    CaseTrustTier,
    Channel,
    EvidenceDirection,
    EvidenceRequestType,
    EvidenceSource,
    Pattern,
    Route,
    TriggerType,
    UncertaintyType,
    Verdict,
)

__all__ = [
    "KNOWN_PATTERNS",
    "Action",
    "ActionRecommendation",
    "CaseAnswer",
    "CasePackEntry",
    "CaseRecord",
    "CaseStatus",
    "CaseTrustTier",
    "Channel",
    "ClosedCase",
    "EvidenceDirection",
    "EvidenceItem",
    "EvidenceRequest",
    "EvidenceRequestType",
    "EvidenceSource",
    "NextBestActions",
    "Pattern",
    "Route",
    "Sar",
    "TriggerType",
    "UncertaintyType",
    "Verdict",
    "count_sentences",
    "iter_closed_cases",
    "load_case_pack",
    "load_closed_cases",
]
