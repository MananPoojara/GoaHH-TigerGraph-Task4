"""Golden behaviour tests.

These assert decisions and invariants, never exact wording, so a prompt or
phrasing change cannot break them but a policy or scoping regression will.

The scenarios are the ones the evaluation plan calls out: a clear testing
sequence, an ambiguous single signal, a disputed recurring charge, a shared
device ring, uncertainty above the exposure threshold, a forbidden
block-all-cards, and a temporal-leak attempt.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from fraudlens_contracts import (
    Action,
    CaseAnswer,
    CaseStatus,
    Pattern,
    Route,
    TriggerType,
    Verdict,
)
from fraudlens_graph import FixtureGraphClient
from fraudlens_investigator import Trigger, build_answer, run_investigation
from fraudlens_loading import preprocess, write_fixture_dataset
from fraudlens_policy import (
    CustomerResponse,
    PolicyFacts,
    SharedOriginFacts,
    decide,
)


@pytest.fixture(scope="module")
def graph(tmp_path_factory: pytest.TempPathFactory) -> FixtureGraphClient:
    root = tmp_path_factory.mktemp("golden")
    raw, out = root / "raw", root / "processed"
    write_fixture_dataset(raw)
    preprocess(raw, out)
    return FixtureGraphClient(out)


def investigate(
    graph: FixtureGraphClient,
    *,
    case_id: str,
    customer_id: str,
    card_id: str,
    txn_id: str,
    opened_at: datetime,
    trigger_type: TriggerType = TriggerType.RISK_SCORE,
    risk_score: float | None = 0.60,
    trigger_text: str = "Fixture trigger",
) -> CaseAnswer:
    trigger = Trigger(
        case_id=case_id,
        trigger_type=trigger_type,
        trigger_text=trigger_text,
        flagged_txn_id=txn_id,
        card_id=card_id,
        customer_id=customer_id,
        opened_at=opened_at,
        risk_score=risk_score,
    )
    return build_answer(run_investigation(trigger, graph).state)


def _testing_anchor(graph: FixtureGraphClient) -> tuple[str, datetime]:
    """The larger purchase that closes the planted card-testing sequence."""
    rows = [
        row
        for row in graph.by_card["FIXC02-K1"]
        if row.channel == "online" and abs(row.amount) > 100
    ]
    assert rows, "the fixture must plant a larger purchase"
    return rows[0].txn_id, rows[0].ts


# --------------------------------------------------------------------------
# 1. A clear card-testing sequence is found and acted on
# --------------------------------------------------------------------------


def test_card_testing_is_detected_and_contained(graph: FixtureGraphClient) -> None:
    txn_id, ts = _testing_anchor(graph)
    answer = investigate(
        graph,
        case_id="GOLD-001",
        customer_id="FIXC02",
        card_id="FIXC02-K1",
        txn_id=txn_id,
        opened_at=ts,
    )

    assert answer.case.verdict is Verdict.FRAUD
    assert answer.case.pattern is Pattern.CARD_TESTING
    assert answer.case.status is CaseStatus.CLOSED_FRAUD

    actions = [item.action for item in answer.next_best_actions.final]
    assert Action.CREATE_CASE in actions
    # R5 requires declining and stepping up on an observed testing sequence.
    assert Action.DECLINE_TRANSACTION in actions
    assert Action.STEP_UP_AUTH in actions


def test_card_testing_episode_scope_and_exposure_reconcile(
    graph: FixtureGraphClient,
) -> None:
    txn_id, ts = _testing_anchor(graph)
    answer = investigate(
        graph,
        case_id="GOLD-002",
        customer_id="FIXC02",
        card_id="FIXC02-K1",
        txn_id=txn_id,
        opened_at=ts,
    )

    # Three small authorizations plus the larger purchase.
    assert len(answer.case.affected_txn_ids) == 4
    assert answer.case.first_suspicious_txn_id in answer.case.affected_txn_ids

    expected = round(
        sum(abs(graph.transactions[t].amount) for t in answer.case.affected_txn_ids), 2
    )
    assert answer.case.exposure_usd == pytest.approx(expected, abs=0.01)


# --------------------------------------------------------------------------
# 2. A legitimate control case is not blocked
# --------------------------------------------------------------------------


def test_the_legitimate_control_customer_is_not_blocked(
    graph: FixtureGraphClient,
) -> None:
    """An agent that blocks everything scores badly; this must stay clean."""
    row = graph.by_card["FIXC01-K1"][-1]
    answer = investigate(
        graph,
        case_id="GOLD-003",
        customer_id="FIXC01",
        card_id="FIXC01-K1",
        txn_id=row.txn_id,
        opened_at=row.ts,
        risk_score=0.55,
    )

    actions = [item.action for item in answer.next_best_actions.final]
    assert Action.BLOCK_CARD not in actions
    assert Action.BLOCK_ALL_CARDS not in actions
    assert answer.sar.file is False
    assert answer.case.verdict is not Verdict.FRAUD


# --------------------------------------------------------------------------
# 3. Answer-contract invariants hold for every produced answer
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("customer_id", "card_id"),
    [("FIXC01", "FIXC01-K1"), ("FIXC02", "FIXC02-K1"), ("FIXC05", "FIXC05-K1")],
)
def test_produced_answers_satisfy_the_contract(
    graph: FixtureGraphClient, customer_id: str, card_id: str
) -> None:
    row = graph.by_card[card_id][-1]
    answer = investigate(
        graph,
        case_id=f"GOLD-{card_id}",
        customer_id=customer_id,
        card_id=card_id,
        txn_id=row.txn_id,
        opened_at=row.ts,
    )

    # Constructing CaseAnswer already enforced the structural rules; assert
    # the ones a reviewer would check by hand.
    if answer.case.verdict is Verdict.LEGITIMATE:
        assert answer.case.affected_txn_ids == []
        assert answer.case.exposure_usd == 0
        assert answer.sar.file is False

    files_report = Action.FILE_REPORT in [i.action for i in answer.next_best_actions.final]
    assert answer.sar.file is files_report

    if not answer.evidence_requests:
        assert answer.next_best_actions.final == answer.next_best_actions.initial
        assert answer.next_best_actions.what_changed == "nothing"

    for item in answer.next_best_actions.final:
        from fraudlens_policy import route_for

        assert item.route is route_for(item.action, answer.case.exposure_usd)


def test_every_evidence_item_carries_a_reference(graph: FixtureGraphClient) -> None:
    """A claim without a replayable ref is inference, not evidence."""
    txn_id, ts = _testing_anchor(graph)
    answer = investigate(
        graph,
        case_id="GOLD-004",
        customer_id="FIXC02",
        card_id="FIXC02-K1",
        txn_id=txn_id,
        opened_at=ts,
    )
    assert answer.case.evidence
    for item in answer.case.evidence:
        assert item.ref.strip()
        assert item.claim.strip()


def test_every_referenced_transaction_exists(graph: FixtureGraphClient) -> None:
    """Made-up IDs score zero, so nothing may be invented."""
    txn_id, ts = _testing_anchor(graph)
    answer = investigate(
        graph,
        case_id="GOLD-005",
        customer_id="FIXC02",
        card_id="FIXC02-K1",
        txn_id=txn_id,
        opened_at=ts,
    )
    for value in answer.case.affected_txn_ids:
        assert value in graph.transactions
    for value in answer.case.connected_card_ids:
        assert value in graph.cards


# --------------------------------------------------------------------------
# 4. Counter-evidence is always sought
# --------------------------------------------------------------------------


def test_counter_evidence_is_gathered_before_concluding(
    graph: FixtureGraphClient,
) -> None:
    row = graph.by_card["FIXC01-K1"][-1]
    trigger = Trigger(
        case_id="GOLD-006",
        trigger_type=TriggerType.RISK_SCORE,
        trigger_text="control",
        flagged_txn_id=row.txn_id,
        card_id="FIXC01-K1",
        customer_id="FIXC01",
        opened_at=row.ts,
        risk_score=0.80,
    )
    state = run_investigation(trigger, graph).state

    nodes_run = {event.node for event in state.timeline}
    assert "seek_counter_evidence" in nodes_run
    assert state.counter_evidence(), "an innocent explanation must be tested"


# --------------------------------------------------------------------------
# 5. Case memory and graph persistence
# --------------------------------------------------------------------------


def test_the_case_is_written_back_and_verified(graph: FixtureGraphClient) -> None:
    txn_id, ts = _testing_anchor(graph)
    trigger = Trigger(
        case_id="GOLD-007",
        trigger_type=TriggerType.RISK_SCORE,
        trigger_text="testing",
        flagged_txn_id=txn_id,
        card_id="FIXC02-K1",
        customer_id="FIXC02",
        opened_at=ts,
        risk_score=0.61,
    )
    result = run_investigation(trigger, graph)

    assert result.write_verified, result.state.errors
    assert result.state.written_to_graph is True
    assert result.state.graph_case_id

    # The written case must be retrievable, which is what makes it memory.
    stored = graph.run("get_case_history", {"case_id": result.state.graph_case_id})
    assert stored[0]["case_details"], "the case must be readable back out of the graph"


def test_written_to_graph_is_false_when_persistence_fails(
    graph: FixtureGraphClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The answer must never claim a write that did not happen."""
    from fraudlens_graph import GraphError

    txn_id, ts = _testing_anchor(graph)
    original = graph.run

    def failing(query: str, params: dict) -> list[dict]:
        if query == "upsert_case":
            raise GraphError(query, "simulated write failure")
        return original(query, params)

    monkeypatch.setattr(graph, "run", failing)

    trigger = Trigger(
        case_id="GOLD-008",
        trigger_type=TriggerType.RISK_SCORE,
        trigger_text="testing",
        flagged_txn_id=txn_id,
        card_id="FIXC02-K1",
        customer_id="FIXC02",
        opened_at=ts,
        risk_score=0.61,
    )
    state = run_investigation(trigger, graph).state
    assert state.written_to_graph is False
    assert state.graph_case_id == ""
    assert state.errors


# --------------------------------------------------------------------------
# 6. Policy invariants that no investigation may violate
# --------------------------------------------------------------------------


def test_a_shared_ring_on_a_confirmed_legitimate_case_files_no_report() -> None:
    """R6 names a ring only when this case actually shows fraud.

    A cardholder who confirms their own purchase must not trigger a
    regulatory filing just because their device is shared.
    """
    facts = PolicyFacts(
        case_id="GOLD-R6",
        verdict=Verdict.LEGITIMATE,
        fraud_probability=0.08,
        pattern=Pattern.NONE,
        exposure_usd=0.0,
        customer=CustomerResponse(asked=True, confirmed=True),
        shared_origin=SharedOriginFacts(
            cards_sharing_origin=3,
            shared_element="D-123",
            shared_element_kind="device profile",
            within_one_window=True,
        ),
    )
    decision = decide(facts)
    assert "R6" not in decision.triggered_rules
    assert Action.FILE_REPORT not in [item.action for item in decision.actions]


def test_a_shared_ring_on_a_fraud_case_does_file_a_report() -> None:
    facts = PolicyFacts(
        case_id="GOLD-R6b",
        verdict=Verdict.FRAUD,
        fraud_probability=0.88,
        pattern=Pattern.CARD_NOT_PRESENT_NEW_DEVICE,
        exposure_usd=900.0,
        independent_signal_count=3,
        shared_origin=SharedOriginFacts(
            cards_sharing_origin=3,
            shared_element="D-123",
            shared_element_kind="device profile",
            within_one_window=True,
        ),
    )
    decision = decide(facts)
    assert "R6" in decision.triggered_rules
    actions = [item.action for item in decision.actions]
    assert Action.FILE_REPORT in actions
    assert Action.MONITOR_CONNECTED_CARDS in actions
    assert Action.CREATE_CASE in actions


def test_no_investigation_executes_a_non_auto_action(
    graph: FixtureGraphClient,
) -> None:
    """Only `auto` actions may be carried out by the agent."""
    from fraudlens_policy import is_auto_executable

    txn_id, ts = _testing_anchor(graph)
    trigger = Trigger(
        case_id="GOLD-009",
        trigger_type=TriggerType.RISK_SCORE,
        trigger_text="testing",
        flagged_txn_id=txn_id,
        card_id="FIXC02-K1",
        customer_id="FIXC02",
        opened_at=ts,
        risk_score=0.61,
    )
    state = run_investigation(trigger, graph).state

    for action in state.executed_actions:
        assert is_auto_executable(action), f"{action} was executed without approval"

    # Anything not auto must still be present as a recommendation.
    pending = [i for i in state.final_actions if i.route is not Route.AUTO]
    for item in pending:
        assert item.action not in state.executed_actions


# --------------------------------------------------------------------------
# 7. Temporal integrity
# --------------------------------------------------------------------------


def test_an_investigation_cannot_see_past_its_cutoff(
    graph: FixtureGraphClient,
) -> None:
    """A case opened before the testing sequence must not find it."""
    txn_id, ts = _testing_anchor(graph)
    early_row = graph.by_card["FIXC02-K1"][0]

    answer = investigate(
        graph,
        case_id="GOLD-010",
        customer_id="FIXC02",
        card_id="FIXC02-K1",
        txn_id=early_row.txn_id,
        opened_at=early_row.ts,
    )
    assert txn_id not in answer.case.affected_txn_ids
    assert answer.case.pattern is not Pattern.CARD_TESTING


def test_reruns_of_the_same_case_agree(graph: FixtureGraphClient) -> None:
    """Same inputs and seed must produce the same structured decision."""
    txn_id, ts = _testing_anchor(graph)
    first = investigate(
        graph,
        case_id="GOLD-011",
        customer_id="FIXC02",
        card_id="FIXC02-K1",
        txn_id=txn_id,
        opened_at=ts,
    )
    second = investigate(
        graph,
        case_id="GOLD-011",
        customer_id="FIXC02",
        card_id="FIXC02-K1",
        txn_id=txn_id,
        opened_at=ts,
    )

    assert first.case.verdict == second.case.verdict
    assert first.case.fraud_probability == second.case.fraud_probability
    assert first.case.pattern == second.case.pattern
    assert first.case.exposure_usd == second.case.exposure_usd
    assert [i.action for i in first.next_best_actions.final] == [
        i.action for i in second.next_best_actions.final
    ]


def test_an_unconfirmable_anchor_escalates_rather_than_guessing(
    graph: FixtureGraphClient,
) -> None:
    answer = investigate(
        graph,
        case_id="GOLD-012",
        customer_id="FIXC02",
        card_id="FIXC02-K1",
        txn_id="no-such-transaction",
        opened_at=datetime(2016, 11, 20, 12, 0, 0),
    )
    actions = [item.action for item in answer.next_best_actions.final]
    assert Action.ESCALATE_TO_ANALYST in actions
    assert answer.case.status is CaseStatus.ESCALATED
    assert answer.case.verdict is Verdict.UNCERTAIN
    assert answer.case.affected_txn_ids == []


def test_an_episode_does_not_normalise_its_own_device(graph: FixtureGraphClient) -> None:
    """Counter-evidence must not cite the fraud's own activity as history.

    The baseline window ends at the cutoff, so it contains the episode's
    earlier transactions. Without a guard, a compromise that ran for a few
    hours would establish its own device as familiar and then cite that as
    evidence of innocence -- producing an answer that contradicts itself.
    """
    txn_id, ts = _testing_anchor(graph)
    trigger = Trigger(
        case_id="GOLD-013",
        trigger_type=TriggerType.RISK_SCORE,
        trigger_text="testing",
        flagged_txn_id=txn_id,
        card_id="FIXC02-K1",
        customer_id="FIXC02",
        opened_at=ts,
        risk_score=0.61,
    )
    state = run_investigation(trigger, graph).state

    claims = [record.claim for record in state.evidence]
    says_new = any("marked New for this account" in claim for claim in claims)
    says_known = any("is not new to the account" in claim for claim in claims)

    assert says_new, "the planted device is marked New by the identity record"
    assert not says_known, "the same device must not also be reported as familiar"


def test_r7_disputed_recurring_charge_is_verified_not_blocked() -> None:
    """R7: a disputed charge matching the cardholder's own recurring pattern.

    The policy is explicit that this must not be blocked. It is also the one
    route by which a disputed charge can be concluded legitimate, so the
    verdict must be allowed to land there rather than being held uncertain
    purely because the customer complained.
    """
    facts = PolicyFacts(
        case_id="GOLD-R7",
        verdict=Verdict.LEGITIMATE,
        fraud_probability=0.0,
        pattern=Pattern.NONE,
        exposure_usd=0.0,
        customer_disputed=True,
        matches_recurring_legitimate_pattern=True,
    )
    decision = decide(facts)

    assert "R7" in decision.triggered_rules
    actions = [item.action for item in decision.actions]
    assert Action.CREATE_CASE in actions
    assert Action.VERIFY_WITH_CUSTOMER in actions
    assert Action.WARN_CUSTOMER in actions
    assert Action.BLOCK_CARD not in actions
    assert decision.is_barred(Action.BLOCK_CARD)
    assert decision.requires_report is False


def test_a_generic_device_profile_does_not_connect_cardholders() -> None:
    """A popular configuration must not become a filing predicate.

    In the official data the most-shared profile is used by 1,011 unrelated
    customers. Treating that as a shared device would connect all of them and,
    under policy 3a, justify a report on nearly every online case.
    """
    from fraudlens_investigator.device_identity import select_linking_device

    generic = [
        {
            "device_id": "Dgeneric",
            "readable": "Windows | Windows 10 | chrome 63.0 | 1920x1080",
            "customer_fanout": 842,
        }
    ]
    assert select_linking_device(generic) is None

    specific = [
        {
            "device_id": "Dspecific",
            "readable": "SAMSUNG SM-G892A Build/NRD90M | Android 7.0 | samsung browser 6.2 | 2220x1080",
            "customer_fanout": 3,
        }
    ]
    assert select_linking_device(specific) is not None
