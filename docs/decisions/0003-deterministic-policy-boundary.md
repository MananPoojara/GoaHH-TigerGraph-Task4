# ADR-0003: Deterministic policy boundary

**Status:** Accepted — 22 September 2026

## Context

Action names, thresholds, approval routes, case/report rules, and stopping criteria are exact benchmark requirements. Model-only compliance is difficult to prove.

## Decision

Implement policy version 1.0 as deterministic predicates and validators. The LLM supplies a structured assessment and explanation; the policy engine supplies allowed actions, routes, required artifacts, and execution permission.

## Consequences

Policy behavior becomes testable at boundaries and consistent across runs. The workflow must normalize evidence into the facts required by those predicates, and explanations must cite the resulting rule evaluation.
