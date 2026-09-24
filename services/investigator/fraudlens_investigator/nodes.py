"""Investigation nodes.

Each node takes `CaseState` and returns it, mutated. They are plain functions
rather than LangGraph internals so they can be unit-tested in isolation and
replayed from a checkpoint; `workflow.py` only wires them together.

The division of labour is fixed:
  * nodes gather and normalise evidence;
  * `assessment.py` turns evidence into a probability;
  * `fraudlens_policy` turns a probability and facts into authorized actions;
  * the LLM writes prose about what the other three produced.

No node decides an action, and no node writes a fact it did not get from a
tool.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fraudlens_contracts import (
    EvidenceDirection,
    EvidenceRequestType,
    EvidenceSource,
    Pattern,
    Route,
    Verdict,
)
from fraudlens_graph import GraphClient, GraphError, tools
from fraudlens_policy import (
    CardTestingFacts,
    CustomerResponse,
    PolicyFacts,
    SharedOriginFacts,
    decide,
)
from fraudlens_simulator import SimulationContext, preview_all_responses, simulate

from .assessment import assess, should_stop
from .device_identity import assess_device, select_linking_device
from .llm import LLMPort
from .state import Assessment, CaseState, Hypothesis, PriorCase, RequestRecord

logger = logging.getLogger(__name__)

# Bounded windows. Wide enough to contain an episode, narrow enough that a
# query stays cheap and an analyst can read the result.
WINDOW_HOURS_CARD = 72
WINDOW_HOURS_TESTING = 24
WINDOW_HOURS_BURST = 48
WINDOW_HOURS_RING = 720  # 30 days, matching the README's "in one window"
BASELINE_LOOKBACK_DAYS = 180

# The small-amount threshold for card testing. The README says "often under
# $5"; the value is a parameter so it can be tuned with evidence rather than
# hidden in a predicate.
SMALL_AUTH_MAX_USD = 5.0

# R7 recurring-charge detection. The dataset has no merchant field, so a
# recurring charge is recognised from an identical product code and a
# near-identical amount. Two prior occurrences is the smallest number that
# establishes a pattern rather than a coincidence.
RECURRING_AMOUNT_TOLERANCE_USD = 1.0
MIN_RECURRING_MATCHES = 2

# Episode bounds. The README describes a card-not-present episode as "often a
# burst of two to four within 48 hours", so an episode is contiguous activity
# around the flagged transaction rather than everything in the query window.
# The transaction cap stops a very high-volume cardholder from producing an
# episode no analyst could review.
EPISODE_MAX_HOURS = 48
EPISODE_MAX_TRANSACTIONS = 25


@dataclass
class InvestigationDeps:
    """Everything a node needs from outside itself."""

    graph: GraphClient
    llm: LLMPort


# ---------------------------------------------------------------------------
# 1. Intake
# ---------------------------------------------------------------------------


def intake(state: CaseState, deps: InvestigationDeps) -> CaseState:
    """Confirm the trigger before investigating it.

    A case whose anchor cannot be confirmed is not investigated on a false
    premise; the integrity errors are recorded and the run escalates.
    """
    state.log("intake", "investigation_started", state.trigger.trigger_text)

    try:
        result = tools.get_case_anchor(
            deps.graph,
            txn_id=state.trigger.flagged_txn_id,
            card_id=state.trigger.card_id,
            customer_id=state.trigger.customer_id,
            cutoff=state.trigger.cutoff,
        )
    except GraphError as error:
        state.errors.append(f"anchor lookup failed: {error}")
        state.log("intake", "tool_failed", str(error))
        return state

    anchor_rows = result.data.get("anchor") or []
    state.integrity_errors = list(result.data.get("integrity_errors") or [])
    state.anchor = anchor_rows[0] if anchor_rows else {}
    state.anchor_confirmed = bool(state.anchor) and not state.integrity_errors

    if state.anchor_confirmed:
        state.add_evidence(
            claim=(
                f"Flagged transaction {state.anchor.get('txn_id')} for "
                f"${float(state.anchor.get('amount', 0)):,.2f} on "
                f"{state.anchor.get('ts')} is confirmed on card "
                f"{state.trigger.card_id} held by customer {state.trigger.customer_id}"
            ),
            source=EvidenceSource.GRAPH,
            ref=result.ref,
            entity_ids=[state.trigger.flagged_txn_id, state.trigger.card_id],
            direction=EvidenceDirection.CONTEXT,
            source_family="anchor",
            result_hash=result.receipt.result_hash if result.receipt else "",
        )
        state.log("intake", "case_created", f"anchor confirmed for {state.trigger.case_id}")
    else:
        state.log("intake", "tool_failed", "; ".join(state.integrity_errors) or "anchor missing")

    return state


# ---------------------------------------------------------------------------
# 2. Plan
# ---------------------------------------------------------------------------


def plan_evidence(state: CaseState, deps: InvestigationDeps) -> CaseState:
    """Name the questions to answer, not the conclusions to reach."""
    questions = [
        "What happened on this card immediately before and after the flagged transaction?",
        "How does this activity compare with the cardholder's own history?",
        "Is the device or billing region new for this account?",
        "Do other cards share the same device, region, or recipient email?",
        "Which closed cases resemble this one, and how did they end?",
    ]
    if state.trigger.customer_disputed:
        questions.insert(
            0, "Does the disputed charge match a recurring pattern the cardholder already had?"
        )

    state.plan = questions
    state.log("plan_evidence", "plan_created", f"{len(questions)} questions")
    return state


# ---------------------------------------------------------------------------
# 3. Collect
# ---------------------------------------------------------------------------


def _anchor_time(state: CaseState) -> datetime:
    raw = state.anchor.get("ts")
    if raw:
        try:
            return datetime.strptime(str(raw), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            logger.warning("unparseable anchor timestamp %r; falling back to cutoff", raw)
    return state.trigger.cutoff


def collect_evidence(state: CaseState, deps: InvestigationDeps) -> CaseState:
    """Run the bounded evidence queries and normalise what comes back."""
    cutoff = state.trigger.cutoff
    card_id = state.trigger.card_id
    customer_id = state.trigger.customer_id
    anchor_ts = _anchor_time(state)

    # --- baseline ---------------------------------------------------------
    baseline = tools.get_customer_baseline(
        deps.graph,
        customer_id=customer_id,
        cutoff=cutoff,
        lookback_days=BASELINE_LOOKBACK_DAYS,
    )
    state.baseline = baseline.data
    state.add_evidence(
        claim=(
            f"Cardholder {customer_id} has {baseline.data.get('txn_count', 0)} prior "
            f"transactions before the cutoff, averaging "
            f"${float(baseline.data.get('mean_amount', 0)):,.2f}, across "
            f"{len(baseline.data.get('known_regions') or [])} billing region(s)"
        ),
        source=EvidenceSource.GRAPH,
        ref=baseline.ref,
        entity_ids=[customer_id],
        direction=EvidenceDirection.CONTEXT,
        source_family="baseline",
        result_hash=baseline.receipt.result_hash if baseline.receipt else "",
    )

    # --- window -----------------------------------------------------------
    window = tools.get_transaction_history(
        deps.graph,
        card_id=card_id,
        anchor_ts=anchor_ts,
        cutoff=cutoff,
        hours_before=WINDOW_HOURS_CARD,
        hours_after=WINDOW_HOURS_CARD,
    )
    state.observations["window"] = window.data

    # --- pattern observations --------------------------------------------
    testing = tools.detect_card_testing(
        deps.graph,
        card_id=card_id,
        cutoff=cutoff,
        window_hours=WINDOW_HOURS_TESTING,
        small_amount_max=SMALL_AUTH_MAX_USD,
    )
    state.observations["card_testing"] = testing.data

    if int(testing.data.get("small_online_count", 0)) >= 3 and testing.data.get("larger_txn_ids"):
        state.add_evidence(
            claim=(
                f"{testing.data['small_online_count']} online authorizations at or under "
                f"${SMALL_AUTH_MAX_USD:,.2f} occurred on card {card_id} within "
                f"{WINDOW_HOURS_TESTING} hours, followed by "
                f"{len(testing.data['larger_txn_ids'])} larger purchase(s)"
            ),
            source=EvidenceSource.GRAPH,
            ref=testing.ref,
            entity_ids=list(testing.data.get("small_txn_ids", []))
            + list(testing.data.get("larger_txn_ids", [])),
            direction=EvidenceDirection.SUPPORTS_FRAUD,
            source_family="sequence",
            result_hash=testing.receipt.result_hash if testing.receipt else "",
        )

    burst = tools.detect_cnp_burst(
        deps.graph, card_id=card_id, cutoff=cutoff, window_hours=WINDOW_HOURS_BURST
    )
    state.observations["cnp_burst"] = burst.data

    if int(burst.data.get("new_device_count", 0)) > 0:
        # `entity_ids` must contain IDs that exist in the supplied dataset:
        # invented IDs score zero. A device profile ID is derived by us, not
        # supplied, so the transactions carry the claim and the readable
        # profile is reported separately in `connected_device_profiles`.
        new_device_txns = [
            row["txn_id"]
            for row in burst.data.get("online_transactions") or []
            if row.get("device_is_new")
        ]
        state.add_evidence(
            claim=(
                f"{burst.data['new_device_count']} online transaction(s) on card {card_id} "
                "came from a device profile marked New for this account"
            ),
            source=EvidenceSource.GRAPH,
            ref=burst.ref,
            entity_ids=new_device_txns,
            direction=EvidenceDirection.SUPPORTS_FRAUD,
            source_family="device",
            result_hash=burst.receipt.result_hash if burst.receipt else "",
        )

    region = tools.detect_region_anomaly(
        deps.graph, customer_id=customer_id, cutoff=cutoff, window_hours=WINDOW_HOURS_CARD
    )
    state.observations["region_anomaly"] = region.data

    novel_regions = region.data.get("novel_regions") or []
    if novel_regions:
        concurrent = int(region.data.get("concurrent_home_region_count", 0))
        state.add_evidence(
            claim=(
                f"In-person activity appeared in {len(novel_regions)} billing region(s) "
                f"with no prior history ({', '.join(map(str, novel_regions[:3]))}), "
                + (
                    f"while {concurrent} transaction(s) continued in a known region"
                    if concurrent
                    else "with no concurrent activity in a known region"
                )
            ),
            source=EvidenceSource.GRAPH,
            ref=region.ref,
            entity_ids=[customer_id],
            direction=(
                EvidenceDirection.SUPPORTS_FRAUD if concurrent else EvidenceDirection.CONTEXT
            ),
            source_family="geography",
            result_hash=region.receipt.result_hash if region.receipt else "",
        )

    takeover = tools.detect_account_takeover(
        deps.graph, customer_id=customer_id, cutoff=cutoff, window_hours=WINDOW_HOURS_CARD
    )
    state.observations["account_takeover"] = takeover.data

    # --- devices and the ring they may belong to --------------------------
    devices = tools.find_device_connections(
        deps.graph, card_id=card_id, cutoff=cutoff, window_hours=WINDOW_HOURS_RING
    )
    state.observations["devices"] = devices.data

    device_rows = devices.data.get("devices") or []
    state.connected_device_ids = [row["device_id"] for row in device_rows]
    # `connected_device_profiles` means, per the answer contract, "device
    # profiles linking this case to other cards". A profile used only by this
    # cardholder links nothing, and a generic configuration links everyone;
    # neither belongs here. `_collect_shared_origin` fills this with the
    # profile that actually connected something.
    state.connected_device_profiles = []

    _collect_shared_origin(state, deps, device_rows, cutoff, card_id)

    state.tool_calls = deps.graph.call_log.count - state.tool_calls_at_start
    state.log(
        "collect_evidence",
        "evidence_added",
        f"{len(state.evidence)} evidence items from {state.tool_calls} graph calls",
    )
    return state


def _collect_shared_origin(
    state: CaseState,
    deps: InvestigationDeps,
    device_rows: list[dict[str, Any]],
    cutoff: datetime,
    card_id: str,
) -> None:
    """Follow an identifying device outward to other cards.

    Only a profile specific enough to name a device is expanded. Picking the
    widest-reaching profile outright would reliably pick the most generic one
    -- in this data the top profiles are `unknown | unknown | unknown |
    unknown` and `Windows | Windows 10 | chrome 63.0 | 1920x1080`, shared by
    over a thousand unrelated customers each. Connecting cardholders through
    those would be guilt by association, and under policy 3a the connection
    is a filing predicate.
    """
    if not device_rows:
        state.observations["shared_origin"] = {}
        return

    selected = select_linking_device(device_rows)
    if selected is None:
        state.observations["shared_origin"] = {}
        # Record why no link was drawn: an absent connection is a finding the
        # analyst should be able to see, not a silent gap.
        rejected = [
            assess_device(
                row.get("device_id", ""),
                row.get("readable", "") or row.get("device_id", ""),
                int(row.get("customer_fanout", 0) or 0),
            )
            for row in device_rows
        ]
        shared = [item for item in rejected if item.customer_fanout >= 2]
        if shared:
            worst = max(shared, key=lambda item: item.customer_fanout)
            state.add_evidence(
                claim=(
                    f"No cardholder connection was drawn from device profile "
                    f"'{worst.readable}': {worst.reason}"
                ),
                source=EvidenceSource.GRAPH,
                ref="derived:device_specificity",
                entity_ids=[],
                direction=EvidenceDirection.CONTEXT,
                source_family="network",
            )
        return

    ring = tools.find_connected_accounts(
        deps.graph,
        origin_kind="device",
        origin_id=selected.device_id,
        cutoff=cutoff,
        exclude_card_id=card_id,
        window_hours=WINDOW_HOURS_RING,
    )
    state.observations["shared_origin"] = ring.data
    state.connected_card_ids = list(ring.data.get("connected_cards") or [])
    if state.connected_card_ids:
        state.connected_device_profiles = [selected.readable]

    prior_fraud = ring.data.get("prior_fraud_cases") or []
    # Cases and cards are different things: several closed cases can concern
    # one card, so counting cases here would overstate the reach.
    cards_with_fraud = ring.data.get("cards_with_prior_fraud") or []
    readable = selected.readable
    claim = (
        f"Device profile '{readable}' was used by "
        f"{len(state.connected_card_ids)} other card(s) within the window"
    )
    if prior_fraud:
        claim += (
            f", of which {len(cards_with_fraud)} already carry confirmed fraud "
            f"across {len(prior_fraud)} closed case(s)"
        )

    state.add_evidence(
        claim=claim,
        source=EvidenceSource.GRAPH,
        ref=ring.ref,
        entity_ids=state.connected_card_ids + list(prior_fraud),
        direction=EvidenceDirection.SUPPORTS_FRAUD,
        source_family="network",
        result_hash=ring.receipt.result_hash if ring.receipt else "",
    )


# ---------------------------------------------------------------------------
# 4. Counter-evidence
# ---------------------------------------------------------------------------


def seek_counter_evidence(state: CaseState, deps: InvestigationDeps) -> CaseState:
    """Actively test the leading hypothesis.

    Mandatory before a fraud conclusion. Half the benchmark cases are
    legitimate, so an agent that never looks for the innocent explanation
    will be confidently wrong about half of them.
    """
    baseline = state.baseline
    window = state.observations.get("window", {})
    burst = state.observations.get("cnp_burst", {})
    region = state.observations.get("region_anomaly", {})

    # Is the amount actually unusual for this cardholder?
    anchor_amount = abs(float(state.anchor.get("amount", 0) or 0))
    mean = float(baseline.get("mean_amount", 0) or 0)
    std = float(baseline.get("std_amount", 0) or 0)
    if mean > 0 and anchor_amount > 0:
        if std > 0 and abs(anchor_amount - mean) <= 2 * std:
            state.add_evidence(
                claim=(
                    f"The flagged amount ${anchor_amount:,.2f} is within two standard "
                    f"deviations of the cardholder's ${mean:,.2f} average, so the amount "
                    "alone is not unusual for this account"
                ),
                source=EvidenceSource.GRAPH,
                ref="derived:baseline_comparison",
                entity_ids=[state.trigger.flagged_txn_id],
                direction=EvidenceDirection.SUPPORTS_LEGITIMATE,
                source_family="behaviour",
            )

    # Is the device actually known to this account?
    #
    # The baseline window ends at the cutoff, so it can contain the episode's
    # own earlier transactions. Left unguarded, a compromise that ran for a
    # few hours would "establish" its own device as familiar and then cite
    # that as evidence of innocence. The identity record's New/Found marking
    # (id_15) is the bank's own judgement for this account and settles it, so
    # this check only speaks when the record does not mark the device new.
    known_devices = set(baseline.get("known_devices") or [])
    anchor_device = state.anchor.get("device_profile_id") or ""
    anchor_marked_new = bool(state.anchor.get("device_is_new"))
    if anchor_device and anchor_device in known_devices and not anchor_marked_new:
        state.add_evidence(
            claim=(
                "The device profile used by the flagged transaction already appears in "
                "this cardholder's "
                "history before the cutoff, so it is not new to the account"
            ),
            source=EvidenceSource.GRAPH,
            ref="derived:baseline_device_match",
            # The flagged transaction carries the claim; a derived device ID is
            # not a supplied dataset ID and must not appear in entity_ids.
            entity_ids=[state.trigger.flagged_txn_id],
            direction=EvidenceDirection.SUPPORTS_LEGITIMATE,
            source_family="device",
        )

    # R7: is the disputed charge one the cardholder already pays regularly?
    #
    # Only worth asking when they actually disputed it. A subscription a
    # customer has forgotten looks exactly like an unauthorized charge until
    # their own history is checked, and the policy forbids blocking it.
    if state.trigger.customer_disputed and state.anchor:
        recurring = tools.detect_recurring_charge(
            deps.graph,
            card_id=state.trigger.card_id,
            amount=abs(float(state.anchor.get("amount", 0) or 0)),
            product_cd=str(state.anchor.get("product_cd", "")),
            cutoff=state.trigger.cutoff,
            lookback_days=BASELINE_LOOKBACK_DAYS,
            amount_tolerance=RECURRING_AMOUNT_TOLERANCE_USD,
        )
        state.observations["recurring_charge"] = recurring.data
        match_count = int(recurring.data.get("match_count", 0))
        if match_count >= MIN_RECURRING_MATCHES:
            state.observations["matches_recurring_pattern"] = True
            prior_ids = [
                row["txn_id"] for row in recurring.data.get("prior_matching_charges") or []
            ]
            state.add_evidence(
                claim=(
                    f"The disputed charge matches {match_count} earlier charge(s) on this "
                    f"card for the same product at the same amount, so it fits the "
                    "cardholder's own recurring pattern"
                ),
                source=EvidenceSource.GRAPH,
                ref=recurring.ref,
                entity_ids=prior_ids[:10],
                direction=EvidenceDirection.SUPPORTS_LEGITIMATE,
                source_family="behaviour",
                result_hash=recurring.receipt.result_hash if recurring.receipt else "",
            )

    # Travel rather than a clone: a novel region with no concurrent home use.
    novel = region.get("novel_regions") or []
    if novel and int(region.get("concurrent_home_region_count", 0)) == 0:
        state.add_evidence(
            claim=(
                "Activity in the novel region is not accompanied by concurrent activity "
                "in a known region, which is consistent with the cardholder travelling "
                "rather than a cloned card"
            ),
            source=EvidenceSource.GRAPH,
            ref="derived:travel_consistency",
            entity_ids=[state.trigger.customer_id],
            direction=EvidenceDirection.SUPPORTS_LEGITIMATE,
            source_family="geography",
        )

    # A single online purchase is ambiguous by the README's own warning.
    if int(burst.get("online_count", 0)) == 1 and not state.connected_card_ids:
        state.add_evidence(
            claim=(
                "Only one online transaction appears in the window and no other card "
                "shares its origin, so the activity does not form a burst"
            ),
            source=EvidenceSource.GRAPH,
            ref="derived:isolated_transaction",
            entity_ids=[state.trigger.flagged_txn_id],
            direction=EvidenceDirection.SUPPORTS_LEGITIMATE,
            source_family="behaviour",
        )

    # Normal activity continuing after the flag argues against a compromise.
    if int(window.get("in_person_count", 0)) > 0 and int(burst.get("online_count", 0)) > 0:
        state.observations["mixed_channel_continues"] = True

    state.log(
        "seek_counter_evidence",
        "counter_evidence_gathered",
        f"{len(state.counter_evidence())} item(s) argue against fraud",
    )
    return state


# ---------------------------------------------------------------------------
# 5. Memory
# ---------------------------------------------------------------------------


def retrieve_case_memory(state: CaseState, deps: InvestigationDeps) -> CaseState:
    """Retrieve comparable closed cases, time-gated to the cutoff."""
    leading = state.hypotheses[0].pattern.value if state.hypotheses else ""

    similar = tools.find_similar_cases(
        deps.graph,
        customer_id=state.trigger.customer_id,
        card_id=state.trigger.card_id,
        cutoff=state.trigger.cutoff,
        device_ids=state.connected_device_ids,
        pattern_hint=leading,
    )

    for row in similar.data.get("similar_cases") or []:
        state.prior_cases.append(
            PriorCase(
                case_id=row.get("case_id", ""),
                outcome=row.get("outcome", ""),
                pattern=row.get("pattern", ""),
                customer_id=row.get("customer_id", ""),
                card_id=row.get("card_id", ""),
                exposure_usd=float(row.get("exposure_usd", 0) or 0),
                structural_score=float(row.get("structural_score", 0) or 0),
                link_reason=row.get("link_reason", ""),
                analyst_notes=row.get("analyst_notes", "") or "",
            )
        )

    if state.prior_cases:
        confirmed = [case for case in state.prior_cases if case.outcome == "confirmed_fraud"]
        cleared = [case for case in state.prior_cases if case.outcome == "cleared"]
        state.add_evidence(
            claim=(
                f"{len(state.prior_cases)} comparable closed case(s) were retrieved "
                f"({len(confirmed)} confirmed fraud, {len(cleared)} cleared); "
                f"closest link: {state.prior_cases[0].link_reason}"
            ),
            source=EvidenceSource.GRAPH,
            ref=similar.ref,
            entity_ids=[case.case_id for case in state.prior_cases],
            direction=(
                EvidenceDirection.SUPPORTS_FRAUD
                if len(confirmed) > len(cleared)
                else EvidenceDirection.CONTEXT
            ),
            source_family="history",
            result_hash=similar.receipt.result_hash if similar.receipt else "",
        )

    state.tool_calls = deps.graph.call_log.count - state.tool_calls_at_start
    state.log(
        "retrieve_case_memory",
        "memory_retrieved",
        f"{len(state.prior_cases)} prior case(s)",
    )
    return state


# ---------------------------------------------------------------------------
# 6. Hypotheses
# ---------------------------------------------------------------------------


def form_hypotheses(state: CaseState, deps: InvestigationDeps) -> CaseState:
    """Score every documented pattern and keep the alternatives alive."""
    result = assess(
        observations=state.observations,
        baseline=state.baseline,
        stage="hypotheses",
        trigger_risk_score=state.trigger.risk_score,
    )

    state.hypotheses = [
        Hypothesis(
            pattern=score.pattern,
            score=round(score.score, 2),
            rationale=score.rationale,
        )
        for score in result.pattern_scores
    ]
    # `none` stays on the table explicitly: about half these alerts are
    # legitimate, and the agent must be able to land there.
    state.hypotheses.append(
        Hypothesis(
            pattern=Pattern.NONE,
            score=round(max(0.0, 1.0 - result.fraud_probability), 2),
            rationale="No fraud: the activity is consistent with the cardholder's own use",
        )
    )
    state.hypotheses.sort(key=lambda item: item.score, reverse=True)

    state.log(
        "form_hypotheses",
        "hypotheses_formed",
        ", ".join(f"{h.pattern.value}={h.score:.2f}" for h in state.hypotheses[:3]),
    )
    return state


# ---------------------------------------------------------------------------
# 7. Assess
# ---------------------------------------------------------------------------


def _latest_response(state: CaseState) -> RequestRecord | None:
    return state.requests[-1] if state.requests else None


def assess_evidence(state: CaseState, deps: InvestigationDeps, *, stage: str) -> CaseState:
    """Produce a probability, verdict, pattern, and uncertainty reading."""
    response = _latest_response(state)
    matches_recurring = bool(state.observations.get("matches_recurring_pattern"))

    result = assess(
        observations=state.observations,
        baseline=state.baseline,
        stage=stage,
        trigger_risk_score=state.trigger.risk_score,
        customer_denied=bool(response and response.customer_denied),
        customer_confirmed=bool(response and response.customer_confirmed),
        matches_recurring_pattern=matches_recurring,
        prior_case_support=sum(
            1 for case in state.prior_cases if case.outcome == "confirmed_fraud"
        ),
    )

    # A customer-report trigger is itself the cardholder disputing the charge,
    # so a legitimate verdict needs a positive reason rather than an absence
    # of suspicion. A match against their own recurring pattern is exactly
    # that reason, and is the situation R7 exists for: the charge really is
    # legitimate, and the policy forbids blocking it. Without such an
    # explanation the case stays uncertain rather than being closed.
    if (
        state.trigger.customer_disputed
        and result.verdict is Verdict.LEGITIMATE
        and not matches_recurring
    ):
        result.verdict = Verdict.UNCERTAIN
        result.rationale += (
            " The cardholder has disputed the charge, so the case is not closed as "
            "legitimate without confirming it against their own history."
        )

    state.assessments.append(
        Assessment(
            stage=stage,
            verdict=result.verdict,
            fraud_probability=result.fraud_probability,
            pattern=result.pattern,
            pattern_description=result.pattern_description,
            confidence=result.confidence,
            uncertainty=result.uncertainty,
            independent_signal_count=result.independent_signal_count,
            conflicting_evidence=result.conflicting_evidence,
            rationale=result.rationale,
            trigger_risk_score=state.trigger.risk_score,
        )
    )

    _compute_scope(state, result.verdict)

    state.log(
        "assess",
        "risk_updated",
        f"{stage}: p={result.fraud_probability:.2f} verdict={result.verdict.value} "
        f"pattern={result.pattern.value}",
    )
    return state


def _compute_scope(state: CaseState, verdict: Verdict) -> None:
    """Identify the affected transactions and sum the exposure.

    Exposure is the sum of absolute amounts of the episode, including the
    flagged transaction (policy 4). A legitimate verdict has no episode at
    all, so both are emptied.
    """
    if verdict is Verdict.LEGITIMATE:
        state.affected_txn_ids = []
        state.first_suspicious_txn_id = ""
        state.exposure_usd = 0.0
        return

    testing = state.observations.get("card_testing", {})
    burst = state.observations.get("cnp_burst", {})

    candidates: list[str] = []
    # The testing sequence is only part of the episode when the sequence was
    # actually observed; otherwise its transaction IDs are ordinary activity.
    if testing.get("within_one_hour"):
        candidates.extend(testing.get("small_txn_ids") or [])
        candidates.extend(testing.get("larger_txn_ids") or [])
    for row in burst.get("online_transactions") or []:
        candidates.append(row["txn_id"])
    if state.trigger.flagged_txn_id:
        candidates.append(state.trigger.flagged_txn_id)

    # Preserve first-seen order while removing duplicates.
    seen: set[str] = set()
    ordered = [t for t in candidates if not (t in seen or seen.add(t))]

    amounts = _amounts_for(state, ordered)
    resolved = [t for t in ordered if t in amounts]
    resolved = _bound_episode(state, _order_by_time(state, resolved))

    state.affected_txn_ids = resolved
    state.exposure_usd = round(sum(abs(amounts[t]) for t in resolved), 2)

    if state.affected_txn_ids:
        state.first_suspicious_txn_id = state.affected_txn_ids[0]


def _bound_episode(state: CaseState, ordered: list[str]) -> list[str]:
    """Keep the episode contiguous around the flagged transaction.

    A high-volume cardholder can make dozens of online transactions inside the
    burst window; sweeping all of them into one fraud episode inflates both
    the exposure and the SAR total, and asserts a scope the evidence does not
    support. The episode is therefore limited to activity within
    `EPISODE_MAX_HOURS` of the flagged transaction, which is the span the
    README describes for a card-not-present burst.
    """
    anchor_id = state.trigger.flagged_txn_id
    times = _timestamps_for(state, ordered + [anchor_id])
    anchor_ts = times.get(anchor_id)
    if anchor_ts is None:
        return ordered[:EPISODE_MAX_TRANSACTIONS]

    within = [
        txn_id
        for txn_id in ordered
        if txn_id in times
        and abs((times[txn_id] - anchor_ts).total_seconds()) <= EPISODE_MAX_HOURS * 3600
    ]
    if anchor_id not in within and anchor_id in times:
        within.append(anchor_id)
        within = _order_by_time(state, within)

    return within[:EPISODE_MAX_TRANSACTIONS]


def _timestamps_for(state: CaseState, txn_ids: list[str]) -> dict[str, datetime]:
    """Parsed timestamps for transactions already retrieved."""
    raw: dict[str, str] = {}
    for key, field_name in (
        ("window", "window"),
        ("cnp_burst", "online_transactions"),
        ("card_testing", "sequence"),
    ):
        for row in state.observations.get(key, {}).get(field_name) or []:
            raw[row["txn_id"]] = str(row.get("ts", ""))
    if state.anchor:
        raw.setdefault(str(state.anchor.get("txn_id")), str(state.anchor.get("ts", "")))

    parsed: dict[str, datetime] = {}
    for txn_id in txn_ids:
        value = raw.get(txn_id)
        if not value:
            continue
        try:
            parsed[txn_id] = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return parsed


def _amounts_for(state: CaseState, txn_ids: list[str]) -> dict[str, float]:
    """Amounts for candidate transactions, from evidence already retrieved."""
    amounts: dict[str, float] = {}
    for row in state.observations.get("window", {}).get("window") or []:
        amounts[row["txn_id"]] = float(row.get("amount", 0) or 0)
    for row in state.observations.get("cnp_burst", {}).get("online_transactions") or []:
        amounts[row["txn_id"]] = float(row.get("amount", 0) or 0)
    for row in state.observations.get("card_testing", {}).get("sequence") or []:
        amounts[row["txn_id"]] = float(row.get("amount", 0) or 0)
    if state.anchor:
        amounts[str(state.anchor.get("txn_id"))] = float(state.anchor.get("amount", 0) or 0)
    return {t: amounts[t] for t in txn_ids if t in amounts}


def _order_by_time(state: CaseState, txn_ids: list[str]) -> list[str]:
    times: dict[str, str] = {}
    for key in ("window", "cnp_burst", "card_testing"):
        block = state.observations.get(key, {})
        for field_name in ("window", "online_transactions", "sequence"):
            for row in block.get(field_name) or []:
                times[row["txn_id"]] = str(row.get("ts", ""))
    if state.anchor:
        times.setdefault(str(state.anchor.get("txn_id")), str(state.anchor.get("ts", "")))
    return sorted(txn_ids, key=lambda t: (times.get(t, ""), t))


# ---------------------------------------------------------------------------
# 8. Policy
# ---------------------------------------------------------------------------


def build_policy_facts(state: CaseState) -> PolicyFacts:
    """Translate investigation state into the policy engine's input.

    Everything here is an observation. The engine, not this function, decides
    what follows from them.
    """
    current = state.current
    assert current is not None, "policy facts require an assessment"

    testing_data = state.observations.get("card_testing", {})
    small_count = int(testing_data.get("small_online_count", 0))
    larger_ids = testing_data.get("larger_txn_ids") or []
    cleared_amount = 0.0
    if larger_ids:
        amounts = _amounts_for(state, list(larger_ids))
        cleared_amount = max((abs(v) for v in amounts.values()), default=0.0)

    ring = state.observations.get("shared_origin", {})
    connected = list(ring.get("connected_cards") or [])
    prior_fraud = list(ring.get("prior_fraud_cases") or [])
    devices = state.observations.get("devices", {}).get("devices") or []
    widest = max(devices, key=lambda row: int(row.get("customer_fanout", 0)), default=None)

    response = _latest_response(state)

    return PolicyFacts(
        case_id=state.trigger.case_id,
        verdict=current.verdict,
        fraud_probability=current.fraud_probability,
        pattern=current.pattern,
        exposure_usd=state.exposure_usd,
        independent_signal_count=current.independent_signal_count,
        conflicting_evidence=current.conflicting_evidence,
        evidence_requested=state.evidence_requested,
        customer_disputed=state.trigger.customer_disputed,
        matches_recurring_legitimate_pattern=bool(
            state.observations.get("matches_recurring_pattern")
        ),
        has_pending_authorization=bool(state.affected_txn_ids),
        customer=CustomerResponse(
            asked=response is not None,
            denied=bool(response and response.customer_denied),
            confirmed=bool(response and response.customer_confirmed),
            no_reply_24h=bool(response and response.no_reply),
        ),
        card_testing=CardTestingFacts(
            small_auth_count=small_count,
            # Observed from the transaction timestamps, not inferred from
            # the count: R5's threshold is a one-hour span.
            within_one_hour=bool(testing_data.get("within_one_hour")),
            followed_by_larger_purchase=bool(larger_ids),
            cleared_purchase_amount_usd=cleared_amount,
        ),
        shared_origin=SharedOriginFacts(
            cards_sharing_origin=len(connected) + 1 if connected else 0,
            shared_element=(widest or {}).get("readable", "") if connected else "",
            shared_element_kind="device profile" if connected else "",
            within_one_window=bool(connected),
            connected_card_ids=connected,
        ),
        connected_to_other_card_fraud=bool(prior_fraud),
        connected_to_shared_device_profile=bool(connected),
        coordinated_or_undocumented_abuse=(
            current.pattern is Pattern.UNDOCUMENTED and bool(connected)
        ),
        customer_cards_with_confirmed_fraud=_cards_with_confirmed_fraud(state),
        # Nothing in this dataset confirms a credential compromise, so the
        # second R10 door stays shut rather than being assumed open.
        credentials_confirmed_compromised=False,
    )


def _cards_with_confirmed_fraud(state: CaseState) -> int:
    """How many of this customer's own cards show confirmed fraud.

    R10 opens only at two or more. Counted from the bank's closed history for
    this customer, plus the card under investigation when the current verdict
    is fraud, since that card is itself one of the two.
    """
    cards = {
        case.card_id
        for case in state.prior_cases
        if case.outcome == "confirmed_fraud"
        and case.customer_id == state.trigger.customer_id
        and case.card_id
    }
    current = state.current
    if current is not None and current.verdict is Verdict.FRAUD:
        cards.add(state.trigger.card_id)
    return len(cards)


def initial_policy_decision(state: CaseState, deps: InvestigationDeps) -> CaseState:
    """Run the policy engine on the pre-request evidence."""
    facts = build_policy_facts(state)
    decision = decide(facts)

    state.initial_actions = list(decision.actions)
    state.triggered_rules = list(decision.triggered_rules)
    state.barred_actions = [
        f"{item.action.value} ({item.forbidden_by})" for item in decision.barred
    ]
    state.sar_reason = decision.report_reason

    state.log(
        "initial_policy_decision",
        "action_recommended",
        ", ".join(f"{a.action.value}[{a.route.value}]" for a in state.initial_actions),
    )
    return state


# ---------------------------------------------------------------------------
# 9. Value of information
# ---------------------------------------------------------------------------


def _decision_signature(actions: list[Any]) -> tuple[tuple[str, str], ...]:
    return tuple((item.action.value, item.route.value) for item in actions)


def value_of_information(state: CaseState, deps: InvestigationDeps) -> tuple[CaseState, bool]:
    """Decide whether any request could actually change the decision.

    Policy 5 permits three requests without approval, but asking has a cost to
    the customer and to latency. A request is only worth making if at least
    one possible response would produce a different action list, so each
    candidate response is previewed through assessment and policy first. This
    is side-effect free and does not consume the request.
    """
    current = state.current
    assert current is not None

    settled, stop_reason = should_stop(_as_result(current), response_settled=bool(state.requests))
    if settled:
        state.stop_reason = stop_reason
        state.log("value_of_information", "stop_condition_met", stop_reason)
        return state, False

    if state.requests:
        # Budget: one simulated request unless policy proves a second is needed.
        state.log("value_of_information", "request_budget_exhausted", "one request already made")
        return state, False

    baseline_signature = _decision_signature(state.initial_actions)
    context = _simulation_context(state, request_no=1)

    best_type: EvidenceRequestType | None = None
    best_reason = ""
    for request_type in (
        EvidenceRequestType.CUSTOMER_VALIDATION,
        EvidenceRequestType.STEP_UP_AUTH,
        EvidenceRequestType.ANALYST_INFO,
    ):
        for candidate in preview_all_responses(request_type, context):
            preview = _preview_decision(state, candidate)
            if _decision_signature(preview) != baseline_signature:
                best_type = request_type
                best_reason = (
                    f"A {request_type.value} response could change the recommendation "
                    f"(for example: {candidate.assumed_response})"
                )
                break
        if best_type:
            break

    if best_type is None:
        state.stop_reason = (
            "No available evidence request would change the recommended actions, so "
            "further investigation is unlikely to change the decision."
        )
        state.log("value_of_information", "request_skipped", state.stop_reason)
        return state, False

    state.observations["planned_request_type"] = best_type.value
    state.observations["planned_request_reason"] = best_reason
    state.log("value_of_information", "evidence_request_planned", best_reason)
    return state, True


def _as_result(assessment: Assessment) -> Any:
    """Adapt a stored Assessment to the shape `should_stop` expects."""

    @dataclass
    class _R:
        fraud_probability: float
        independent_signal_count: int

    return _R(assessment.fraud_probability, assessment.independent_signal_count)


def _simulation_context(state: CaseState, *, request_no: int) -> SimulationContext:
    testing = state.observations.get("card_testing", {})
    ring = state.observations.get("shared_origin", {})
    burst = state.observations.get("cnp_burst", {})
    region = state.observations.get("region_anomaly", {})

    return SimulationContext(
        case_id=state.trigger.case_id,
        trigger_type=state.trigger.trigger_type,
        request_no=request_no,
        device_is_new=int(burst.get("new_device_count", 0)) > 0,
        shared_origin_cards=len(ring.get("connected_cards") or []),
        testing_sequence_observed=(
            int(testing.get("small_online_count", 0)) >= 3 and bool(testing.get("larger_txn_ids"))
        ),
        novel_region=bool(region.get("novel_regions")),
        matches_recurring_pattern=bool(state.observations.get("matches_recurring_pattern")),
        amount_usd=abs(float(state.anchor.get("amount", 0) or 0)),
    )


def _preview_decision(state: CaseState, candidate: Any) -> list[Any]:
    """Run assessment and policy for a hypothetical response, without saving it."""
    result = assess(
        observations=state.observations,
        baseline=state.baseline,
        stage="preview",
        trigger_risk_score=state.trigger.risk_score,
        customer_denied=candidate.customer_denied,
        customer_confirmed=candidate.customer_confirmed,
        matches_recurring_pattern=bool(state.observations.get("matches_recurring_pattern")),
        prior_case_support=sum(
            1 for case in state.prior_cases if case.outcome == "confirmed_fraud"
        ),
    )

    probe = state.model_copy(deep=True)
    probe.assessments.append(
        Assessment(
            stage="preview",
            verdict=result.verdict,
            fraud_probability=result.fraud_probability,
            pattern=result.pattern,
            confidence=result.confidence,
            uncertainty=result.uncertainty,
            independent_signal_count=result.independent_signal_count,
            conflicting_evidence=result.conflicting_evidence,
            rationale=result.rationale,
        )
    )
    probe.requests.append(
        RequestRecord(
            request_no=1,
            request_type=candidate.request_type,
            asked_after_step=probe.step,
            reason="preview",
            assumed_response=candidate.assumed_response,
            customer_denied=candidate.customer_denied,
            customer_confirmed=candidate.customer_confirmed,
            no_reply=candidate.no_reply,
        )
    )
    _compute_scope(probe, result.verdict)
    return decide(build_policy_facts(probe)).actions


# ---------------------------------------------------------------------------
# 10. Request evidence
# ---------------------------------------------------------------------------


def request_evidence(state: CaseState, deps: InvestigationDeps) -> CaseState:
    """Issue the chosen request and record the assumed response."""
    planned = state.observations.get("planned_request_type")
    request_type = (
        EvidenceRequestType(planned) if planned else (EvidenceRequestType.CUSTOMER_VALIDATION)
    )
    request_no = len(state.requests) + 1

    context = _simulation_context(state, request_no=request_no)
    response = simulate(request_type, context)

    state.requests.append(
        RequestRecord(
            request_no=request_no,
            request_type=request_type,
            asked_after_step=state.step,
            reason=str(state.observations.get("planned_request_reason", "")),
            assumed_response=response.assumed_response,
            simulated=True,
            simulator_version=response.simulator_version,
            customer_denied=response.customer_denied,
            customer_confirmed=response.customer_confirmed,
            no_reply=response.no_reply,
        )
    )

    state.add_evidence(
        claim=response.assumed_response,
        source=EvidenceSource.CUSTOMER,
        ref=f"evidence_request:{request_no}",
        entity_ids=[],
        direction=(
            EvidenceDirection.SUPPORTS_FRAUD
            if response.customer_denied
            else (
                EvidenceDirection.SUPPORTS_LEGITIMATE
                if response.customer_confirmed
                else EvidenceDirection.CONTEXT
            )
        ),
        source_family="customer",
    )

    state.log(
        "request_evidence",
        "evidence_requested",
        f"{request_type.value}: {response.assumed_response[:80]}",
    )
    return state


# ---------------------------------------------------------------------------
# 11. Final policy decision
# ---------------------------------------------------------------------------


def final_policy_decision(state: CaseState, deps: InvestigationDeps) -> CaseState:
    """Re-run policy on the post-response evidence and record what changed."""
    facts = build_policy_facts(state)
    decision = decide(facts)

    state.final_actions = list(decision.actions)
    state.triggered_rules = list(decision.triggered_rules)
    state.barred_actions = [
        f"{item.action.value} ({item.forbidden_by})" for item in decision.barred
    ]
    state.sar_file = decision.requires_report
    state.sar_reason = decision.report_reason or state.sar_reason

    if not state.requests:
        # No request means the two recommendations must be identical.
        state.final_actions = list(state.initial_actions)
        state.what_changed = "nothing"
    else:
        state.what_changed = _describe_change(state)

    # Only `auto` actions may be carried out by the agent.
    state.executed_actions = [
        item.action for item in state.final_actions if item.route is Route.AUTO
    ]

    state.log(
        "final_policy_decision",
        "action_recommended",
        ", ".join(f"{a.action.value}[{a.route.value}]" for a in state.final_actions),
    )
    for item in state.final_actions:
        if item.route is not Route.AUTO:
            state.log(
                "final_policy_decision",
                "approval_requested",
                f"{item.action.value} requires {item.route.value} approval",
            )
    return state


def _describe_change(state: CaseState) -> str:
    """One or two sentences on why the final actions differ from the initial."""
    before = {item.action for item in state.initial_actions}
    after = {item.action for item in state.final_actions}
    added = sorted(action.value for action in after - before)
    removed = sorted(action.value for action in before - after)

    response = _latest_response(state)
    first = state.assessments[0].fraud_probability if state.assessments else 0.0
    last = state.current.fraud_probability if state.current else 0.0

    if not added and not removed:
        return (
            f"The assumed response did not change the recommended actions; "
            f"probability moved from {first:.2f} to {last:.2f}."
        )

    parts: list[str] = []
    if response:
        if response.customer_denied:
            parts.append("The cardholder denied the transaction")
        elif response.customer_confirmed:
            parts.append("The cardholder confirmed the transaction")
        elif response.no_reply:
            parts.append("The cardholder did not reply within 24 hours")
        else:
            parts.append("The analyst supplied additional context")

    parts.append(f"moving probability from {first:.2f} to {last:.2f}")
    sentence = ", ".join(parts) + "."
    if added:
        sentence += f" Added: {', '.join(added)}."
    if removed:
        sentence += f" Withdrawn: {', '.join(removed)}."
    return sentence
