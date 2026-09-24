"""Explanation and SAR narrative construction.

Both outputs are built from the evidence ledger, never from the model's
recollection. The LLM may rewrite the prose for readability, but the facts,
IDs, totals, and dates come from validated state, and the result is checked
against the same constraints either way.

The SAR is the one place the README asks for completeness: it must stand on
its own for a regulator, answering who, what, when, where, how, and why, in
six to twelve sentences.
"""

from __future__ import annotations

import logging

from fraudlens_contracts import Verdict, count_sentences

from .llm import INVESTIGATOR_SYSTEM_PROMPT, LLMPort, build_evidence_context
from .state import CaseState

logger = logging.getLogger(__name__)

MIN_SAR_SENTENCES = 6
MAX_SAR_SENTENCES = 12


def _activity_dates(state: CaseState) -> tuple[str, str]:
    """First and last date of the affected activity, as YYYY-MM-DD."""
    timestamps: list[str] = []
    for key, field_name in (
        ("window", "window"),
        ("cnp_burst", "online_transactions"),
        ("card_testing", "sequence"),
    ):
        for row in state.observations.get(key, {}).get(field_name) or []:
            if row.get("txn_id") in state.affected_txn_ids and row.get("ts"):
                timestamps.append(str(row["ts"])[:10])
    if state.anchor and state.anchor.get("txn_id") in state.affected_txn_ids:
        timestamps.append(str(state.anchor.get("ts", ""))[:10])

    if not timestamps:
        anchor_date = str(state.anchor.get("ts", ""))[:10] or state.trigger.opened_at.strftime(
            "%Y-%m-%d"
        )
        return anchor_date, anchor_date
    return min(timestamps), max(timestamps)


def build_summary(state: CaseState, llm: LLMPort) -> str:
    """Two to six sentences an analyst could act on.

    The deterministic version is always constructed first; the model is only
    asked to improve its readability, and its output is discarded if it
    strays outside the length the README asks for.
    """
    current = state.current
    assert current is not None

    deterministic = _deterministic_summary(state)

    if not llm.available:
        return deterministic

    context = build_evidence_context(
        trigger_text=state.trigger.trigger_text,
        anchor=state.anchor,
        evidence_claims=[record.claim for record in state.evidence],
        baseline=state.baseline,
        prior_cases=[
            {
                "case_id": case.case_id,
                "outcome": case.outcome,
                "pattern": case.pattern,
                "link_reason": case.link_reason,
            }
            for case in state.prior_cases
        ],
    )
    rewritten = llm.complete_text(
        INVESTIGATOR_SYSTEM_PROMPT,
        (
            f"{context}\n"
            f"ASSESSMENT: verdict {current.verdict.value}, probability "
            f"{current.fraud_probability:.2f}, pattern {current.pattern.value}, "
            f"exposure ${state.exposure_usd:,.2f}.\n\n"
            "Write a case summary of two to six sentences for a fraud analyst. "
            "Use only the evidence above. Do not recommend actions, and do not "
            "state any ID or amount that does not appear above."
        ),
    )

    if rewritten and 2 <= count_sentences(rewritten) <= 6:
        return rewritten
    if rewritten:
        logger.info("LLM summary was outside the 2-6 sentence band; using deterministic text")
    return deterministic


def _deterministic_summary(state: CaseState) -> str:
    current = state.current
    assert current is not None

    supporting = [record for record in state.evidence if record.supports_fraud]
    counter = state.counter_evidence()

    sentences: list[str] = []

    if current.verdict is Verdict.FRAUD:
        opening = (
            f"Assessed as fraud at probability {current.fraud_probability:.2f}, "
            f"matching the {current.pattern.value.replace('_', ' ')} pattern."
        )
    elif current.verdict is Verdict.LEGITIMATE:
        opening = (
            f"Assessed as legitimate at fraud probability "
            f"{current.fraud_probability:.2f}; the activity is consistent with the "
            "cardholder's own history."
        )
    else:
        opening = (
            f"Assessment is uncertain at probability {current.fraud_probability:.2f}; "
            "the evidence does not settle whether the activity was authorized."
        )
    sentences.append(opening)

    if supporting:
        sentences.append(supporting[0].claim + ".")
    if len(supporting) > 1:
        sentences.append(supporting[1].claim + ".")
    if counter:
        sentences.append(
            "Against that, " + counter[0].claim[0].lower() + counter[0].claim[1:] + "."
        )

    if state.affected_txn_ids:
        sentences.append(
            f"{len(state.affected_txn_ids)} transaction(s) totalling "
            f"${state.exposure_usd:,.2f} are attributed to the episode."
        )
    if state.connected_card_ids:
        sentences.append(
            f"{len(state.connected_card_ids)} other card(s) are connected through a "
            "shared device profile."
        )

    # The README asks for two to six sentences.
    return " ".join(sentences[:6])


def build_sar_narrative(state: CaseState, llm: LLMPort) -> str:
    """The regulatory filing, six to twelve sentences, standing on its own.

    Built deterministically so every ID, amount, and date is traceable. If the
    model rewrites it, the result is only accepted when it stays inside the
    required sentence band.
    """
    current = state.current
    assert current is not None

    first_date, last_date = _activity_dates(state)
    deterministic = _deterministic_sar(state, first_date, last_date)

    if not llm.available:
        return deterministic

    rewritten = llm.complete_text(
        INVESTIGATOR_SYSTEM_PROMPT,
        (
            "Rewrite the following suspicious activity report narrative so it reads "
            "clearly for a regulator. Keep every identifier, amount, and date exactly "
            "as given; add nothing that is not stated. It must be between six and "
            "twelve sentences and must cover who, what, when, where, how, and why the "
            f"activity is suspicious.\n\n{deterministic}"
        ),
    )
    if rewritten and MIN_SAR_SENTENCES <= count_sentences(rewritten) <= MAX_SAR_SENTENCES:
        return rewritten
    if rewritten:
        logger.info("LLM narrative was outside the 6-12 sentence band; using deterministic text")
    return deterministic


def _deterministic_sar(state: CaseState, first_date: str, last_date: str) -> str:
    """Assemble a narrative covering the six required elements.

    Sentences are appended in a fixed order and then trimmed or padded to the
    required band, so the output is always inside the contract.
    """
    current = state.current
    assert current is not None

    customer = state.trigger.customer_id
    card = state.trigger.card_id
    count = len(state.affected_txn_ids)
    channels = _channels_used(state)

    sentences: list[str] = []

    # WHO and WHAT
    sentences.append(
        f"Between {first_date} and {last_date}, {count} transaction(s) totalling "
        f"${state.exposure_usd:,.2f} on card {card}, held by customer {customer}, "
        "were identified as suspicious."
    )
    # WHEN and WHERE
    sentences.append(
        f"The activity was conducted via {channels} and was flagged after "
        f"{_trigger_phrase(state)}."
    )
    # HOW
    supporting = [record for record in state.evidence if record.supports_fraud]
    for record in supporting[:3]:
        sentences.append(record.claim + ".")

    # Connections
    if state.connected_card_ids:
        sentences.append(
            f"The same device profile was observed on {len(state.connected_card_ids)} "
            f"other card(s): {', '.join(state.connected_card_ids[:5])}."
        )
    if state.prior_cases:
        confirmed = [case for case in state.prior_cases if case.outcome == "confirmed_fraud"]
        if confirmed:
            sentences.append(
                f"{len(confirmed)} previously closed case(s) with confirmed fraud share "
                f"structure with this activity, including {confirmed[0].case_id}."
            )

    # Customer response
    response = state.requests[-1] if state.requests else None
    if response and response.customer_denied:
        sentences.append(
            "The cardholder was contacted and stated they did not authorize the "
            "transactions; this response was simulated for this exercise."
        )

    # WHY it is suspicious
    sentences.append(
        f"The activity is suspicious because it matches the "
        f"{current.pattern.value.replace('_', ' ')} typology and departs from the "
        f"cardholder's established pattern of "
        f"{int(state.baseline.get('txn_count', 0))} prior transactions."
    )
    # Disposition
    sentences.append(
        f"The internal case was assessed at fraud probability "
        f"{current.fraud_probability:.2f} and the supporting evidence is retained "
        "with the case record."
    )

    # Trim to the maximum, then pad if a sparse case fell short.
    if len(sentences) > MAX_SAR_SENTENCES:
        sentences = sentences[:MAX_SAR_SENTENCES]

    while len(sentences) < MIN_SAR_SENTENCES:
        sentences.append(
            "No further corroborating activity was identified within the " "investigation window."
        )

    return " ".join(sentences)


def _channels_used(state: CaseState) -> str:
    channels: set[str] = set()
    for key, field_name in (("window", "window"), ("card_testing", "sequence")):
        for row in state.observations.get(key, {}).get(field_name) or []:
            if row.get("txn_id") in state.affected_txn_ids and row.get("channel"):
                channels.add(str(row["channel"]).replace("_", "-"))
    if not channels and state.anchor.get("channel"):
        channels.add(str(state.anchor["channel"]).replace("_", "-"))
    return " and ".join(sorted(channels)) or "card"


def _trigger_phrase(state: CaseState) -> str:
    trigger = state.trigger
    if trigger.trigger_type.value == "risk_score":
        score = trigger.risk_score if trigger.risk_score is not None else 0.0
        return f"the bank's detection model scored the transaction at {score:.2f}"
    if trigger.trigger_type.value == "customer_report":
        return "the cardholder reported an unrecognised charge"
    return "an analyst requested a review of related activity"


def build_stop_reason(state: CaseState) -> str:
    """Why the investigation ended where it did (policy 6)."""
    if state.stop_reason:
        return state.stop_reason

    current = state.current
    assert current is not None

    response = state.requests[-1] if state.requests else None
    if response and (response.customer_denied or response.customer_confirmed):
        return (
            "The verification response settled the authorization question, and the "
            "episode scope and connected cards are known."
        )
    if current.fraud_probability >= 0.85:
        return (
            f"Fraud probability reached {current.fraud_probability:.2f} with "
            f"{current.independent_signal_count} independent evidence families, "
            "which meets the stopping threshold."
        )
    if current.fraud_probability <= 0.15:
        return (
            f"Fraud probability fell to {current.fraud_probability:.2f} with "
            f"{current.independent_signal_count} independent evidence families "
            "supporting a legitimate explanation."
        )
    return (
        f"The case remains uncertain at probability {current.fraud_probability:.2f}. "
        "Further automated evidence would not change the recommended actions, so it "
        "is handed to an analyst rather than investigated further."
    )
