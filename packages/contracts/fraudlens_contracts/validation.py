"""Dataset-aware validation of a finished answer file.

`answer.py` enforces everything checkable from the answer alone. This module
enforces the rest: that every referenced ID exists in the supplied data, that
exposure equals the arithmetic it claims, and that every route matches the
policy matrix recomputed independently of the agent.

The validator is the export gate. It returns a report rather than raising, so
a run can surface every problem at once instead of one per attempt.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from .answer import CaseAnswer
from .enums import Action, Route, Verdict

# Exposure is compared to the cent. Floating point sums of USD amounts can
# drift by a fraction of a cent, which is not a real disagreement.
EXPOSURE_TOLERANCE_USD = 0.01


class DatasetResolver(Protocol):
    """The lookups a validator needs from the supplied dataset.

    Implemented against TigerGraph in production and against small in-memory
    fixtures in tests, so validation never requires a live graph.
    """

    def transaction_exists(self, txn_id: str) -> bool: ...

    def card_exists(self, card_id: str) -> bool: ...

    def customer_exists(self, customer_id: str) -> bool: ...

    def closed_case_exists(self, case_id: str) -> bool: ...

    def transaction_amount(self, txn_id: str) -> float | None: ...

    def transaction_timestamp(self, txn_id: str) -> datetime | None: ...


@dataclass
class ValidationIssue:
    """One problem found in an answer."""

    code: str
    field: str
    message: str

    def __str__(self) -> str:
        return f"[{self.code}] {self.field}: {self.message}"


@dataclass
class ValidationReport:
    """The result of validating one answer."""

    case_id: str
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def add(self, code: str, field_name: str, message: str) -> None:
        self.issues.append(ValidationIssue(code=code, field=field_name, message=message))

    def summary(self) -> str:
        if self.ok:
            return f"{self.case_id}: valid"
        lines = "\n".join(f"  {issue}" for issue in self.issues)
        return f"{self.case_id}: {len(self.issues)} issue(s)\n{lines}"


def _check_id_membership(
    report: ValidationReport,
    field_name: str,
    ids: Iterable[str],
    exists: object,
    kind: str,
) -> None:
    for value in ids:
        if not exists(value):  # type: ignore[operator]
            report.add(
                "UNKNOWN_ID",
                field_name,
                f"{kind} {value!r} does not exist in the supplied dataset",
            )


def validate_answer(
    answer: CaseAnswer,
    resolver: DatasetResolver,
    *,
    expected_case_ids: Mapping[str, object] | None = None,
) -> ValidationReport:
    """Validate one answer against the dataset and the policy matrix."""
    report = ValidationReport(case_id=answer.case_id)

    if expected_case_ids is not None and answer.case_id not in expected_case_ids:
        report.add(
            "UNKNOWN_CASE",
            "case_id",
            f"{answer.case_id!r} is not in the supplied case pack",
        )

    case = answer.case

    # --- ID integrity: made-up IDs score zero -----------------------------
    _check_id_membership(
        report,
        "case.affected_txn_ids",
        case.affected_txn_ids,
        resolver.transaction_exists,
        "transaction",
    )
    _check_id_membership(
        report, "case.connected_card_ids", case.connected_card_ids, resolver.card_exists, "card"
    )
    _check_id_membership(
        report,
        "case.similar_prior_cases",
        case.similar_prior_cases,
        resolver.closed_case_exists,
        "closed case",
    )
    if case.first_suspicious_txn_id and not resolver.transaction_exists(
        case.first_suspicious_txn_id
    ):
        report.add(
            "UNKNOWN_ID",
            "case.first_suspicious_txn_id",
            f"transaction {case.first_suspicious_txn_id!r} does not exist",
        )

    for index, item in enumerate(case.evidence):
        for entity_id in item.entity_ids:
            known = (
                resolver.transaction_exists(entity_id)
                or resolver.card_exists(entity_id)
                or resolver.customer_exists(entity_id)
                or resolver.closed_case_exists(entity_id)
            )
            if not known:
                report.add(
                    "UNKNOWN_ID",
                    f"case.evidence[{index}].entity_ids",
                    f"{entity_id!r} matches no transaction, card, customer, or closed case",
                )

    # --- Exposure arithmetic ---------------------------------------------
    amounts: list[float] = []
    missing_amounts = False
    for txn_id in case.affected_txn_ids:
        amount = resolver.transaction_amount(txn_id)
        if amount is None:
            missing_amounts = True
            continue
        amounts.append(abs(amount))

    if not missing_amounts:
        expected_exposure = round(sum(amounts), 2)
        if abs(expected_exposure - case.exposure_usd) > EXPOSURE_TOLERANCE_USD:
            report.add(
                "EXPOSURE_MISMATCH",
                "case.exposure_usd",
                f"reported ${case.exposure_usd:,.2f} but affected transactions sum to "
                f"${expected_exposure:,.2f}",
            )

    # --- SAR consistency --------------------------------------------------
    if answer.sar.file:
        if not missing_amounts and amounts:
            expected_total = round(sum(amounts), 2)
            if abs(expected_total - answer.sar.total_amount_usd) > EXPOSURE_TOLERANCE_USD:
                report.add(
                    "SAR_TOTAL_MISMATCH",
                    "sar.total_amount_usd",
                    f"reported ${answer.sar.total_amount_usd:,.2f} but the affected "
                    f"transactions sum to ${expected_total:,.2f}",
                )

        timestamps = [resolver.transaction_timestamp(txn_id) for txn_id in case.affected_txn_ids]
        known_times = [value for value in timestamps if value is not None]
        if known_times and len(answer.sar.activity_dates) == 2:
            first = min(known_times).strftime("%Y-%m-%d")
            last = max(known_times).strftime("%Y-%m-%d")
            if [first, last] != answer.sar.activity_dates:
                report.add(
                    "SAR_DATES_MISMATCH",
                    "sar.activity_dates",
                    f"reported {answer.sar.activity_dates} but the affected transactions "
                    f"span [{first!r}, {last!r}]",
                )

        for subject in answer.sar.subjects:
            known = (
                resolver.card_exists(subject)
                or resolver.customer_exists(subject)
                or resolver.transaction_exists(subject)
            )
            # Device profiles are descriptive strings, not dataset IDs, so a
            # subject that resolves to nothing is only a problem when it looks
            # like an entity ID.
            if not known and subject.startswith("C") and "|" not in subject:
                report.add(
                    "UNKNOWN_ID",
                    "sar.subjects",
                    f"{subject!r} looks like a customer or card ID but does not exist",
                )

    # --- Route integrity: recompute, never trust ---------------------------
    from_policy_exposure = case.exposure_usd
    for label, recommendations in (
        ("initial", answer.next_best_actions.initial),
        ("final", answer.next_best_actions.final),
    ):
        seen: set[Action] = set()
        for index, item in enumerate(recommendations):
            expected_route = _expected_route(item.action, from_policy_exposure)
            if item.route is not expected_route:
                report.add(
                    "ROUTE_MISMATCH",
                    f"next_best_actions.{label}[{index}]",
                    f"{item.action.value} at exposure ${from_policy_exposure:,.2f} routes "
                    f"{expected_route.value}, not {item.route.value}",
                )
            if item.action in seen:
                report.add(
                    "DUPLICATE_ACTION",
                    f"next_best_actions.{label}[{index}]",
                    f"{item.action.value} is recommended more than once",
                )
            seen.add(item.action)

    # --- Verdict / status coherence ---------------------------------------
    _check_status_coherence(report, answer)

    return report


def _expected_route(action: Action, exposure_usd: float) -> Route:
    """Recompute a route without importing the policy service.

    The contracts package must not depend on the policy engine, so the matrix
    is restated here. The duplication is intentional: it makes the validator
    an independent check rather than a restatement of the thing it validates.
    A drift between the two is caught by `test_route_matrix_agrees`.
    """
    auto = {
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
    }
    if action in auto:
        return Route.AUTO
    if action in {Action.BLOCK_ALL_CARDS, Action.FILE_REPORT}:
        return Route.L2
    if action is Action.DECLINE_TRANSACTION:
        return Route.L1
    if action is Action.BLOCK_CARD:
        return Route.L2 if exposure_usd > 2_500.0 else Route.L1
    raise ValueError(f"no route defined for action {action!r}")


def _check_status_coherence(report: ValidationReport, answer: CaseAnswer) -> None:
    """Case status must agree with the verdict and the actions taken."""
    case = answer.case
    final_actions = {item.action for item in answer.next_best_actions.final}

    if case.status.value == "closed_legitimate" and case.verdict is not Verdict.LEGITIMATE:
        report.add(
            "STATUS_MISMATCH",
            "case.status",
            f"closed_legitimate requires a legitimate verdict, found {case.verdict.value}",
        )
    if case.status.value == "closed_fraud" and case.verdict is not Verdict.FRAUD:
        report.add(
            "STATUS_MISMATCH",
            "case.status",
            f"closed_fraud requires a fraud verdict, found {case.verdict.value}",
        )
    if case.status.value == "escalated" and Action.ESCALATE_TO_ANALYST not in final_actions:
        report.add(
            "STATUS_MISMATCH",
            "case.status",
            "escalated status requires ESCALATE_TO_ANALYST among the final actions",
        )
    if Action.CREATE_CASE in final_actions and not case.written_to_graph:
        report.add(
            "GRAPH_WRITE_MISSING",
            "case.written_to_graph",
            "CREATE_CASE was recommended but the case was not written to the graph",
        )


def validate_many(
    answers: Iterable[CaseAnswer],
    resolver: DatasetResolver,
    *,
    expected_case_ids: Mapping[str, object] | None = None,
) -> list[ValidationReport]:
    return [
        validate_answer(answer, resolver, expected_case_ids=expected_case_ids) for answer in answers
    ]
