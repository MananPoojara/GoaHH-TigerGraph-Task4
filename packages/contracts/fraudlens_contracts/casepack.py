"""Typed readers for the two official CSV inputs that define case context.

These are supplied data, not derived state: the loaders parse them exactly and
refuse to silently coerce a malformed row.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from pydantic import Field, field_validator

from .answer import StrictModel
from .enums import CaseTrustTier, Pattern, TriggerType

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


def _parse_timestamp(value: str) -> datetime:
    return datetime.strptime(value.strip(), TIMESTAMP_FORMAT)


class CasePackEntry(StrictModel):
    """One of the 20 benchmark alerts from `case_pack.csv`.

    `risk_score` is populated only for `risk_score` triggers; the README is
    explicit that it is an input, never an answer.
    """

    case_id: str
    opened_at: datetime
    trigger_type: TriggerType
    trigger_text: str
    flagged_txn_id: str
    card_id: str
    customer_id: str
    risk_score: float | None = None

    @field_validator("opened_at", mode="before")
    @classmethod
    def _coerce_opened_at(cls, value: object) -> object:
        return _parse_timestamp(value) if isinstance(value, str) else value

    @field_validator("risk_score", mode="before")
    @classmethod
    def _coerce_risk_score(cls, value: object) -> object:
        # Non-risk-score triggers carry an empty cell, not a zero.
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def cutoff(self) -> datetime:
        """Decision time. Nothing after this instant may inform the case."""
        return self.opened_at


class ClosedCase(StrictModel):
    """A finished bank investigation from `closed_cases_history.csv`.

    This is the only place ground truth is written down, and it is the agent's
    starting memory. Cleared cases carry `pattern == none` and no first fraud
    transaction.
    """

    case_id: str
    customer_id: str
    card_id: str
    opened_at: datetime
    closed_at: datetime
    outcome: str
    pattern: Pattern
    first_fraud_txn_id: str = ""
    txn_ids: list[str] = Field(default_factory=list)
    n_txns: int = 0
    exposure_usd: float = 0.0
    connected_card_ids: list[str] = Field(default_factory=list)
    actions_taken: list[str] = Field(default_factory=list)
    report_filed: bool = False
    analyst_notes: str = ""

    trust_tier: CaseTrustTier = CaseTrustTier.LABELED_HISTORY

    @field_validator("opened_at", "closed_at", mode="before")
    @classmethod
    def _coerce_times(cls, value: object) -> object:
        return _parse_timestamp(value) if isinstance(value, str) else value

    @field_validator("txn_ids", "connected_card_ids", "actions_taken", mode="before")
    @classmethod
    def _split_pipes(cls, value: object) -> object:
        if isinstance(value, str):
            return [part for part in (p.strip() for p in value.split("|")) if part]
        return value

    @field_validator("report_filed", mode="before")
    @classmethod
    def _coerce_report_filed(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower() in {"yes", "true", "1"}
        return value

    @property
    def is_confirmed_fraud(self) -> bool:
        return self.outcome == "confirmed_fraud"


def load_case_pack(path: str | Path) -> list[CasePackEntry]:
    """Read `case_pack.csv` in file order."""
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return [CasePackEntry.model_validate(row) for row in csv.DictReader(handle)]


def iter_closed_cases(path: str | Path) -> Iterator[ClosedCase]:
    """Stream `closed_cases_history.csv` without holding the file in memory twice."""
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            yield ClosedCase.model_validate(row)


def load_closed_cases(path: str | Path) -> list[ClosedCase]:
    return list(iter_closed_cases(path))
