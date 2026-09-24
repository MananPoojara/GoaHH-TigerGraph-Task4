"""Pattern scoring, probability, and uncertainty.

This is a versioned, deterministic rubric over observations the graph
returned. It exists rather than a model call because a probability that is
scored for calibration must be reproducible: the same evidence has to yield
the same number on every run.

Two rules from the README shape the whole module:

  * "The risk_score on the flagged transaction is an input, not an answer."
    It contributes a small, bounded amount and can never by itself carry a
    case past the action thresholds.
  * "Half the cases are legitimate. Many look suspicious. An agent that
    blocks everything scores badly." Counter-evidence therefore subtracts,
    and an absent baseline lowers confidence rather than raising suspicion.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from fraudlens_contracts import Pattern, UncertaintyType, Verdict

logger = logging.getLogger(__name__)

RUBRIC_VERSION = "1.0"

# Probability bands from the architecture notes. The policy rules take
# precedence over these; they only set the default posture.
HIGH_CONFIDENCE_FRAUD = 0.85
STRONG_SUSPICION = 0.70
MATERIAL_UNCERTAINTY = 0.30
LIKELY_LEGITIMATE = 0.15

# The supplied model score is capped at this contribution. It is a reason to
# look, never enough to decide.
MAX_RISK_SCORE_CONTRIBUTION = 0.10


@dataclass
class Signal:
    """One scored observation, with the evidence family it belongs to."""

    name: str
    weight: float
    family: str
    detail: str = ""
    supports_fraud: bool = True


@dataclass
class PatternScore:
    pattern: Pattern
    score: float
    rationale: str
    signals: list[Signal] = field(default_factory=list)


@dataclass
class AssessmentResult:
    """The full output of one assessment pass."""

    verdict: Verdict
    fraud_probability: float
    pattern: Pattern
    pattern_description: str
    confidence: float
    uncertainty: UncertaintyType
    independent_signal_count: int
    conflicting_evidence: bool
    rationale: str
    signals: list[Signal] = field(default_factory=list)
    pattern_scores: list[PatternScore] = field(default_factory=list)
    rubric_version: str = RUBRIC_VERSION


def score_card_testing(observations: dict) -> PatternScore:
    """R5's signature: three or more tiny online authorizations, then a
    larger purchase. Confirmed by the sequence itself."""
    testing = observations.get("card_testing", {})
    small_count = int(testing.get("small_online_count", 0))
    larger = testing.get("larger_txn_ids", []) or []

    signals: list[Signal] = []
    score = 0.0
    if small_count >= 3 and larger:
        score = 0.85
        signals.append(
            Signal(
                name="testing_sequence",
                weight=0.45,
                family="sequence",
                detail=(
                    f"{small_count} online authorizations at or under the small-amount "
                    f"threshold, followed by {len(larger)} larger purchase(s)"
                ),
            )
        )
    elif small_count >= 3:
        # The small authorizations alone are suspicious but incomplete: the
        # pattern is defined by what follows them.
        score = 0.35
        signals.append(
            Signal(
                name="small_auth_cluster",
                weight=0.15,
                family="sequence",
                detail=f"{small_count} small online authorizations with no larger purchase yet",
            )
        )

    return PatternScore(
        pattern=Pattern.CARD_TESTING,
        score=score,
        rationale=(
            f"{small_count} small online authorizations; "
            f"{len(larger)} larger purchase(s) in the window"
        ),
        signals=signals,
    )


def score_cnp(observations: dict, baseline: dict) -> tuple[PatternScore, PatternScore]:
    """Card-not-present, with and without a new device.

    The README warns that one unusual online purchase is ambiguous and that a
    new device is not proof, because people buy new phones. Both are scored
    below the action thresholds on their own.
    """
    burst = observations.get("cnp_burst", {})
    online_count = int(burst.get("online_count", 0))
    new_device_count = int(burst.get("new_device_count", 0))
    proxied = int(burst.get("proxied_count", 0))
    burst_amount = float(burst.get("burst_amount", 0.0))

    baseline_online = int(baseline.get("online_count", 0))
    mean_amount = float(baseline.get("mean_amount", 0.0))
    std_amount = float(baseline.get("std_amount", 0.0))

    signals: list[Signal] = []
    score = 0.0

    if online_count >= 2:
        score += 0.30
        signals.append(
            Signal(
                name="online_burst",
                weight=0.20,
                family="behaviour",
                detail=f"{online_count} online transactions inside the window",
            )
        )

    # An amount far outside the customer's own history is meaningful; an
    # amount inside it is not, whatever the risk score says.
    if mean_amount > 0 and std_amount > 0 and burst_amount > 0:
        deviation = (burst_amount / max(online_count, 1) - mean_amount) / std_amount
        if deviation >= 2.0:
            score += 0.20
            signals.append(
                Signal(
                    name="amount_deviation",
                    weight=0.15,
                    family="behaviour",
                    detail=f"average amount is {deviation:.1f} standard deviations above baseline",
                )
            )

    if baseline_online == 0 and online_count > 0:
        score += 0.15
        signals.append(
            Signal(
                name="first_online_activity",
                weight=0.15,
                family="behaviour",
                detail="the cardholder has no prior online activity in the baseline window",
            )
        )

    plain = PatternScore(
        pattern=Pattern.CARD_NOT_PRESENT_FRAUD,
        score=min(score, 0.95),
        rationale=f"{online_count} online transactions totalling ${burst_amount:,.2f}",
        signals=list(signals),
    )

    device_signals = list(signals)
    device_score = score
    if new_device_count > 0:
        device_score += 0.20
        device_signals.append(
            Signal(
                name="new_device",
                weight=0.15,
                family="device",
                detail=f"{new_device_count} transaction(s) from a device marked New for this account",
            )
        )
    if proxied > 0:
        device_score += 0.10
        device_signals.append(
            Signal(
                name="proxy",
                weight=0.10,
                family="device",
                detail=f"{proxied} transaction(s) behind a non-transparent proxy",
            )
        )

    with_device = PatternScore(
        pattern=Pattern.CARD_NOT_PRESENT_NEW_DEVICE,
        score=min(device_score, 0.95) if new_device_count > 0 else 0.0,
        rationale=(
            f"{new_device_count} transaction(s) from a new device, " f"{proxied} behind a proxy"
        ),
        signals=device_signals,
    )
    return plain, with_device


def score_out_of_region(observations: dict) -> PatternScore:
    """Card-present use in a novel region while home activity continues.

    Several days of purchases in one new region is a trip, so a novel region
    with no concurrent home activity scores lower than one with it.
    """
    region = observations.get("region_anomaly", {})
    novel = region.get("novel_regions", []) or []
    in_person = int(region.get("in_person_window_count", 0))
    concurrent_home = int(region.get("concurrent_home_region_count", 0))

    signals: list[Signal] = []
    score = 0.0
    if novel and in_person > 0:
        score = 0.45
        signals.append(
            Signal(
                name="novel_region",
                weight=0.25,
                family="geography",
                detail=f"in-person activity in {len(novel)} region(s) with no prior history",
            )
        )
        if concurrent_home > 0:
            # Being in two places at once is the signal that separates a
            # cloned card from a traveller.
            score = 0.75
            signals.append(
                Signal(
                    name="concurrent_home_activity",
                    weight=0.30,
                    family="geography",
                    detail=(
                        f"{concurrent_home} transaction(s) continued in a known region "
                        "during the same window"
                    ),
                )
            )
        else:
            signals.append(
                Signal(
                    name="no_concurrent_home_activity",
                    weight=0.15,
                    family="geography",
                    detail="no home-region activity during the window, consistent with travel",
                    supports_fraud=False,
                )
            )

    return PatternScore(
        pattern=Pattern.OUT_OF_REGION_USE,
        score=score,
        rationale=(
            f"{len(novel)} novel region(s), {concurrent_home} concurrent home transaction(s)"
        ),
        signals=signals,
    )


def score_account_takeover(observations: dict) -> PatternScore:
    """Mixed-channel activity with device and match anomalies.

    Requires several independent signals, so a single anomaly scores low.
    """
    ato = observations.get("account_takeover", {})
    online = int(ato.get("online_count", 0))
    in_person = int(ato.get("in_person_count", 0))
    new_devices = int(ato.get("new_device_count", 0))
    match_anomalies = int(ato.get("match_anomaly_count", 0))
    cards_active = len(ato.get("cards_active", []) or [])

    signals: list[Signal] = []
    present = 0
    if online > 0 and in_person > 0:
        present += 1
        signals.append(
            Signal(
                name="mixed_channel",
                weight=0.15,
                family="behaviour",
                detail=f"{online} online and {in_person} in-person transactions in the window",
            )
        )
    if new_devices > 0:
        present += 1
        signals.append(
            Signal(
                name="new_device",
                weight=0.15,
                family="device",
                detail=f"{new_devices} transaction(s) from a new device",
            )
        )
    if match_anomalies > 0:
        present += 1
        signals.append(
            Signal(
                name="match_anomaly",
                weight=0.15,
                family="identity",
                detail=f"{match_anomalies} transaction(s) with a match-flag anomaly",
            )
        )
    if cards_active > 1:
        present += 1
        signals.append(
            Signal(
                name="multi_card",
                weight=0.10,
                family="behaviour",
                detail=f"{cards_active} of the customer's cards were active in the window",
            )
        )

    # Deliberately steep: one anomaly is noise, three together is a pattern.
    score = {0: 0.0, 1: 0.20, 2: 0.45, 3: 0.70, 4: 0.80}.get(present, 0.0)
    return PatternScore(
        pattern=Pattern.ACCOUNT_TAKEOVER,
        score=score,
        rationale=f"{present} of four takeover signals present",
        signals=signals,
    )


def score_shared_origin(observations: dict) -> list[Signal]:
    """Signals from other cards reached through a shared origin."""
    ring = observations.get("shared_origin", {})
    connected = ring.get("connected_cards", []) or []
    prior_fraud = ring.get("prior_fraud_cases", []) or []

    signals: list[Signal] = []
    if len(connected) >= 1 and prior_fraud:
        signals.append(
            Signal(
                name="shared_origin_with_prior_fraud",
                weight=0.30,
                family="network",
                detail=(
                    f"{len(connected)} other card(s) share this origin and "
                    f"{len(prior_fraud)} carry confirmed fraud"
                ),
            )
        )
    elif len(connected) >= 2:
        # Proximity alone is context, not proof. It is weighted low and can
        # never carry a case on its own.
        signals.append(
            Signal(
                name="shared_origin",
                weight=0.15,
                family="network",
                detail=f"{len(connected)} other card(s) transacted through this origin",
            )
        )
    return signals


def assess(
    *,
    observations: dict,
    baseline: dict,
    stage: str = "initial",
    trigger_risk_score: float | None = None,
    customer_denied: bool = False,
    customer_confirmed: bool = False,
    matches_recurring_pattern: bool = False,
    prior_case_support: int = 0,
) -> AssessmentResult:
    """Produce a probability, verdict, pattern, and uncertainty reading.

    The customer's own answer dominates when it exists: a denial is direct
    evidence of unauthorized use, and a confirmation settles the question the
    other way. Graph evidence sets the prior; the cardholder settles it.
    """
    testing = score_card_testing(observations)
    cnp_plain, cnp_device = score_cnp(observations, baseline)
    region = score_out_of_region(observations)
    takeover = score_account_takeover(observations)

    pattern_scores = [testing, cnp_device, cnp_plain, region, takeover]
    ranked = sorted(pattern_scores, key=lambda item: item.score, reverse=True)
    leading = ranked[0]

    signals: list[Signal] = list(leading.signals)
    signals.extend(score_shared_origin(observations))

    if prior_case_support > 0:
        signals.append(
            Signal(
                name="prior_case_support",
                weight=0.10,
                family="history",
                detail=f"{prior_case_support} comparable closed case(s) retrieved",
            )
        )

    # The supplied model score contributes, but is capped.
    if trigger_risk_score is not None:
        contribution = min(
            trigger_risk_score * MAX_RISK_SCORE_CONTRIBUTION, MAX_RISK_SCORE_CONTRIBUTION
        )
        signals.append(
            Signal(
                name="model_risk_score",
                weight=contribution,
                family="model_score",
                detail=(
                    f"the bank's model scored the flagged transaction at "
                    f"{trigger_risk_score:.2f}; treated as a reason to look, not a verdict"
                ),
            )
        )

    if matches_recurring_pattern:
        signals.append(
            Signal(
                name="recurring_pattern_match",
                weight=0.40,
                family="behaviour",
                detail="the disputed charge matches the cardholder's own recurring pattern",
                supports_fraud=False,
            )
        )

    supporting = sum(signal.weight for signal in signals if signal.supports_fraud)
    opposing = sum(signal.weight for signal in signals if not signal.supports_fraud)
    probability = max(0.0, min(1.0, supporting - opposing))

    # The cardholder's own answer outranks the graph evidence.
    if customer_denied:
        probability = max(probability, 0.88)
        signals.append(
            Signal(
                name="customer_denial",
                weight=0.0,
                family="customer",
                detail="the cardholder denies making the transaction",
            )
        )
    elif customer_confirmed:
        probability = min(probability, 0.08)
        signals.append(
            Signal(
                name="customer_confirmation",
                weight=0.0,
                family="customer",
                detail="the cardholder confirms making the transaction",
                supports_fraud=False,
            )
        )

    families = {signal.family for signal in signals if signal.supports_fraud and signal.weight > 0}
    if customer_denied:
        families.add("customer")
    independent_signal_count = len(families)

    has_support = any(signal.supports_fraud and signal.weight > 0 for signal in signals)
    has_counter = any(not signal.supports_fraud for signal in signals)
    conflicting = (
        has_support and has_counter and MATERIAL_UNCERTAINTY <= probability < STRONG_SUSPICION
    )

    if probability >= STRONG_SUSPICION:
        verdict = Verdict.FRAUD
    elif probability <= LIKELY_LEGITIMATE:
        verdict = Verdict.LEGITIMATE
    else:
        verdict = Verdict.UNCERTAIN

    # `none` means "no fraud", so it cannot accompany a fraud verdict. When
    # the cardholder denies a charge that matches none of the five documented
    # signatures, the honest label is `undocumented` with a description of
    # what was actually seen -- which is what the README asks for.
    pattern_description = ""
    if verdict is Verdict.LEGITIMATE:
        pattern = Pattern.NONE
    elif leading.score > 0:
        pattern = leading.pattern
    elif verdict is Verdict.FRAUD:
        pattern = Pattern.UNDOCUMENTED
        pattern_description = _describe_undocumented(observations, customer_denied=customer_denied)
    else:
        pattern = Pattern.NONE

    # Uncertainty type drives what the agent does next: missing evidence is
    # worth asking about, conflicting evidence is worth escalating.
    if verdict is Verdict.UNCERTAIN:
        if conflicting and independent_signal_count < 2:
            uncertainty = UncertaintyType.BOTH
        elif conflicting:
            uncertainty = UncertaintyType.CONFLICTING_EVIDENCE
        else:
            uncertainty = UncertaintyType.MISSING_EVIDENCE
    else:
        uncertainty = UncertaintyType.NONE

    # Confidence is about evidence sufficiency, not about the probability
    # being high. A well-evidenced legitimate verdict is highly confident.
    confidence = min(
        1.0,
        0.25 * independent_signal_count + (0.3 if customer_denied or customer_confirmed else 0.0),
    )

    rationale = (
        f"Leading pattern {leading.pattern.value} scored {leading.score:.2f} "
        f"({leading.rationale}). {independent_signal_count} independent evidence "
        f"family/families support the conclusion."
    )

    logger.info(
        "risk_updated stage=%s probability=%.2f verdict=%s pattern=%s families=%d",
        stage,
        probability,
        verdict.value,
        pattern.value,
        independent_signal_count,
    )

    return AssessmentResult(
        verdict=verdict,
        fraud_probability=round(probability, 2),
        pattern=pattern,
        pattern_description=pattern_description,
        confidence=round(confidence, 2),
        uncertainty=uncertainty,
        independent_signal_count=independent_signal_count,
        conflicting_evidence=conflicting,
        rationale=rationale,
        signals=signals,
        pattern_scores=ranked,
    )


def _describe_undocumented(observations: dict, *, customer_denied: bool) -> str:
    """Two or three sentences on abuse that fits none of the five patterns.

    Required whenever `pattern` is `undocumented`. Describes only what the
    graph actually returned, so the description stays evidence-backed rather
    than becoming a guess dressed as a finding.
    """
    burst = observations.get("cnp_burst", {})
    ring = observations.get("shared_origin", {})
    window = observations.get("window", {})

    online = int(burst.get("online_count", 0))
    in_person = int(window.get("in_person_count", 0))
    connected = len(ring.get("connected_cards") or [])

    parts: list[str] = []
    if customer_denied:
        parts.append(
            "The cardholder denies transactions that match none of the five documented "
            "signatures: there is no small-authorization testing sequence, no novel "
            "billing region, and no burst of uncharacteristic online activity."
        )
    else:
        parts.append(
            "The activity does not match any of the five documented patterns: no "
            "testing sequence, no novel region, and no uncharacteristic online burst."
        )

    if online and in_person:
        parts.append(
            f"The disputed activity spans {online} online and {in_person} in-person "
            "transactions without the device or match anomalies that would indicate "
            "account takeover."
        )
    elif online:
        parts.append(
            f"The disputed activity is {online} online transaction(s) that sit within "
            "the cardholder's own amount and product history."
        )
    else:
        parts.append(
            "The disputed activity is card-present and falls inside the cardholder's "
            "established region and amount profile."
        )

    if connected:
        parts.append(
            f"It reaches {connected} other card(s) through a shared origin, which "
            "suggests a coordinated actor rather than an isolated compromise."
        )
    else:
        parts.append(
            "It affects this cardholder alone, so the compromise route is not yet "
            "identified and warrants analyst review."
        )

    return " ".join(parts)


def should_stop(result: AssessmentResult, *, response_settled: bool) -> tuple[bool, str]:
    """Policy 6: when to stop investigating.

    Stopping too early creates risk; continuing past a defensible decision
    wastes time. Both are marked down, so the condition is explicit.
    """
    if response_settled:
        return True, "A verification response settled the authorization question."
    if result.fraud_probability >= HIGH_CONFIDENCE_FRAUD and result.independent_signal_count >= 2:
        return True, (
            f"Fraud probability {result.fraud_probability:.2f} is at or above "
            f"{HIGH_CONFIDENCE_FRAUD:.2f} with {result.independent_signal_count} "
            "independent pieces of evidence."
        )
    if result.fraud_probability <= LIKELY_LEGITIMATE and result.independent_signal_count >= 2:
        return True, (
            f"Fraud probability {result.fraud_probability:.2f} is at or below "
            f"{LIKELY_LEGITIMATE:.2f} with {result.independent_signal_count} "
            "independent pieces of evidence."
        )
    return False, ""
