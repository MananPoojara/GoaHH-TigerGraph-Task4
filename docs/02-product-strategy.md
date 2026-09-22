# Product and judging strategy

## Product thesis

FraudLens should feel like an excellent analyst with perfect memory and strict operating controls. Its advantage is not a more confident chatbot. Its advantage is a visible chain from trigger → graph evidence → uncertainty → policy → action, with each claim reproducible.

The central design choice is to optimize **decision quality under uncertainty**. Half the cases are legitimate, high risk scores are often false positives, low scores can still be fraud, and `uncertain` can earn full credit when the evidence and actions are appropriate. A system that over-blocks will fail both accuracy and next-best-action scoring.

## Judging allocation translated into engineering priorities

| Judging area | Weight | Product proof | Engineering priority |
|---|---:|---|---|
| Investigation accuracy | 25% | Finds complete episode, connected cards/devices, correct pattern or legitimate result | Bounded graph queries, explicit evidence ledger, temporal baselines, prior-case retrieval |
| Next-best action | 25% | Initial/final actions change correctly as evidence arrives | Deterministic policy engine, decision-value gate, approval routing |
| Case summary and explainability | 10% | Concise case plus traceable evidence and defensible SAR | Provenance-first state, structured generation, consistency validator |
| Agentic design and engineering | 15% | Stateful tool use, memory, permissions, reliable orchestration | LangGraph checkpoints, TigerGraph MCP, policy boundary, retries/replay |
| Innovation | 15% | Graph/vector fusion, calibrated uncertainty, emerging-pattern discovery | Structural + semantic memory, counter-evidence search, optional ring monitor |
| Demo quality | 10% | One clear case evolves end to end without waiting or confusion | Seeded demo case, timeline UI, before/after actions, preflight script |

## Five differentiators

### 1. Counter-evidence search

The agent must search for evidence that weakens its leading hypothesis before acting. Examples include prior legitimate travel to the region, a recurring merchant/amount pattern, the device appearing in the customer's history, or normal home activity that contradicts a travel explanation. This reduces confirmation bias and produces more credible uncertainty.

### 2. Decision-value evidence requests

The agent requests customer validation, step-up authentication, or analyst information only when a plausible response would change the verdict, action, approval route, or SAR requirement. Every request records:

- current probability and competing hypotheses;
- expected outcomes and their action impact;
- why this request is the least disruptive useful choice;
- the assumed response used for the benchmark simulation.

### 3. Dual-memory GraphRAG

Case memory combines two retrieval paths:

- **Structural retrieval:** matching cards, devices, regions, emails, sequences, and graph neighborhoods.
- **Semantic retrieval:** vector similarity over closed-case notes, case summaries, policy chunks, typologies, and approved regulatory guidance.

The agent fuses and re-ranks both, cites the cases actually used, and separates labeled historical memory from lower-trust benchmark-era memory.

### 4. Evidence path receipts

Every graph-derived claim carries the exact query version, decision-time cutoff, parameter hash, returned entity IDs, and supporting path edges. The analyst can move from a sentence to the evidence row and then to the graph path that produced it. This turns explainability into a reproducibility feature rather than a generated paragraph.

### 5. Counterfactual action preview

Before requesting customer validation, step-up authentication, or analyst information, FraudLens evaluates the small set of allowed outcomes. The interface shows how `confirmed`, `denied`, `no_response`, or the relevant analyst response would change probability, action route, SAR status, and stop condition. A request is made only when at least one plausible outcome changes the decision.

## Scope order

### Must ship

- Official data ingestion and verified graph counts
- Required graph schema and investigation queries
- One complete stateful investigator
- Deterministic policy and approval engine
- Seeded evidence simulator
- Exact output validator and 20 answer files
- Analyst workbench with timeline, evidence, uncertainty, and actions
- Case writeback and memory retrieval
- Reproducible 3–5 minute demo

### Ship after required gates pass

- Hybrid vector/structural retrieval improvements
- Calibration dashboard and case comparison
- Emerging-pattern clustering
- Autonomous exam-period monitoring in a separate output folder
- Richer graph visualization and query-performance tuning

## Failure modes to design out

| Failure | Prevention |
|---|---|
| Treating risk score as truth | Independent evidence rubric; score appears as one feature only |
| Hallucinated IDs or amounts | Dataset membership checks and server-side exposure recomputation |
| Good prose with unsupported claims | Evidence objects created before narrative; entity references validated |
| LLM bypasses policy | Deterministic policy engine owns routes and execution permission |
| One-sided investigation | Mandatory counter-evidence phase before final assessment |
| Raw graph dump overwhelms model | Purpose-built bounded queries returning compact evidence packets |
| Retrieval uses future benchmark cases | Opened-time gating and provenance trust tiers |
| Graph features leak future activity | Every feature and query has an `as_of` cutoff; chronological tests fail on later edges |
| Network proximity is treated as guilt | Structural signals remain attributed evidence; probability requires corroboration and calibration |
| Case/report conflation | Separate action predicates and cross-field validator |
| Human override disappears from the audit | Store actor, rationale, evidence viewed, before/after action, and timestamp |
| Demo fails on network/model variance | Cached read-only fallback for presentation only, plus visible live-run status |

## Product name and demo line

**FraudLens — from uncertain signal to defensible action.**

The demo should prove that line in one case: show an ambiguous trigger, uncover connected evidence, request one meaningful confirmation, update the probability and action route, explain the decision, and write the case back to the graph.
