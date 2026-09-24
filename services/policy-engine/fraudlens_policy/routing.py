"""Approval routing, exactly as Fraud Policy v1.0 section 2 specifies.

Routing is a pure function of the action and the exposure. It is deliberately
separated from rule evaluation so a rule can never invent a route, and so the
answer validator can recompute every route independently of the agent.
"""

from __future__ import annotations

from fraudlens_contracts import Action, Route

# BLOCK_CARD is L1 at or below this exposure and L2 above it.
BLOCK_CARD_L2_THRESHOLD_USD = 2_500.0

# Actions the agent may execute alone. Everything else waits for a human.
_AUTO_ACTIONS: frozenset[Action] = frozenset(
    {
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
)

# Always L2 regardless of exposure.
_ALWAYS_L2: frozenset[Action] = frozenset({Action.BLOCK_ALL_CARDS, Action.FILE_REPORT})

# Always L1 regardless of exposure.
_ALWAYS_L1: frozenset[Action] = frozenset({Action.DECLINE_TRANSACTION})


def route_for(action: Action, exposure_usd: float) -> Route:
    """Return the approval route required for `action` at `exposure_usd`.

    Raises:
        ValueError: if the action is not a known policy action.
    """
    if action in _AUTO_ACTIONS:
        return Route.AUTO
    if action in _ALWAYS_L2:
        return Route.L2
    if action in _ALWAYS_L1:
        return Route.L1
    if action is Action.BLOCK_CARD:
        # Policy 2: L1 when exposure <= $2,500, L2 above it.
        return Route.L2 if exposure_usd > BLOCK_CARD_L2_THRESHOLD_USD else Route.L1
    raise ValueError(f"no route defined for action {action!r}")


def is_auto_executable(action: Action) -> bool:
    """Whether the agent may carry this action out without human approval."""
    return action in _AUTO_ACTIONS


def requires_approval(action: Action, exposure_usd: float) -> bool:
    return route_for(action, exposure_usd) is not Route.AUTO
