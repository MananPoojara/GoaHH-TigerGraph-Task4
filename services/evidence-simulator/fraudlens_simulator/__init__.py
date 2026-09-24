"""Seeded, ground-truth-blind simulation of unavailable evidence."""

from .simulator import (
    SIMULATOR_VERSION,
    SimulatedResponse,
    SimulationContext,
    preview_all_responses,
    simulate,
    simulate_analyst_info,
    simulate_customer_validation,
    simulate_step_up_auth,
)

__all__ = [
    "SIMULATOR_VERSION",
    "SimulatedResponse",
    "SimulationContext",
    "preview_all_responses",
    "simulate",
    "simulate_analyst_info",
    "simulate_customer_validation",
    "simulate_step_up_auth",
]
