# Policy, safety, and explainability

## Deterministic policy boundary

The LLM proposes a fact pattern and supporting evidence. The policy engine decides which actions are valid, which routes apply, whether a case/report is required, and whether execution is allowed. The UI and output validator independently check the result.

## Action routing matrix

| Action | Route |
|---|---|
| `ALLOW_TRANSACTION` | `auto` |
| `DECLINE_TRANSACTION` | `L1` |
| `MONITOR_CARD` | `auto` |
| `MONITOR_CONNECTED_CARDS` | `auto` |
| `WARN_CUSTOMER` | `auto` |
| `VERIFY_WITH_CUSTOMER` | `auto` |
| `STEP_UP_AUTH` | `auto` |
| `BLOCK_CARD` | `L1` when exposure ≤ $2,500; otherwise `L2` |
| `BLOCK_ALL_CARDS` | `L2` |
| `GENERATE_REPORT` | `auto` |
| `CREATE_CASE` | `auto` |
| `FILE_REPORT` | `L2` |
| `ESCALATE_TO_ANALYST` | `auto` |
| `CLOSE_NO_FRAUD` | `auto` |

Only `auto` actions may be simulated as executed by the agent. The rest remain recommendations awaiting explicit human approval.

## Policy rule predicates

| Rule | Machine-checkable trigger | Required/forbidden effects |
|---|---|---|
| R1 | Single signal and probability < 0.70 | Verify or step up before blocking |
| R2 | Customer denies | Block card + create case; report if exposure > $1,000 or connected to shared device/another card's fraud |
| R3 | Customer confirms | Close no fraud and record confirmation |
| R4 | No response for 24 hours | Monitor card + decline pending authorizations; escalate above $500 exposure |
| R5 | ≥3 tiny online authorizations within one hour then larger purchase | Decline + step up; block if cleared purchase > $100 |
| R6 | Several cards share fraudulent device/region/recipient-email origin in one window | Name origin, create case, file report, monitor connected cards |
| R7 | Dispute matches recurring legitimate pattern | Create case + verify + warn; do not block |
| R8 | Uncertain with exposure > $500 or conflicting evidence | Escalate to analyst |
| R9 | Coordinated/repeated abuse fits no known pattern | Create case + file report + escalate; use `undocumented` description |
| R10 | Fewer than two customer cards show confirmed fraud and credentials not confirmed compromised | Forbid block-all-cards |

Additional rules from sections 3a–7 are also encoded: when to create a case, when to file a report, exposure calculation, allowed evidence requests, stopping, and explanation requirements.

## Case versus SAR

A case is an internal investigation record. Open one when probability reaches 0.30, evidence is requested, or a customer disputes a charge. A SAR is an external regulatory report and requires confirmed/strongly suspected fraud plus the policy's exposure, connection, coordinated, or undocumented predicate.

The validator enforces:

- no `FILE_REPORT` without `CREATE_CASE`/case existence;
- `sar.file` exactly matches final `FILE_REPORT`;
- non-filed SAR fields use the specified empty values;
- a filed narrative has 6–12 sentences and covers who, what, when, where, how, and why;
- totals, dates, subjects, and mentioned IDs reconcile with evidence.

## Evidence ledger

Each evidence item contains:

- an atomic claim;
- source type (`graph`, `document`, `customer`, or `external`);
- a reproducible query/document/request reference;
- exact supporting entity IDs;
- timestamp and case cutoff;
- support direction and source family;
- collection tool/query version.
- a reproducible path receipt or document-content hash;
- the maximum source-event timestamp used by the query or derived feature.

The final narrative may compress evidence but cannot introduce a material claim absent from the ledger.

## Explanation format for analysts

The UI explanation has five short sections:

1. **Finding:** verdict, probability, and pattern.
2. **Why:** strongest supporting and counter-evidence.
3. **Scope:** affected transactions, cards, devices, exposure, and episode dates.
4. **Action:** ordered initial/final actions, exact route, rule citation, and pending approval.
5. **Stop:** why further evidence is unlikely to change the action or what remains uncertain.

The interface can reveal the underlying query reference and entity IDs for every claim.

Network proximity, shared infrastructure, centrality, and case similarity are shown as attributed signals, never as guilt by association. The explanation names the corroborating independent evidence or keeps the verdict uncertain.

## Human approval and override record

For each L1/L2 decision, store the analyst identity, timestamp, recommendation shown, evidence snapshot hash, approval/rejection, rationale, and resulting action state. A human override appends a new audit event rather than editing the model output. Override frequency and rationale categories are reviewed as product-quality signals; an override is not automatically accepted as a fraud label for future calibration.

## Regulatory narrative quality

The benchmark policy controls whether to file. When a SAR is required, official FinCEN guidance improves its quality: describe the suspicious activity clearly, explain why it is unusual, include relevant cyber/device identifiers, and retain the supporting evidence behind the report. FraudLens therefore generates the narrative from the same evidence ledger and keeps its supporting records linked in the graph.

## Prompt-injection and tool safety

- Retrieved content is quoted evidence and cannot change system permissions.
- The runtime exposes only named read queries plus one validated case-write tool.
- Tool parameters are typed, length-bounded, and checked against case context.
- A document cannot request more tools, reveal secrets, change policy, or alter output destinations.
- The agent never receives database or provider credentials in prompt text.

## Audit and reproducibility

Every run records case/run IDs, input hashes, temporal cutoff, graph/query versions, path receipts, feature lineage, knowledge document hashes, prompt/model versions, raw and calibrated probability revisions, uncertainty type, policy evaluations, action state transitions, approvals/overrides, output hash, graph-write receipt, tool count, tokens, and latency.

Corrections append a new run and supersede the old result; they do not silently overwrite the evidence trail.

## Hackathon disclaimer

All customer contact, step-up authentication, card/account actions, reports, and external-system updates are simulated. The interface labels this clearly without distracting from the analyst workflow.
