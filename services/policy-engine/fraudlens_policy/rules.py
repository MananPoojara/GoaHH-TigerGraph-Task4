"""Rules R1-R10 of Fraud Policy v1.0, one function per rule.

Each rule is a pure predicate over `PolicyFacts` that returns the actions it
requires and the actions it forbids. Rules never read the graph, never call a
model, and never look at another rule's output; composition and conflict
resolution happen once, in `engine.py`.

A rule that forbids an action outranks a rule that requires it. R1, R7, and
R10 exist precisely to stop a block, so allowing a requirement to override them
would defeat the policy.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from fraudlens_contracts import Action, Pattern, Verdict

from .facts import PolicyFacts

# Policy thresholds, named so a magic number never appears in a predicate.
R1_VERIFY_BELOW_PROBABILITY = 0.70
R2_REPORT_EXPOSURE_USD = 1_000.0
R4_ESCALATE_EXPOSURE_USD = 500.0
R5_BLOCK_CLEARED_PURCHASE_USD = 100.0
R8_ESCALATE_EXPOSURE_USD = 500.0
CASE_REQUIRED_PROBABILITY = 0.30
R10_MIN_CARDS_WITH_FRAUD = 2


@dataclass(frozen=True)
class RuleOutcome:
    """What one rule concluded.

    `required` is ordered only for readability; the engine applies the canonical
    action order. `forbidden` maps an action to the reason it is barred.
    """

    rule_id: str
    triggered: bool
    required: tuple[tuple[Action, str], ...] = ()
    forbidden: tuple[tuple[Action, str], ...] = ()
    note: str = ""

    @property
    def required_actions(self) -> tuple[Action, ...]:
        return tuple(action for action, _ in self.required)


def _not_triggered(rule_id: str) -> RuleOutcome:
    return RuleOutcome(rule_id=rule_id, triggered=False)


def rule_r1_verify_before_block(facts: PolicyFacts) -> RuleOutcome:
    """R1. Verify before you block on a weak signal.

    Blocking a legitimate customer on one signal is a policy breach, so this
    rule bars every card block and requires a verification step instead.
    """
    if not (facts.rests_on_single_signal and facts.fraud_probability < R1_VERIFY_BELOW_PROBABILITY):
        return _not_triggered("R1")

    reason = (
        f"R1: case rests on a single signal at probability "
        f"{facts.fraud_probability:.2f}; verify before any block"
    )
    return RuleOutcome(
        rule_id="R1",
        triggered=True,
        required=((Action.VERIFY_WITH_CUSTOMER, reason),),
        forbidden=(
            (Action.BLOCK_CARD, reason),
            (Action.BLOCK_ALL_CARDS, reason),
        ),
    )


def rule_r2_customer_denies(facts: PolicyFacts) -> RuleOutcome:
    """R2. Customer denies the transaction."""
    if not facts.customer.denied:
        return _not_triggered("R2")

    required: list[tuple[Action, str]] = [
        (Action.BLOCK_CARD, "R2: cardholder denied the transaction"),
        (Action.CREATE_CASE, "R2: confirmed unauthorized use requires an internal case"),
    ]

    connected = facts.connected_to_shared_device_profile or facts.connected_to_other_card_fraud
    if facts.exposure_usd > R2_REPORT_EXPOSURE_USD:
        required.append(
            (
                Action.FILE_REPORT,
                f"R2: exposure ${facts.exposure_usd:,.2f} exceeds "
                f"${R2_REPORT_EXPOSURE_USD:,.0f}",
            )
        )
    elif connected:
        required.append(
            (
                Action.FILE_REPORT,
                "R2: activity connects to a shared device profile or another card's fraud",
            )
        )

    return RuleOutcome(rule_id="R2", triggered=True, required=tuple(required))


def rule_r3_customer_confirms(facts: PolicyFacts) -> RuleOutcome:
    """R3. Customer confirms the transaction."""
    if not facts.customer.confirmed:
        return _not_triggered("R3")
    return RuleOutcome(
        rule_id="R3",
        triggered=True,
        required=((Action.CLOSE_NO_FRAUD, "R3: cardholder confirmed they made the transaction"),),
        forbidden=(
            (Action.BLOCK_CARD, "R3: cardholder confirmed the transaction"),
            (Action.BLOCK_ALL_CARDS, "R3: cardholder confirmed the transaction"),
        ),
        note="Confirmation recorded in the case file.",
    )


def rule_r4_no_reply(facts: PolicyFacts) -> RuleOutcome:
    """R4. No reply within 24 hours."""
    if not facts.customer.no_reply_24h:
        return _not_triggered("R4")

    required: list[tuple[Action, str]] = [
        (Action.MONITOR_CARD, "R4: no cardholder reply within 24 hours")
    ]
    if facts.has_pending_authorization:
        required.insert(
            0,
            (
                Action.DECLINE_TRANSACTION,
                "R4: decline pending authorizations while the cardholder is unreachable",
            ),
        )
    if facts.exposure_usd > R4_ESCALATE_EXPOSURE_USD:
        required.append(
            (
                Action.ESCALATE_TO_ANALYST,
                f"R4: exposure ${facts.exposure_usd:,.2f} exceeds "
                f"${R4_ESCALATE_EXPOSURE_USD:,.0f} with no reply",
            )
        )
    return RuleOutcome(rule_id="R4", triggered=True, required=tuple(required))


def rule_r5_card_testing(facts: PolicyFacts) -> RuleOutcome:
    """R5. Card testing.

    The trigger is the observed sequence, not the assigned pattern label, so a
    mislabelled case cannot borrow R5's authority.
    """
    if not facts.card_testing.sequence_observed:
        return _not_triggered("R5")

    required: list[tuple[Action, str]] = [
        (
            Action.DECLINE_TRANSACTION,
            f"R5: {facts.card_testing.small_auth_count} small online authorizations "
            "within an hour followed by a larger purchase",
        ),
        (Action.STEP_UP_AUTH, "R5: require step-up authentication after a testing sequence"),
    ]
    cleared = facts.card_testing.cleared_purchase_amount_usd
    if cleared > R5_BLOCK_CLEARED_PURCHASE_USD:
        required.append(
            (
                Action.BLOCK_CARD,
                f"R5: a purchase of ${cleared:,.2f} over "
                f"${R5_BLOCK_CLEARED_PURCHASE_USD:,.0f} has already cleared",
            )
        )
    return RuleOutcome(rule_id="R5", triggered=True, required=tuple(required))


def rule_r6_shared_origin(facts: PolicyFacts) -> RuleOutcome:
    """R6. Shared origin across several cards in one window.

    The policy says "when several cards show *fraud* from the same device
    profile". Sharing an origin is not itself fraud: a household sharing a
    tablet, or a popular device model, will share one profile innocently.
    So R6 requires that this case actually shows fraud before it names a ring
    and files a report. Without that precondition a cardholder who confirms
    their own purchase could still trigger a regulatory filing.
    """
    if not facts.shared_origin.ring_observed:
        return _not_triggered("R6")
    if not facts.strongly_suspected_or_confirmed:
        return _not_triggered("R6")

    element = facts.shared_origin.shared_element
    kind = facts.shared_origin.shared_element_kind or "origin"
    named = f"R6: {facts.shared_origin.cards_sharing_origin} cards share {kind} {element}"
    return RuleOutcome(
        rule_id="R6",
        triggered=True,
        required=(
            (Action.CREATE_CASE, named),
            (Action.FILE_REPORT, named),
            (Action.MONITOR_CONNECTED_CARDS, f"{named}; monitor every card sharing it"),
        ),
        note=f"Shared element: {element}",
    )


def rule_r7_disputed_but_legitimate(facts: PolicyFacts) -> RuleOutcome:
    """R7. Disputed but legitimate recurring charge. Explicitly must not block.

    The rule presupposes the charge is legitimate -- its own heading is
    "Disputed but legitimate" -- so it applies when the recurring match is the
    best available explanation. When fraud is independently established (a new
    device shared with other cards already carrying confirmed fraud, say), the
    premise fails: the charge merely resembles a subscription. Without this
    guard R7 would bar a block on exactly the cases that most need one.
    """
    if not (facts.customer_disputed and facts.matches_recurring_legitimate_pattern):
        return _not_triggered("R7")
    if facts.strongly_suspected_or_confirmed:
        return _not_triggered("R7")

    reason = "R7: disputed charge matches the cardholder's own recurring pattern"
    return RuleOutcome(
        rule_id="R7",
        triggered=True,
        required=(
            (Action.VERIFY_WITH_CUSTOMER, reason),
            (Action.CREATE_CASE, reason),
            (Action.WARN_CUSTOMER, f"{reason}; remind the cardholder of the recurring charge"),
        ),
        forbidden=(
            (Action.BLOCK_CARD, "R7: do not block a charge matching a recurring pattern"),
            (Action.BLOCK_ALL_CARDS, "R7: do not block a charge matching a recurring pattern"),
        ),
    )


def rule_r8_escalate_when_uncertain(facts: PolicyFacts) -> RuleOutcome:
    """R8. Escalate when uncertain and exposed, or when evidence conflicts."""
    exposed = facts.verdict is Verdict.UNCERTAIN and facts.exposure_usd > R8_ESCALATE_EXPOSURE_USD
    if not (exposed or facts.conflicting_evidence):
        return _not_triggered("R8")

    if exposed:
        reason = (
            f"R8: verdict uncertain with exposure ${facts.exposure_usd:,.2f} over "
            f"${R8_ESCALATE_EXPOSURE_USD:,.0f}"
        )
    else:
        reason = "R8: the evidence conflicts"
    return RuleOutcome(
        rule_id="R8",
        triggered=True,
        required=((Action.ESCALATE_TO_ANALYST, reason),),
    )


def rule_r9_undocumented_pattern(facts: PolicyFacts) -> RuleOutcome:
    """R9. Coordinated or repeated abuse fitting none of the known patterns."""
    if not (facts.pattern is Pattern.UNDOCUMENTED and facts.coordinated_or_undocumented_abuse):
        return _not_triggered("R9")

    reason = "R9: coordinated or repeated abuse matching none of the documented patterns"
    return RuleOutcome(
        rule_id="R9",
        triggered=True,
        required=(
            (Action.CREATE_CASE, reason),
            (Action.FILE_REPORT, reason),
            (Action.ESCALATE_TO_ANALYST, reason),
        ),
        note="Pattern must be described in the agent's own words.",
    )


def rule_r10_block_all_cards_guard(facts: PolicyFacts) -> RuleOutcome:
    """R10. Never BLOCK_ALL_CARDS without the required evidence.

    This rule is a standing guard: it is 'triggered' only when it actually bars
    the action, so a case that legitimately meets the bar records no R10
    citation.
    """
    permitted = (
        facts.customer_cards_with_confirmed_fraud >= R10_MIN_CARDS_WITH_FRAUD
        or facts.credentials_confirmed_compromised
    )
    if permitted:
        return _not_triggered("R10")

    return RuleOutcome(
        rule_id="R10",
        triggered=True,
        forbidden=(
            (
                Action.BLOCK_ALL_CARDS,
                "R10: fewer than two cards show confirmed fraud and credentials are "
                "not confirmed compromised",
            ),
        ),
    )


# Evaluation order is fixed so traces are comparable across runs.
ALL_RULES: tuple[Callable[[PolicyFacts], RuleOutcome], ...] = (
    rule_r1_verify_before_block,
    rule_r2_customer_denies,
    rule_r3_customer_confirms,
    rule_r4_no_reply,
    rule_r5_card_testing,
    rule_r6_shared_origin,
    rule_r7_disputed_but_legitimate,
    rule_r8_escalate_when_uncertain,
    rule_r9_undocumented_pattern,
    rule_r10_block_all_cards_guard,
)


@dataclass
class RuleEvaluation:
    """Every rule outcome for one fact pattern."""

    outcomes: list[RuleOutcome] = field(default_factory=list)

    @property
    def triggered(self) -> list[RuleOutcome]:
        return [outcome for outcome in self.outcomes if outcome.triggered]

    @property
    def triggered_ids(self) -> list[str]:
        return [outcome.rule_id for outcome in self.triggered]


def evaluate_rules(facts: PolicyFacts) -> RuleEvaluation:
    """Run every rule against `facts` in fixed order."""
    return RuleEvaluation(outcomes=[rule(facts) for rule in ALL_RULES])
