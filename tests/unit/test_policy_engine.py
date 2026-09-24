"""Policy engine tests.

Boundary values are taken verbatim from Fraud Policy v1.0: $100, $500, $1,000,
and $2,500, plus the 0.30 case threshold and the 0.70 R1 threshold. Each is
tested on both sides because an off-by-one here is a policy breach, not a bug.
"""

from __future__ import annotations

import pytest
from fraudlens_contracts import Action, Pattern, Route, Verdict
from fraudlens_policy import (
    CardTestingFacts,
    CustomerResponse,
    PolicyFacts,
    SharedOriginFacts,
    case_required,
    decide,
    is_auto_executable,
    report_required,
    route_for,
)


def facts(**overrides: object) -> PolicyFacts:
    """A deliberately inert baseline: uncertain, unexposed, nothing observed."""
    base: dict[str, object] = {
        "case_id": "HHG-TEST",
        "verdict": Verdict.UNCERTAIN,
        "fraud_probability": 0.20,
        "pattern": Pattern.NONE,
        "exposure_usd": 0.0,
        "independent_signal_count": 2,
    }
    base.update(overrides)
    return PolicyFacts(**base)  # type: ignore[arg-type]


def actions_of(decision) -> list[Action]:
    return [item.action for item in decision.actions]


def route_of(decision, action: Action) -> Route:
    return next(item.route for item in decision.actions if item.action is action)


# --------------------------------------------------------------------------
# Routing matrix (policy section 2)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action",
    [
        Action.ALLOW_TRANSACTION,
        Action.MONITOR_CARD,
        Action.MONITOR_CONNECTED_CARDS,
        Action.WARN_CUSTOMER,
        Action.VERIFY_WITH_CUSTOMER,
        Action.STEP_UP_AUTH,
        Action.GENERATE_REPORT,
        Action.CREATE_CASE,
        Action.ESCALATE_TO_ANALYST,
        Action.CLOSE_NO_FRAUD,
    ],
)
def test_auto_actions_route_auto_at_any_exposure(action: Action) -> None:
    assert route_for(action, 0.0) is Route.AUTO
    assert route_for(action, 1_000_000.0) is Route.AUTO
    assert is_auto_executable(action)


def test_decline_transaction_is_always_l1() -> None:
    assert route_for(Action.DECLINE_TRANSACTION, 0.0) is Route.L1
    assert route_for(Action.DECLINE_TRANSACTION, 50_000.0) is Route.L1
    assert not is_auto_executable(Action.DECLINE_TRANSACTION)


@pytest.mark.parametrize(
    ("exposure", "expected"),
    [
        (0.0, Route.L1),
        (2_499.99, Route.L1),
        (2_500.0, Route.L1),  # "when exposure <= $2,500"
        (2_500.01, Route.L2),  # "when exposure > $2,500"
        (10_000.0, Route.L2),
    ],
)
def test_block_card_route_turns_at_2500(exposure: float, expected: Route) -> None:
    assert route_for(Action.BLOCK_CARD, exposure) is expected


def test_block_all_cards_and_file_report_are_always_l2() -> None:
    for exposure in (0.0, 100_000.0):
        assert route_for(Action.BLOCK_ALL_CARDS, exposure) is Route.L2
        assert route_for(Action.FILE_REPORT, exposure) is Route.L2


# --------------------------------------------------------------------------
# R1 - verify before blocking on a weak signal
# --------------------------------------------------------------------------


def test_r1_blocks_are_suppressed_on_a_single_weak_signal() -> None:
    decision = decide(
        facts(
            verdict=Verdict.FRAUD,
            fraud_probability=0.55,
            independent_signal_count=1,
            exposure_usd=300.0,
        )
    )
    assert "R1" in decision.triggered_rules
    assert Action.BLOCK_CARD not in actions_of(decision)
    assert Action.VERIFY_WITH_CUSTOMER in actions_of(decision)
    assert decision.is_barred(Action.BLOCK_CARD), "R1 must record that a block was barred"


def test_r1_does_not_fire_at_or_above_070() -> None:
    decision = decide(
        facts(verdict=Verdict.FRAUD, fraud_probability=0.70, independent_signal_count=1)
    )
    assert "R1" not in decision.triggered_rules
    assert Action.BLOCK_CARD in actions_of(decision)


def test_r1_does_not_fire_when_several_independent_signals_exist() -> None:
    decision = decide(
        facts(verdict=Verdict.FRAUD, fraud_probability=0.55, independent_signal_count=3)
    )
    assert "R1" not in decision.triggered_rules


# --------------------------------------------------------------------------
# R2 / R3 / R4 - customer response
# --------------------------------------------------------------------------


def test_r2_denial_blocks_and_opens_a_case() -> None:
    decision = decide(
        facts(
            verdict=Verdict.FRAUD,
            fraud_probability=0.80,
            exposure_usd=400.0,
            customer=CustomerResponse(asked=True, denied=True),
        )
    )
    assert "R2" in decision.triggered_rules
    assert Action.BLOCK_CARD in actions_of(decision)
    assert Action.CREATE_CASE in actions_of(decision)
    # $400 exposure, no connection: a case without a report.
    assert Action.FILE_REPORT not in actions_of(decision)


@pytest.mark.parametrize(
    ("exposure", "expect_report"),
    [(1_000.0, False), (1_000.01, True)],
)
def test_r2_report_threshold_is_strictly_above_1000(exposure: float, expect_report: bool) -> None:
    decision = decide(
        facts(
            verdict=Verdict.FRAUD,
            fraud_probability=0.80,
            exposure_usd=exposure,
            customer=CustomerResponse(asked=True, denied=True),
        )
    )
    assert (Action.FILE_REPORT in actions_of(decision)) is expect_report


def test_r2_files_a_report_on_a_shared_device_even_when_exposure_is_small() -> None:
    decision = decide(
        facts(
            verdict=Verdict.FRAUD,
            fraud_probability=0.80,
            exposure_usd=50.0,
            customer=CustomerResponse(asked=True, denied=True),
            connected_to_shared_device_profile=True,
        )
    )
    assert Action.FILE_REPORT in actions_of(decision)
    assert Action.CREATE_CASE in actions_of(decision), "a report always has a case behind it"


def test_r3_confirmation_closes_and_bars_a_block() -> None:
    decision = decide(
        facts(
            verdict=Verdict.LEGITIMATE,
            fraud_probability=0.05,
            customer=CustomerResponse(asked=True, confirmed=True),
        )
    )
    assert "R3" in decision.triggered_rules
    assert Action.CLOSE_NO_FRAUD in actions_of(decision)
    assert Action.BLOCK_CARD not in actions_of(decision)


def test_r4_no_reply_monitors_and_declines_pending() -> None:
    decision = decide(
        facts(
            fraud_probability=0.40,
            exposure_usd=200.0,
            has_pending_authorization=True,
            customer=CustomerResponse(asked=True, no_reply_24h=True),
        )
    )
    assert "R4" in decision.triggered_rules
    assert Action.MONITOR_CARD in actions_of(decision)
    assert Action.DECLINE_TRANSACTION in actions_of(decision)
    assert Action.ESCALATE_TO_ANALYST not in actions_of(decision)


@pytest.mark.parametrize(
    ("exposure", "expect_escalation"),
    [(500.0, False), (500.01, True)],
)
def test_r4_escalation_threshold_is_strictly_above_500(
    exposure: float, expect_escalation: bool
) -> None:
    decision = decide(
        facts(
            fraud_probability=0.40,
            exposure_usd=exposure,
            customer=CustomerResponse(asked=True, no_reply_24h=True),
        )
    )
    assert (Action.ESCALATE_TO_ANALYST in actions_of(decision)) is expect_escalation


def test_customer_response_rejects_contradictory_answers() -> None:
    with pytest.raises(ValueError, match="at most one"):
        CustomerResponse(asked=True, denied=True, confirmed=True)


def test_customer_response_requires_having_asked() -> None:
    with pytest.raises(ValueError, match="requires that the customer was asked"):
        CustomerResponse(asked=False, denied=True)


# --------------------------------------------------------------------------
# R5 - card testing
# --------------------------------------------------------------------------


def test_r5_needs_the_full_observed_sequence() -> None:
    partial = decide(
        facts(
            pattern=Pattern.CARD_TESTING,
            card_testing=CardTestingFacts(
                small_auth_count=2, within_one_hour=True, followed_by_larger_purchase=True
            ),
        )
    )
    assert "R5" not in partial.triggered_rules, "two authorizations is below the R5 threshold"


def test_r5_declines_and_steps_up() -> None:
    decision = decide(
        facts(
            verdict=Verdict.FRAUD,
            fraud_probability=0.75,
            pattern=Pattern.CARD_TESTING,
            exposure_usd=60.0,
            card_testing=CardTestingFacts(
                small_auth_count=3,
                within_one_hour=True,
                followed_by_larger_purchase=True,
                cleared_purchase_amount_usd=60.0,
            ),
        )
    )
    assert "R5" in decision.triggered_rules
    assert Action.DECLINE_TRANSACTION in actions_of(decision)
    assert Action.STEP_UP_AUTH in actions_of(decision)


@pytest.mark.parametrize(
    ("cleared", "expect_block"),
    [(100.0, False), (100.01, True)],
)
def test_r5_block_threshold_is_strictly_above_100(cleared: float, expect_block: bool) -> None:
    decision = decide(
        facts(
            verdict=Verdict.FRAUD,
            fraud_probability=0.75,
            pattern=Pattern.CARD_TESTING,
            exposure_usd=cleared,
            card_testing=CardTestingFacts(
                small_auth_count=4,
                within_one_hour=True,
                followed_by_larger_purchase=True,
                cleared_purchase_amount_usd=cleared,
            ),
        )
    )
    assert (Action.BLOCK_CARD in actions_of(decision)) is expect_block


# --------------------------------------------------------------------------
# R6 - shared origin
# --------------------------------------------------------------------------


def test_r6_names_the_shared_element_and_monitors_connected_cards() -> None:
    decision = decide(
        facts(
            verdict=Verdict.FRAUD,
            fraud_probability=0.82,
            exposure_usd=900.0,
            shared_origin=SharedOriginFacts(
                cards_sharing_origin=3,
                shared_element="SAMSUNG SM-G935F | Android 7.0 | chrome 62 | 1920x1080",
                shared_element_kind="device profile",
                within_one_window=True,
                connected_card_ids=["C00877-K1", "C01234-K2"],
            ),
        )
    )
    assert "R6" in decision.triggered_rules
    assert Action.CREATE_CASE in actions_of(decision)
    assert Action.FILE_REPORT in actions_of(decision)
    assert Action.MONITOR_CONNECTED_CARDS in actions_of(decision)
    reason = next(
        item.reason for item in decision.actions if item.action is Action.MONITOR_CONNECTED_CARDS
    )
    assert "SAMSUNG SM-G935F" in reason, "R6 requires naming the shared element"


# --------------------------------------------------------------------------
# R7 - disputed but legitimate
# --------------------------------------------------------------------------


def test_r7_verifies_and_warns_but_never_blocks() -> None:
    decision = decide(
        facts(
            verdict=Verdict.LEGITIMATE,
            fraud_probability=0.12,
            customer_disputed=True,
            matches_recurring_legitimate_pattern=True,
        )
    )
    assert "R7" in decision.triggered_rules
    assert Action.CREATE_CASE in actions_of(decision)
    assert Action.VERIFY_WITH_CUSTOMER in actions_of(decision)
    assert Action.WARN_CUSTOMER in actions_of(decision)
    assert Action.BLOCK_CARD not in actions_of(decision)


# --------------------------------------------------------------------------
# R8 - escalate when uncertain and exposed
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("exposure", "expect_escalation"),
    [(500.0, False), (500.01, True)],
)
def test_r8_escalation_threshold_is_strictly_above_500(
    exposure: float, expect_escalation: bool
) -> None:
    decision = decide(
        facts(verdict=Verdict.UNCERTAIN, fraud_probability=0.50, exposure_usd=exposure)
    )
    assert (Action.ESCALATE_TO_ANALYST in actions_of(decision)) is expect_escalation


def test_r8_escalates_on_conflicting_evidence_at_any_exposure() -> None:
    decision = decide(
        facts(verdict=Verdict.UNCERTAIN, fraud_probability=0.50, conflicting_evidence=True)
    )
    assert "R8" in decision.triggered_rules
    assert Action.ESCALATE_TO_ANALYST in actions_of(decision)


# --------------------------------------------------------------------------
# R9 - undocumented pattern
# --------------------------------------------------------------------------


def test_r9_creates_case_files_report_and_escalates() -> None:
    decision = decide(
        facts(
            verdict=Verdict.FRAUD,
            fraud_probability=0.78,
            pattern=Pattern.UNDOCUMENTED,
            exposure_usd=300.0,
            coordinated_or_undocumented_abuse=True,
        )
    )
    assert "R9" in decision.triggered_rules
    assert Action.CREATE_CASE in actions_of(decision)
    assert Action.FILE_REPORT in actions_of(decision)
    assert Action.ESCALATE_TO_ANALYST in actions_of(decision)


# --------------------------------------------------------------------------
# R10 - block-all-cards guard
# --------------------------------------------------------------------------


def test_r10_bars_block_all_cards_without_evidence() -> None:
    decision = decide(facts(verdict=Verdict.FRAUD, fraud_probability=0.95))
    assert "R10" in decision.triggered_rules
    assert Action.BLOCK_ALL_CARDS not in actions_of(decision)


def test_r10_permits_block_all_cards_with_two_compromised_cards() -> None:
    decision = decide(
        facts(
            verdict=Verdict.FRAUD,
            fraud_probability=0.95,
            customer_cards_with_confirmed_fraud=2,
        )
    )
    assert "R10" not in decision.triggered_rules


def test_r10_permits_block_all_cards_on_confirmed_credential_compromise() -> None:
    decision = decide(
        facts(
            verdict=Verdict.FRAUD,
            fraud_probability=0.95,
            credentials_confirmed_compromised=True,
        )
    )
    assert "R10" not in decision.triggered_rules


# --------------------------------------------------------------------------
# Case and report predicates (policy 3a)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("probability", "expected"),
    [(0.29, False), (0.30, True), (0.31, True)],
)
def test_case_opens_at_probability_030(probability: float, expected: bool) -> None:
    assert case_required(facts(fraud_probability=probability))[0] is expected


def test_case_opens_when_evidence_was_requested() -> None:
    assert case_required(facts(fraud_probability=0.10, evidence_requested=True))[0] is True


def test_case_opens_when_the_customer_disputed() -> None:
    assert case_required(facts(fraud_probability=0.10, customer_disputed=True))[0] is True


def test_no_report_without_confirmed_or_strong_suspicion() -> None:
    required, reason = report_required(
        facts(verdict=Verdict.UNCERTAIN, fraud_probability=0.60, exposure_usd=5_000.0)
    )
    assert required is False
    assert "not confirmed or strongly suspected" in reason


def test_no_report_for_confirmed_fraud_without_a_predicate() -> None:
    required, _ = report_required(
        facts(verdict=Verdict.FRAUD, fraud_probability=0.90, exposure_usd=250.0)
    )
    assert required is False, "most cases never need a report"


def test_legitimate_verdict_allows_and_closes() -> None:
    decision = decide(facts(verdict=Verdict.LEGITIMATE, fraud_probability=0.05))
    assert Action.ALLOW_TRANSACTION in actions_of(decision)
    assert Action.CLOSE_NO_FRAUD in actions_of(decision)
    assert decision.requires_report is False


# --------------------------------------------------------------------------
# Ordering and determinism
# --------------------------------------------------------------------------


def test_actions_follow_policy_order_first_thing_first() -> None:
    decision = decide(
        facts(
            verdict=Verdict.FRAUD,
            fraud_probability=0.88,
            exposure_usd=1_500.0,
            customer=CustomerResponse(asked=True, denied=True),
            connected_to_shared_device_profile=True,
            shared_origin=SharedOriginFacts(
                cards_sharing_origin=2,
                shared_element="D-001",
                shared_element_kind="device profile",
                within_one_window=True,
            ),
        )
    )
    order = actions_of(decision)
    assert order.index(Action.BLOCK_CARD) < order.index(Action.CREATE_CASE)
    assert order.index(Action.CREATE_CASE) < order.index(Action.FILE_REPORT)
    assert order.index(Action.FILE_REPORT) < order.index(Action.MONITOR_CONNECTED_CARDS)


def test_decide_is_deterministic() -> None:
    sample = facts(
        verdict=Verdict.FRAUD,
        fraud_probability=0.77,
        exposure_usd=3_000.0,
        customer=CustomerResponse(asked=True, denied=True),
    )
    first = decide(sample)
    second = decide(sample)
    assert actions_of(first) == actions_of(second)
    assert first.triggered_rules == second.triggered_rules
    assert route_of(first, Action.BLOCK_CARD) is Route.L2, "exposure over $2,500 is L2"
