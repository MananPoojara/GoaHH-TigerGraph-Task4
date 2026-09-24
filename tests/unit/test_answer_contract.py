"""Answer-contract tests.

The anchor test parses the worked example from the dataset README. If our
schema and the official contract ever disagree, that test is the first to say
so.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from fraudlens_contracts import Action, CaseAnswer, Pattern, Route, Verdict, count_sentences
from fraudlens_contracts.validation import validate_answer
from fraudlens_policy import route_for
from pydantic import ValidationError

FIXTURES = Path(__file__).resolve().parents[2] / "data" / "fixtures"
README_EXAMPLE = FIXTURES / "readme_example_answer.json"


class FixtureResolver:
    """An in-memory stand-in for the dataset, so validation needs no graph."""

    def __init__(
        self,
        transactions: dict[str, tuple[float, str]] | None = None,
        cards: set[str] | None = None,
        customers: set[str] | None = None,
        closed_cases: set[str] | None = None,
    ) -> None:
        self._transactions = transactions or {}
        self._cards = cards or set()
        self._customers = customers or set()
        self._closed_cases = closed_cases or set()

    def transaction_exists(self, txn_id: str) -> bool:
        return txn_id in self._transactions

    def card_exists(self, card_id: str) -> bool:
        return card_id in self._cards

    def customer_exists(self, customer_id: str) -> bool:
        return customer_id in self._customers

    def closed_case_exists(self, case_id: str) -> bool:
        return case_id in self._closed_cases

    def transaction_amount(self, txn_id: str) -> float | None:
        entry = self._transactions.get(txn_id)
        return None if entry is None else entry[0]

    def transaction_timestamp(self, txn_id: str) -> datetime | None:
        entry = self._transactions.get(txn_id)
        if entry is None:
            return None
        return datetime.strptime(entry[1], "%Y-%m-%d %H:%M:%S")


@pytest.fixture
def readme_answer() -> CaseAnswer:
    return CaseAnswer.model_validate(json.loads(README_EXAMPLE.read_text(encoding="utf-8")))


def test_readme_example_parses_against_our_schema(readme_answer: CaseAnswer) -> None:
    """The official example must satisfy the contract we generate against."""
    assert readme_answer.case_id == "HHG-017"
    assert readme_answer.case.verdict is Verdict.FRAUD
    assert readme_answer.case.pattern is Pattern.CARD_TESTING
    assert readme_answer.sar.file is True
    assert Action.FILE_REPORT in [a.action for a in readme_answer.next_best_actions.final]


def test_readme_example_routes_match_the_policy_matrix(readme_answer: CaseAnswer) -> None:
    exposure = readme_answer.case.exposure_usd
    for item in readme_answer.next_best_actions.final:
        assert item.route is route_for(item.action, exposure), item.action


def test_readme_example_passes_dataset_validation(readme_answer: CaseAnswer) -> None:
    resolver = FixtureResolver(
        transactions={
            "T0412877": (1.10, "2016-11-14 09:12:00"),
            "T0412878": (2.40, "2016-11-14 09:30:00"),
            "T0412879": (0.95, "2016-11-14 09:52:00"),
            "T0412883": (263.98, "2016-11-14 10:31:00"),
        },
        cards={"C00377-K1", "C00877-K1"},
        customers={"C00377"},
        closed_cases={"CC-0141"},
    )
    report = validate_answer(readme_answer, resolver)
    assert report.ok, report.summary()


def test_readme_narrative_is_within_the_sentence_band(readme_answer: CaseAnswer) -> None:
    sentences = count_sentences(readme_answer.sar.narrative)
    assert 6 <= sentences <= 12, f"README narrative counted as {sentences} sentences"


def test_dollar_amounts_do_not_inflate_the_sentence_count() -> None:
    assert count_sentences("Total was $268.43 for the episode.") == 1


# --------------------------------------------------------------------------
# Structural invariants
# --------------------------------------------------------------------------


def _valid_payload() -> dict:
    return json.loads(README_EXAMPLE.read_text(encoding="utf-8"))


def test_sar_file_must_agree_with_final_actions() -> None:
    payload = _valid_payload()
    payload["sar"]["file"] = False
    payload["sar"]["narrative"] = ""
    payload["sar"]["subjects"] = []
    payload["sar"]["total_amount_usd"] = 0
    payload["sar"]["activity_dates"] = []
    with pytest.raises(ValidationError, match="sar.file must agree"):
        CaseAnswer.model_validate(payload)


def test_file_report_requires_create_case() -> None:
    payload = _valid_payload()
    payload["next_best_actions"]["final"] = [
        item for item in payload["next_best_actions"]["final"] if item["action"] != "CREATE_CASE"
    ]
    with pytest.raises(ValidationError, match="FILE_REPORT requires CREATE_CASE"):
        CaseAnswer.model_validate(payload)


def test_legitimate_verdict_must_have_no_affected_transactions() -> None:
    payload = _valid_payload()
    payload["case"]["verdict"] = "legitimate"
    with pytest.raises(ValidationError, match="no affected transactions"):
        CaseAnswer.model_validate(payload)


def test_unfiled_sar_must_use_the_specified_empty_values() -> None:
    payload = _valid_payload()
    payload["sar"]["file"] = False
    with pytest.raises(ValidationError, match="narrative must be empty"):
        CaseAnswer.model_validate(payload)


def test_final_must_equal_initial_when_nothing_was_requested() -> None:
    payload = _valid_payload()
    payload["evidence_requests"] = []
    with pytest.raises(ValidationError, match="final actions must equal initial"):
        CaseAnswer.model_validate(payload)


def test_what_changed_must_say_nothing_when_nothing_was_requested() -> None:
    payload = _valid_payload()
    payload["evidence_requests"] = []
    payload["next_best_actions"]["final"] = payload["next_best_actions"]["initial"]
    payload["sar"] = {
        "file": False,
        "reason": "No report predicate holds.",
        "narrative": "",
        "subjects": [],
        "total_amount_usd": 0,
        "activity_dates": [],
    }
    with pytest.raises(ValidationError, match="what_changed must be 'nothing'"):
        CaseAnswer.model_validate(payload)


def test_undocumented_pattern_requires_a_description() -> None:
    payload = _valid_payload()
    payload["case"]["pattern"] = "undocumented"
    with pytest.raises(ValidationError, match="pattern_description is required"):
        CaseAnswer.model_validate(payload)


def test_known_pattern_must_not_carry_a_description() -> None:
    payload = _valid_payload()
    payload["case"]["pattern_description"] = "Some description"
    with pytest.raises(ValidationError, match="pattern_description must be empty"):
        CaseAnswer.model_validate(payload)


def test_first_suspicious_must_be_among_affected() -> None:
    payload = _valid_payload()
    payload["case"]["first_suspicious_txn_id"] = "T9999999"
    with pytest.raises(ValidationError, match="must be one of affected_txn_ids"):
        CaseAnswer.model_validate(payload)


def test_unknown_field_is_rejected() -> None:
    payload = _valid_payload()
    payload["case"]["invented_field"] = True
    with pytest.raises(ValidationError):
        CaseAnswer.model_validate(payload)


def test_short_narrative_is_rejected() -> None:
    payload = _valid_payload()
    payload["sar"]["narrative"] = "Too short. Only three sentences here. That is all."
    with pytest.raises(ValidationError, match="must be 6-12 sentences"):
        CaseAnswer.model_validate(payload)


# --------------------------------------------------------------------------
# Dataset-aware validation
# --------------------------------------------------------------------------


def test_invented_transaction_id_is_caught(readme_answer: CaseAnswer) -> None:
    resolver = FixtureResolver(
        transactions={"T0412877": (1.10, "2016-11-14 09:12:00")},
        cards={"C00377-K1", "C00877-K1"},
        customers={"C00377"},
        closed_cases={"CC-0141"},
    )
    report = validate_answer(readme_answer, resolver)
    assert not report.ok
    assert any(issue.code == "UNKNOWN_ID" for issue in report.issues)


def test_exposure_must_equal_the_sum_of_affected_amounts(readme_answer: CaseAnswer) -> None:
    resolver = FixtureResolver(
        transactions={
            "T0412877": (1.10, "2016-11-14 09:12:00"),
            "T0412878": (2.40, "2016-11-14 09:30:00"),
            "T0412879": (0.95, "2016-11-14 09:52:00"),
            "T0412883": (999.99, "2016-11-14 10:31:00"),
        },
        cards={"C00377-K1", "C00877-K1"},
        customers={"C00377"},
        closed_cases={"CC-0141"},
    )
    report = validate_answer(readme_answer, resolver)
    assert any(issue.code == "EXPOSURE_MISMATCH" for issue in report.issues), report.summary()


def test_exposure_uses_absolute_amounts() -> None:
    """Policy 4: exposure sums absolute amounts, so a refund cannot cancel a debit."""
    payload = _valid_payload()
    payload["case"]["affected_txn_ids"] = ["T1", "T2"]
    payload["case"]["first_suspicious_txn_id"] = "T1"
    payload["case"]["exposure_usd"] = 150.0
    payload["sar"]["total_amount_usd"] = 150.0
    payload["sar"]["subjects"] = ["C00377"]
    payload["sar"]["activity_dates"] = ["2016-11-14", "2016-11-14"]
    payload["case"]["evidence"] = []
    answer = CaseAnswer.model_validate(payload)

    resolver = FixtureResolver(
        transactions={
            "T1": (100.0, "2016-11-14 09:00:00"),
            "T2": (-50.0, "2016-11-14 10:00:00"),
        },
        cards={"C00877-K1"},
        customers={"C00377"},
        closed_cases={"CC-0141"},
    )
    report = validate_answer(answer, resolver)
    assert not any(issue.code == "EXPOSURE_MISMATCH" for issue in report.issues), report.summary()


def test_route_matrix_agrees_between_validator_and_policy_engine() -> None:
    """The validator restates the matrix deliberately; it must not drift."""
    from fraudlens_contracts.validation import _expected_route

    for action in Action:
        for exposure in (0.0, 2_500.0, 2_500.01, 10_000.0):
            assert _expected_route(action, exposure) is route_for(action, exposure), (
                action,
                exposure,
            )


def test_tampered_route_is_caught(readme_answer: CaseAnswer) -> None:
    tampered = readme_answer.model_copy(deep=True)
    tampered.next_best_actions.final[2].route = Route.AUTO  # FILE_REPORT is always L2
    resolver = FixtureResolver(
        transactions={
            "T0412877": (1.10, "2016-11-14 09:12:00"),
            "T0412878": (2.40, "2016-11-14 09:30:00"),
            "T0412879": (0.95, "2016-11-14 09:52:00"),
            "T0412883": (263.98, "2016-11-14 10:31:00"),
        },
        cards={"C00377-K1", "C00877-K1"},
        customers={"C00377"},
        closed_cases={"CC-0141"},
    )
    report = validate_answer(tampered, resolver)
    assert any(issue.code == "ROUTE_MISMATCH" for issue in report.issues), report.summary()
