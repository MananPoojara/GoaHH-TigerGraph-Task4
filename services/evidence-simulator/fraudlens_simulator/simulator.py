"""Seeded simulation of evidence the dataset does not supply.

The README is explicit: "Customer and analyst replies are not provided ...
Simulate them in your own system and state the assumption you made."

Two properties matter, and both are enforced here:

1. **Determinism.** The same case and request always produce the same
   response, derived from a seeded hash of the case ID and request number.
   A rerun of the benchmark must not silently change its answers.

2. **No access to ground truth.** The simulator never sees the closed-case
   outcome, and it never sees the agent's own probability as a way of
   deciding what the customer "really" did. Letting either in would turn the
   benchmark into a self-fulfilling loop: the agent would request evidence,
   the simulator would confirm the agent's hypothesis, and the resulting
   accuracy would measure nothing.

What it may condition on is the *observable* case shape -- the trigger type
and the evidence already gathered -- because a real customer's answer does
correlate with what actually happened to their card. A customer-report
trigger means the cardholder has already said they did not make the charge;
returning a confirmation there would be incoherent, not neutral.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from fraudlens_contracts import EvidenceRequestType, TriggerType

logger = logging.getLogger(__name__)

SIMULATOR_VERSION = "1.0"


@dataclass(frozen=True)
class SimulationContext:
    """The observable case shape the simulator may condition on.

    Deliberately excludes the verdict, the fraud probability, and anything
    derived from the closed-case labels.
    """

    case_id: str
    trigger_type: TriggerType
    request_no: int
    # Observable evidence, not conclusions.
    device_is_new: bool = False
    shared_origin_cards: int = 0
    testing_sequence_observed: bool = False
    novel_region: bool = False
    matches_recurring_pattern: bool = False
    amount_usd: float = 0.0


@dataclass(frozen=True)
class SimulatedResponse:
    """A response, always labelled as assumed rather than verified."""

    request_type: EvidenceRequestType
    assumed_response: str
    simulated: bool = True
    simulator_version: str = SIMULATOR_VERSION
    # Structured reading of the prose, so the policy engine does not have to
    # parse free text to know what the customer said.
    customer_denied: bool = False
    customer_confirmed: bool = False
    no_reply: bool = False

    @property
    def settles_the_question(self) -> bool:
        """Whether this response resolves the authorization question outright."""
        return self.customer_denied or self.customer_confirmed


def _draw(context: SimulationContext) -> float:
    """A stable pseudo-random value in [0, 1) for this case and request.

    Hash-based rather than `random.Random`, so a value depends only on the
    case and request number and not on how many draws happened before it.
    """
    key = f"{context.case_id}|{context.request_no}|{SIMULATOR_VERSION}"
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def _suspicion_weight(context: SimulationContext) -> float:
    """How strongly the *observable* evidence points at unauthorized use.

    This is not the agent's probability; it is a coarse reading of what the
    graph showed, used only to keep simulated replies coherent with the
    scenario rather than uniformly random.
    """
    weight = 0.0
    if context.testing_sequence_observed:
        weight += 0.45
    if context.shared_origin_cards >= 2:
        weight += 0.30
    if context.device_is_new:
        weight += 0.15
    if context.novel_region:
        weight += 0.10
    if context.matches_recurring_pattern:
        # A charge matching the customer's own recurring pattern points the
        # other way; R7 exists for exactly this case.
        weight -= 0.50
    return max(0.0, min(1.0, weight))


def simulate_customer_validation(context: SimulationContext) -> SimulatedResponse:
    """Ask the cardholder whether they made the transaction."""
    # A customer-report trigger means they have already denied it. Anything
    # else would contradict the supplied trigger text.
    if context.trigger_type is TriggerType.CUSTOMER_REPORT:
        return SimulatedResponse(
            request_type=EvidenceRequestType.CUSTOMER_VALIDATION,
            assumed_response=(
                "Customer restates that they did not make this purchase and confirms "
                "they still have the card in their possession."
            ),
            customer_denied=True,
        )

    if context.matches_recurring_pattern:
        return SimulatedResponse(
            request_type=EvidenceRequestType.CUSTOMER_VALIDATION,
            assumed_response=(
                "Customer recognises the charge after being reminded it is their "
                "recurring monthly subscription, and confirms they made it."
            ),
            customer_confirmed=True,
        )

    draw = _draw(context)
    weight = _suspicion_weight(context)

    # A small share of contacts simply go unanswered, which is what R4 is for.
    if draw > 0.90:
        return SimulatedResponse(
            request_type=EvidenceRequestType.CUSTOMER_VALIDATION,
            assumed_response=(
                "No response received from the cardholder within 24 hours of contact."
            ),
            no_reply=True,
        )

    if draw < weight:
        return SimulatedResponse(
            request_type=EvidenceRequestType.CUSTOMER_VALIDATION,
            assumed_response=(
                "Customer states they did not make this purchase and still has the card."
            ),
            customer_denied=True,
        )

    return SimulatedResponse(
        request_type=EvidenceRequestType.CUSTOMER_VALIDATION,
        assumed_response=("Customer confirms they made this purchase and recognises the merchant."),
        customer_confirmed=True,
    )


def simulate_step_up_auth(context: SimulationContext) -> SimulatedResponse:
    """Require a one-time passcode or app confirmation."""
    draw = _draw(context)
    weight = _suspicion_weight(context)

    if draw < weight:
        return SimulatedResponse(
            request_type=EvidenceRequestType.STEP_UP_AUTH,
            assumed_response=(
                "Step-up authentication failed: the one-time passcode was not completed "
                "on the enrolled device, and a further attempt came from the same "
                "unrecognised device."
            ),
            customer_denied=True,
        )

    return SimulatedResponse(
        request_type=EvidenceRequestType.STEP_UP_AUTH,
        assumed_response=(
            "Step-up authentication succeeded: the cardholder completed the one-time "
            "passcode on their enrolled device."
        ),
        customer_confirmed=True,
    )


def simulate_analyst_info(context: SimulationContext) -> SimulatedResponse:
    """Request context from a human analyst.

    An analyst adds context but does not settle authorization, so this never
    sets denial or confirmation.
    """
    if context.shared_origin_cards >= 2:
        detail = (
            f"Analyst confirms {context.shared_origin_cards} other cards have been "
            "reported against this same device profile in the current window and a "
            "linked review is already open."
        )
    elif context.testing_sequence_observed:
        detail = (
            "Analyst confirms the small-authorization sequence matches the testing "
            "playbook seen in recent confirmed cases on this issuer range."
        )
    elif context.novel_region:
        detail = (
            "Analyst reports no travel notification on file for this cardholder and no "
            "prior activity in the region in question."
        )
    else:
        detail = (
            "Analyst reports no additional context beyond the activity already "
            "retrieved from the graph."
        )

    return SimulatedResponse(
        request_type=EvidenceRequestType.ANALYST_INFO,
        assumed_response=detail,
    )


_SIMULATORS = {
    EvidenceRequestType.CUSTOMER_VALIDATION: simulate_customer_validation,
    EvidenceRequestType.STEP_UP_AUTH: simulate_step_up_auth,
    EvidenceRequestType.ANALYST_INFO: simulate_analyst_info,
}


def simulate(request_type: EvidenceRequestType, context: SimulationContext) -> SimulatedResponse:
    """Produce the assumed response for one controlled evidence request."""
    simulator = _SIMULATORS.get(request_type)
    if simulator is None:
        raise ValueError(f"no simulator for request type {request_type!r}")

    response = simulator(context)
    logger.info(
        "evidence_requested case=%s type=%s request_no=%d settled=%s",
        context.case_id,
        request_type.value,
        context.request_no,
        response.settles_the_question,
    )
    return response


def preview_all_responses(
    request_type: EvidenceRequestType, context: SimulationContext
) -> list[SimulatedResponse]:
    """Every response this request could plausibly return.

    Used by the value-of-information gate: a request is only worth making if
    at least one possible response would change the decision. Previewing the
    alternatives is side-effect free and does not consume the request.
    """
    if request_type is EvidenceRequestType.CUSTOMER_VALIDATION:
        return [
            SimulatedResponse(
                request_type=request_type,
                assumed_response="Customer denies the transaction.",
                customer_denied=True,
            ),
            SimulatedResponse(
                request_type=request_type,
                assumed_response="Customer confirms the transaction.",
                customer_confirmed=True,
            ),
            SimulatedResponse(
                request_type=request_type,
                assumed_response="No response within 24 hours.",
                no_reply=True,
            ),
        ]
    if request_type is EvidenceRequestType.STEP_UP_AUTH:
        return [
            SimulatedResponse(
                request_type=request_type,
                assumed_response="Step-up authentication failed.",
                customer_denied=True,
            ),
            SimulatedResponse(
                request_type=request_type,
                assumed_response="Step-up authentication succeeded.",
                customer_confirmed=True,
            ),
        ]
    return [
        SimulatedResponse(
            request_type=request_type,
            assumed_response="Analyst supplies additional context.",
        )
    ]
