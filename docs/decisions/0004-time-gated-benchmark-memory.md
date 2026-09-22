# ADR-0004: Time-gated benchmark memory

**Status:** Accepted — 22 September 2026

## Context

The challenge requires case writeback and memory, but the 20 benchmark cases occur across November and December. Letting a later case inform an earlier case would leak future information; treating agent-derived benchmark conclusions as historical truth could compound mistakes.

## Decision

Run benchmark memory in opened-time order. Queries enforce a decision-time cutoff, and benchmark-derived cases have a lower trust tier than labeled closed history. Also run each case independently from a clean snapshot and review material differences.

## Consequences

Memory is demonstrated without future leakage. Sequential benefits are measurable, errors are less likely to cascade, and results remain comparable with independent runs.
