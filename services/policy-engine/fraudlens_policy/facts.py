"""The normalized fact pattern the policy engine decides on.

Every field is a checkable observation, not a conclusion. The LLM may assemble
these facts from graph evidence, but it never states the resulting action: the
engine derives that. Keeping the input this narrow is what stops a persuasive
model from talking its way past an approval route.
"""

from __future__ import annotations

from fraudlens_contracts import Pattern, Verdict
from pydantic import BaseModel, ConfigDict, Field


class CustomerResponse(BaseModel):
    """What the cardholder said when asked, if they were asked at all."""

    model_config = ConfigDict(extra="forbid")

    asked: bool = False
    denied: bool = False
    confirmed: bool = False
    no_reply_24h: bool = False

    def model_post_init(self, _context: object) -> None:
        exclusive = [self.denied, self.confirmed, self.no_reply_24h]
        if sum(1 for flag in exclusive if flag) > 1:
            raise ValueError("customer response must be at most one of deny/confirm/no reply")
        if any(exclusive) and not self.asked:
            raise ValueError("a customer response requires that the customer was asked")


class CardTestingFacts(BaseModel):
    """Observations behind rule R5.

    The sequence must be observed in the graph, never inferred from a risk
    score: the README is explicit that card testing is "confirmed by the
    sequence itself".
    """

    model_config = ConfigDict(extra="forbid")

    small_auth_count: int = Field(default=0, ge=0)
    within_one_hour: bool = False
    followed_by_larger_purchase: bool = False
    cleared_purchase_amount_usd: float = Field(default=0.0, ge=0.0)

    @property
    def sequence_observed(self) -> bool:
        """R5 trigger: three or more small online authorizations within an hour,
        followed by a larger purchase."""
        return (
            self.small_auth_count >= 3 and self.within_one_hour and self.followed_by_larger_purchase
        )


class SharedOriginFacts(BaseModel):
    """Observations behind rule R6.

    `shared_element` names the concrete device profile, billing region, or
    recipient email so the recommendation can cite it, as R6 requires.
    """

    model_config = ConfigDict(extra="forbid")

    cards_sharing_origin: int = Field(default=0, ge=0)
    shared_element: str = ""
    shared_element_kind: str = ""
    within_one_window: bool = False
    connected_card_ids: list[str] = Field(default_factory=list)

    @property
    def ring_observed(self) -> bool:
        """R6 trigger: several cards showing fraud from one shared origin in a window."""
        return (
            self.cards_sharing_origin >= 2 and self.within_one_window and bool(self.shared_element)
        )


class PolicyFacts(BaseModel):
    """The complete decision input for one case at one point in time.

    The engine is evaluated twice per case: once before any evidence request
    (the initial recommendation) and once after the assumed response (the
    final recommendation).
    """

    model_config = ConfigDict(extra="forbid")

    case_id: str
    verdict: Verdict
    fraud_probability: float = Field(ge=0.0, le=1.0)
    pattern: Pattern
    exposure_usd: float = Field(default=0.0, ge=0.0)

    # Evidence shape
    independent_signal_count: int = Field(default=0, ge=0)
    conflicting_evidence: bool = False
    evidence_requested: bool = False

    # Trigger context
    customer_disputed: bool = False
    matches_recurring_legitimate_pattern: bool = False
    has_pending_authorization: bool = False

    # Rule-specific observations
    customer: CustomerResponse = Field(default_factory=CustomerResponse)
    card_testing: CardTestingFacts = Field(default_factory=CardTestingFacts)
    shared_origin: SharedOriginFacts = Field(default_factory=SharedOriginFacts)

    # Connection facts feeding the SAR predicate
    connected_to_other_card_fraud: bool = False
    connected_to_shared_device_profile: bool = False
    coordinated_or_undocumented_abuse: bool = False

    # R10 guard
    customer_cards_with_confirmed_fraud: int = Field(default=0, ge=0)
    credentials_confirmed_compromised: bool = False

    @property
    def rests_on_single_signal(self) -> bool:
        """R1 applies when the case rests on one signal, a lone risk score included."""
        return self.independent_signal_count <= 1

    @property
    def strongly_suspected_or_confirmed(self) -> bool:
        """The SAR gate in policy 3a: fraud confirmed or strongly suspected.

        A denial from the cardholder is a confirmation of unauthorized use even
        when the probability sits just below the high-confidence band.
        """
        return self.verdict is Verdict.FRAUD and (
            self.fraud_probability >= 0.70 or self.customer.denied
        )
