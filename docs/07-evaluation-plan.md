# Evaluation plan

## Evaluation layers

FraudLens is evaluated as a data system, graph system, decision system, agent workflow, and user-facing product. A fluent answer is insufficient if IDs, arithmetic, evidence, policy, or graph persistence are wrong.

## Release gates

| Gate | Pass condition |
|---|---|
| Source integrity | Four official files hashed; row/header profile recorded; no public label source used |
| Graph load | Vertex/edge counts reconcile with accepted rows; no orphan case/transaction/card references |
| Query semantics | Each installed query passes synthetic known-answer fixtures and cutoff-time tests |
| Output schema | All 20 files parse and satisfy every required type/enum/field |
| ID integrity | 100% of referenced official IDs exist; zero invented IDs |
| Arithmetic | Exposure, SAR total, and activity dates recompute exactly from affected transactions |
| Policy | Zero route, threshold, forbidden-action, case/report, or stopping invariant violations |
| Provenance | Every material summary/SAR/action claim maps to evidence and source refs |
| Temporal causality | No query, derived feature, retrieval, or explanation can observe an event after its case cutoff |
| Calibration | Held-out chronological probabilities meet the documented Brier/ECE baseline and reliability review |
| Writeback | All 20 final cases read back from graph with matching bundle hashes |
| Reproducibility | Same inputs/config/seed produce equivalent structured decisions |
| Demo | Clean reset-to-finish rehearsal completes in under 5 minutes twice consecutively |

No optional innovation work begins before the schema, ID, arithmetic, policy, and writeback gates pass.

## Historical validation design

The closed-case history is labeled but imbalanced. Use chronological validation rather than a random split:

- Earlier July–September cases for rubric/calibration development.
- October cases as a held-out validation period.
- November–December benchmark cases never supply labels.

Metrics:

- fraud/legitimate precision, recall, F1, and PR-AUC;
- false-positive rate, with special attention to legitimate high-score alerts;
- Brier score and expected calibration error for `fraud_probability`;
- reliability plots overall and by trigger type; compare uncalibrated, Platt, and isotonic methods without selecting on the October holdout;
- pattern accuracy on confirmed historical fraud;
- episode transaction precision/recall where closed case transaction lists support it;
- connected-card and prior-case retrieval hit rate;
- policy-action exact match on generated rule fixtures;
- tool calls, latency, tokens, and failure/retry rate.

Class balance must be reported; raw accuracy alone is misleading.

Calibration uses only the development period: fit candidate calibrators on an inner chronological split within July–September, select by predeclared Brier/ECE criteria, lock the result, and evaluate once on October. Report sample counts and avoid subgroup claims where the history is too small. The 20 benchmark cases never tune the calibrator.

## Test pyramid

### Unit tests

- R1–R10 predicates and boundary values such as $500, $1,000, and $2,500.
- Action-to-route mapping and forbidden execution.
- Case versus SAR predicates.
- Exposure summation, date ranges, sentence count, and ID validation.
- Time-cutoff and trust-tier filtering.
- Feature-lineage rejection when any source event exceeds the cutoff.
- Evidence-receipt replay and result-hash agreement.
- Device-profile normalization and deterministic IDs.
- Answer-contract serialization and cross-field invariants.
- Evidence independence and stopping-rule evaluation.
- Seeded evidence-simulator determinism.

### Integration tests

- Load a small fixture graph and verify vertex/edge counts.
- Run each installed GSQL query against known patterns and counterexamples.
- Exercise TigerGraph MCP discovery, query, vector retrieval, write, and readback.
- Pause/resume workflow at an approval interrupt.
- Simulate transient MCP/model failure and verify retry/recovery behavior.
- Confirm browser/API cannot execute L1/L2 without explicit approval.
- Confirm approval/override events preserve the original recommendation and require identity plus rationale.

### Golden behavior tests

Create small synthetic cases covering:

1. clear card-testing fraud;
2. one unusual online purchase requiring verification;
3. recurring legitimate charge disputed by customer (R7);
4. coherent travel versus cloned out-of-region activity;
5. shared-device multi-card ring (R6);
6. uncertain exposure above $500 (R8);
7. undocumented coordinated abuse (R9);
8. attempted `BLOCK_ALL_CARDS` without R10 evidence;
9. legitimate verdict with stray affected transaction (validator must fail);
10. future-case leakage attempt (query must exclude it).
11. graph-proximity signal without corroboration (must remain uncertain or seek evidence).
12. evidence request whose possible outcomes never change policy (must be skipped).

Golden tests assert decisions and invariants, not exact wording.

### End-to-end tests

- Run one official case from a clean graph through final validated output and writeback.
- Run all 20 independently from the base snapshot.
- Run all 20 chronologically with time-gated case memory.
- Diff independent and sequential decisions; manually review material changes.
- Validate all output files, graph receipts, and metrics in one release report.

## Quality rubric for each official case

| Dimension | Review question |
|---|---|
| Trigger grounding | Did the investigation verify the flagged transaction/card/customer relationship? |
| Episode scope | Did it look before and after the trigger and justify affected transactions? |
| Relationship scope | Did it inspect devices, emails, regions, cards, and historical cases when relevant? |
| Counter-evidence | Did it actively test the leading hypothesis? |
| Uncertainty | Does probability reflect the evidence rather than risk score confidence? |
| Calibration | Is the recorded calibrator valid for this cutoff and is the probability presented with its reliability limits? |
| Provenance | Can each graph-derived claim be replayed from its path receipt? |
| Evidence request | Could the chosen response actually change the decision? |
| Policy | Are actions ordered, routed, and cited correctly? |
| Explanation | Can every material claim be reproduced from its reference? |
| SAR | If filed, is it complete, standalone, consistent, and policy-triggered? |
| Stop | Is the stop decision defensible and is scope sufficiently known? |

## Performance budgets

- Target median case latency under 30 seconds after graph is warm.
- Target p95 under 90 seconds for the official run.
- Bound UI subgraphs to a readable evidence neighborhood.
- Bound LLM context to summarized evidence packets with source refs.
- Track, but do not optimize tokens at the expense of correctness.

## Submission audit

Before the one allowed submission:

1. Re-fetch the challenge/dataset README and compare the contract hash or manually review any change.
2. Run the full validator and save its report.
3. Verify the repository URL and default branch from a logged-out browser.
4. Confirm 20 case files and graph writeback receipts.
5. Verify demo, blog, and social URLs load.
6. Confirm no credentials, raw dataset, private traces, or unsupported claims are committed.
7. Submit at least one hour before the deadline and retain the confirmation.
