"""Composition of rule outcomes into a single authorized decision.

This module owns the only path from a fact pattern to a recommended action
list. The agent may not append, reorder, or re-route what comes out of here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fraudlens_contracts import Action, ActionRecommendation, Pattern, Route, Verdict

from .facts import PolicyFacts
from .routing import route_for
from .rules import (
    CASE_REQUIRED_PROBABILITY,
    R2_REPORT_EXPOSURE_USD,
    RuleEvaluation,
    evaluate_rules,
)

# Policy 1: "Order them by what happens first." Containment precedes
# verification, verification precedes a block, and record-keeping follows the
# operational response.
ACTION_ORDER: tuple[Action, ...] = (
    Action.ALLOW_TRANSACTION,
    Action.DECLINE_TRANSACTION,
    Action.STEP_UP_AUTH,
    Action.VERIFY_WITH_CUSTOMER,
    Action.BLOCK_CARD,
    Action.BLOCK_ALL_CARDS,
    Action.CREATE_CASE,
    Action.FILE_REPORT,
    Action.MONITOR_CARD,
    Action.MONITOR_CONNECTED_CARDS,
    Action.WARN_CUSTOMER,
    Action.GENERATE_REPORT,
    Action.ESCALATE_TO_ANALYST,
    Action.CLOSE_NO_FRAUD,
)

_ORDER_INDEX: dict[Action, int] = {action: i for i, action in enumerate(ACTION_ORDER)}


@dataclass
class SuppressedAction:
    """An action a rule required but a stronger rule barred.

    Retained so the explanation can say why a block did not happen, which is
    as important to an auditor as the actions that did.
    """

    action: Action
    required_by: str
    forbidden_by: str
    reason: str


@dataclass
class BarredAction:
    """An action a triggered rule bars, whether or not anything asked for it.

    R1, R3, R7, and R10 are prohibitions. Recording them even when no rule
    requested the action lets the explanation answer "why was this card not
    blocked?", which an auditor asks as often as "why was it blocked?".
    """

    action: Action
    forbidden_by: str
    reason: str


@dataclass
class PolicyDecision:
    """The authorized outcome for one fact pattern."""

    case_id: str
    actions: list[ActionRecommendation] = field(default_factory=list)
    triggered_rules: list[str] = field(default_factory=list)
    suppressed: list[SuppressedAction] = field(default_factory=list)
    barred: list[BarredAction] = field(default_factory=list)
    requires_case: bool = False
    requires_report: bool = False
    report_reason: str = ""
    evaluation: RuleEvaluation | None = None

    def is_barred(self, action: Action) -> bool:
        return any(item.action is action for item in self.barred)

    @property
    def action_list(self) -> list[Action]:
        return [item.action for item in self.actions]

    @property
    def pending_approval(self) -> list[ActionRecommendation]:
        """Actions the agent may not execute on its own."""
        return [item for item in self.actions if item.route is not Route.AUTO]

    @property
    def auto_executable(self) -> list[ActionRecommendation]:
        return [item for item in self.actions if item.route is Route.AUTO]


def case_required(facts: PolicyFacts) -> tuple[bool, str]:
    """Policy 3a: when an internal case must be opened.

    Open one whenever probability reaches 0.30, whenever evidence is
    requested, or whenever a customer disputes a charge.
    """
    if facts.fraud_probability >= CASE_REQUIRED_PROBABILITY:
        return True, (
            f"Policy 3a: fraud probability {facts.fraud_probability:.2f} reaches "
            f"{CASE_REQUIRED_PROBABILITY:.2f}"
        )
    if facts.evidence_requested:
        return True, "Policy 3a: evidence was requested during the investigation"
    if facts.customer_disputed:
        return True, "Policy 3a: the cardholder disputed a charge"
    return False, ""


def report_required(facts: PolicyFacts) -> tuple[bool, str]:
    """Policy 3a: when a suspicious activity report must be filed.

    Requires confirmed or strongly suspected fraud AND at least one of the
    listed predicates. Most cases never need a report.
    """
    if not facts.strongly_suspected_or_confirmed:
        return False, (
            "Policy 3a: fraud is not confirmed or strongly suspected, so no report is due"
        )

    if facts.exposure_usd > R2_REPORT_EXPOSURE_USD:
        return True, (
            f"Policy 3a: exposure ${facts.exposure_usd:,.2f} exceeds "
            f"${R2_REPORT_EXPOSURE_USD:,.0f}"
        )
    if facts.connected_to_shared_device_profile:
        return True, "Policy 3a: the activity connects to a shared device profile"
    if facts.connected_to_other_card_fraud:
        return True, "Policy 3a: the activity connects to another card's confirmed fraud"
    if facts.shared_origin.ring_observed:
        return True, (
            f"Policy 3a: the activity connects to a shared "
            f"{facts.shared_origin.shared_element_kind or 'origin'} cluster"
        )
    if facts.coordinated_or_undocumented_abuse or facts.pattern is Pattern.UNDOCUMENTED:
        return True, "Policy 3a: the pattern is coordinated or undocumented (R9)"

    return False, (
        "Policy 3a: fraud is suspected but no exposure, connection, or coordination "
        "predicate holds, so a case alone is sufficient"
    )


def _baseline_actions(facts: PolicyFacts) -> list[tuple[Action, str]]:
    """Actions implied by the verdict when no rule speaks to the outcome.

    Without this the engine could return an empty recommendation for a clean
    legitimate case, which is itself a decision the bank has to record.
    """
    if facts.verdict is Verdict.LEGITIMATE:
        return [
            (Action.ALLOW_TRANSACTION, "Verdict legitimate: the flagged transaction stands"),
            (Action.CLOSE_NO_FRAUD, "Verdict legitimate: close the alert"),
        ]
    if facts.verdict is Verdict.FRAUD:
        return [
            (
                Action.BLOCK_CARD,
                f"Verdict fraud at probability {facts.fraud_probability:.2f}: "
                "contain the compromised card",
            )
        ]
    # Uncertain with no rule fired: keep the card live but watch it.
    return [
        (
            Action.MONITOR_CARD,
            f"Verdict uncertain at probability {facts.fraud_probability:.2f}: "
            "raise monitoring while the question stays open",
        )
    ]


def decide(facts: PolicyFacts) -> PolicyDecision:
    """Produce the authorized action list for one fact pattern.

    Resolution order:
      1. collect every action a triggered rule requires;
      2. if no rule called for an operational response, fall back to the
         verdict baseline;
      3. add the case and report actions the policy demands;
      4. drop anything a rule forbids, recording the suppression;
      5. sort into policy order and attach the computed route.

    Step 2 deliberately precedes step 3. Opening a case is record-keeping, not
    a response to the fraud, so the presence of a case requirement must not
    suppress the containment action a verdict calls for.
    """
    evaluation = evaluate_rules(facts)

    required: dict[Action, str] = {}
    required_by: dict[Action, str] = {}
    for outcome in evaluation.triggered:
        for action, reason in outcome.required:
            # First rule to require an action owns the citation.
            if action not in required:
                required[action] = reason
                required_by[action] = outcome.rule_id

    if not required:
        for action, reason in _baseline_actions(facts):
            required[action] = reason
            required_by[action] = "verdict"

    needs_case, case_reason = case_required(facts)
    if needs_case and Action.CREATE_CASE not in required:
        required[Action.CREATE_CASE] = case_reason
        required_by[Action.CREATE_CASE] = "3a"

    needs_report, report_reason = report_required(facts)
    if needs_report and Action.FILE_REPORT not in required:
        required[Action.FILE_REPORT] = report_reason
        required_by[Action.FILE_REPORT] = "3a"

    forbidden: dict[Action, tuple[str, str]] = {}
    for outcome in evaluation.triggered:
        for action, reason in outcome.forbidden:
            forbidden.setdefault(action, (outcome.rule_id, reason))

    suppressed: list[SuppressedAction] = []
    for action, (rule_id, reason) in forbidden.items():
        if action in required:
            suppressed.append(
                SuppressedAction(
                    action=action,
                    required_by=required_by[action],
                    forbidden_by=rule_id,
                    reason=reason,
                )
            )
            del required[action]

    # A report always has a case behind it (policy 3a), even when the report
    # arrived from a rule and the case did not.
    if Action.FILE_REPORT in required and Action.CREATE_CASE not in required:
        required[Action.CREATE_CASE] = "Policy 3a: a report always has a case behind it"
        required_by[Action.CREATE_CASE] = "3a"

    ordered = sorted(required.items(), key=lambda item: _ORDER_INDEX[item[0]])
    actions = [
        ActionRecommendation(
            action=action,
            route=route_for(action, facts.exposure_usd),
            reason=reason,
        )
        for action, reason in ordered
    ]

    barred = [
        BarredAction(action=action, forbidden_by=rule_id, reason=reason)
        for action, (rule_id, reason) in sorted(
            forbidden.items(), key=lambda item: _ORDER_INDEX[item[0]]
        )
    ]

    return PolicyDecision(
        case_id=facts.case_id,
        actions=actions,
        triggered_rules=evaluation.triggered_ids,
        suppressed=suppressed,
        barred=barred,
        requires_case=Action.CREATE_CASE in required,
        requires_report=Action.FILE_REPORT in required,
        report_reason=report_reason if needs_report else report_reason or "",
        evaluation=evaluation,
    )
