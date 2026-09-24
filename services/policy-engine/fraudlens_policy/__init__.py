"""Deterministic Fraud Policy v1.0 engine.

Nothing in this package calls a model or touches the graph. Given the same
facts it always returns the same decision, which is what makes the approval
boundary auditable.
"""

from .engine import (
    ACTION_ORDER,
    PolicyDecision,
    SuppressedAction,
    case_required,
    decide,
    report_required,
)
from .facts import CardTestingFacts, CustomerResponse, PolicyFacts, SharedOriginFacts
from .routing import (
    BLOCK_CARD_L2_THRESHOLD_USD,
    is_auto_executable,
    requires_approval,
    route_for,
)
from .rules import ALL_RULES, RuleEvaluation, RuleOutcome, evaluate_rules

__all__ = [
    "ACTION_ORDER",
    "ALL_RULES",
    "BLOCK_CARD_L2_THRESHOLD_USD",
    "CardTestingFacts",
    "CustomerResponse",
    "PolicyDecision",
    "PolicyFacts",
    "RuleEvaluation",
    "RuleOutcome",
    "SharedOriginFacts",
    "SuppressedAction",
    "case_required",
    "decide",
    "evaluate_rules",
    "is_auto_executable",
    "report_required",
    "requires_approval",
    "route_for",
]
