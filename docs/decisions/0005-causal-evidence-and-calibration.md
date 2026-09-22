# ADR-0005: Causal evidence and calibrated probability

**Status:** Accepted — 23 September 2026

## Context

Graph structure can expose shared infrastructure and coordinated behavior, but a value computed from future edges would leak information and a network score can be mistaken for proof. The challenge also makes risk score intentionally unreliable, while action thresholds depend on a defensible fraud probability.

## Decision

Every graph query and derived feature must have a case-time cutoff and versioned lineage. Graph-path receipts preserve the entities, edges, query version, cutoff, and result hash behind each material claim. Structural scores remain contextual signals that require corroboration.

Fraud probability is calibrated only on chronological closed history. Candidate calibration methods are selected inside the development period, locked before the October holdout, and evaluated with Brier score, expected calibration error, reliability plots, and operational ranking metrics. Benchmark cases never tune the calibrator.

## Consequences

Explanations become reproducible, temporal leakage becomes testable, and action thresholds receive probabilities with measured historical reliability. The implementation must maintain feature metadata and calibration artifacts, but this cost directly protects investigation accuracy and auditability.
