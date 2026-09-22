# ADR-0001: One stateful investigator

**Status:** Accepted — 22 September 2026

## Context

The case flow has many stages but one authoritative state, strict output consistency, and a two-day delivery window. A multi-agent design would require conflict resolution, shared-memory coordination, and more model calls.

## Decision

Use one LangGraph state machine with specialized graph, retrieval, policy, simulation, validation, and persistence tools. Independent read queries may execute concurrently.

## Consequences

State transitions, checkpoints, retries, and approvals remain explicit. Specialized logic stays testable without the reliability cost of agent-to-agent negotiation. Future subgraphs can be added after the scored path is stable.
