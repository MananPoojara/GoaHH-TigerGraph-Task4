# Contributing

FraudLens is currently a solo hackathon project. Changes should still be reviewable and reproducible.

1. Read the architecture and active decision records.
2. Link each change to one benchmark requirement or evaluation gate.
3. Keep generated data, secrets, and local traces out of Git.
4. Run the smallest relevant checks, then the benchmark contract validator before merging.
5. Record architecture changes in `docs/decisions/` when they alter data ownership, service boundaries, policy behavior, or the benchmark protocol.

Commit messages should use a clear imperative summary, for example `Add time-bounded device-ring query` or `Enforce R2 reporting threshold`.
