# Research notes and design implications

Researched on 22–23 September 2026. Primary and official sources were preferred for technical decisions.

## Challenge and data

- The supplied PDF defines the required TigerGraph, GSQL/algorithms, MCP, GraphRAG, UI, 20 outputs, demo, blog, and social deliverables.
- The [official shared dataset folder](https://drive.google.com/drive/folders/1YDJUW1fiE7Jx8R9KqknC4IcsED9zll2A) contains the authoritative README and four files.
- The README makes three scoring-sensitive points: about half the cases are legitimate, risk score is not truth, and `uncertain` can be correct when actions follow policy.
- Design implication: probability calibration, counter-evidence, and restraint matter as much as pattern detection.

## TigerGraph MCP

Source: [TigerGraph MCP repository and README](https://github.com/tigergraph/tigergraph-mcp).

Current capabilities include schema inspection, node/edge operations, installed queries, loading jobs, GSQL, vector attributes and similarity search, connection profiles, tool discovery, and workflow templates. The project describes `stdio` as the normal single-user transport and streamable HTTP/SSE as a shared-server option that needs endpoint authentication.

An Agent Reach/Jina read of the current upstream README also confirms Python 3.10–3.14 support, TigerGraph 4.1+ as the minimum, and TigerGraph 4.2+ as the recommended version for TigerVector and advanced hybrid retrieval. The server can expose a subset of tools and log tool calls, which fits the least-privilege and audit design.

Design implications:

- Use MCP as the agent's graph tool boundary.
- Prefer installed, described, bounded queries for repeatability and lower token use.
- Use `stdio` for the solo local demo.
- Keep writes behind one validated case-bundle adapter.
- Use structured MCP results as evidence packets instead of exposing raw database responses.

## GSQL and loading

Sources: [GSQL 4.2 query language](https://docs.tigergraph.com/gsql-ref/4.2/querying/) and [loading-job reference](https://docs.tigergraph.com/gsql-ref/current/ddl-and-loading/creating-a-loading-job).

GSQL queries are defined multi-statement operations suited to graph traversal, and loading jobs can take multiple input files, accept run-time file locations, expose loading endpoints, and be monitored/restarted.

Design implications:

- Separate versioned schema, loading jobs, and installed investigation queries.
- Load the 708 MB transaction file through TigerGraph's loading path rather than API row inserts.
- Keep online investigation queries bounded; reserve global algorithms for batch features.

## TigerGraph graph analytics and vectors

Sources: [TigerGraph graph-data-science connected components](https://docs.tigergraph.com/graph-ml/current/community-algorithms/connected-components) and the [GSQL 4.2 vector/hybrid-search documentation index](https://docs.tigergraph.com/gsql-ref/4.2/querying/).

TigerGraph supports graph algorithms and vector/hybrid retrieval. Whole-graph components can identify broad rings, while online cases need focused temporal neighborhoods.

Design implications:

- Use bounded pattern queries in the scored path.
- Use weakly connected components or community methods only for optional offline ring monitoring.
- Combine structural prior-case candidates with vector similarity over summaries/notes and document chunks.

## TigerGraph GraphRAG implementation guidance

Source: [TigerGraph GraphRAG repository](https://github.com/tigergraph/graphrag).

Agent Reach/Jina research of the current README recommends a bottom-up tuning order: chunking, extraction, retrieval, then prompts. It suggests markdown chunks around 2,048 characters with overlap for prose, larger 4,096–8,192 chunks for table-heavy regulatory material, bounded `top_k`/hop retrieval, and changing one tuning parameter at a time against a stable evaluation set. It also warns that extracted entities and relationships are best-effort and must be validated for high-stakes use.

Design implications:

- Preserve policy/regulatory table structure during chunking.
- Use a strict fraud-domain extraction schema and filter document-layout noise.
- Validate critical extracted facts against source chunks before using them as evidence.
- Version the GraphRAG configuration and its evaluation results.
- The current upstream GraphRAG project is AGPL-3.0 and its top-level configuration links need special handling on Windows; do not make a full source checkout a critical-path dependency unless its license and Windows setup are explicitly accepted.

## Agent Reach

Source: [Agent Reach repository](https://github.com/Panniantong/agent-reach) and [official installation guide](https://raw.githubusercontent.com/Panniantong/agent-reach/main/docs/install.md).

Agent Reach 1.5.0 is installed in a dedicated user virtual environment and its Codex skill is registered. The research passes used its Jina Reader backend to inspect the live TigerGraph MCP, GraphRAG, graph-fraud, temporal-feature, calibration, and human-oversight sources. Core web/RSS access works; Exa/GitHub CLI and other optional channels require the separately authorized system setup.

## Graph fraud, temporal features, and calibration

Sources:

- [TigerGraph fraud-detection graph guidance](https://www.tigergraph.com/glossary/fraud-detection-with-graph/)
- [Leakage Safe Graph Features for Interpretable Fraud Detection in Temporal Transaction Networks](https://arxiv.org/abs/2603.06632) (2026 preprint)
- [Graph-Based Financial Fraud Detection with Calibrated Risk Scoring and Structural Regularization](https://arxiv.org/abs/2605.12782) (2026 preprint)

TigerGraph's current guidance emphasizes timestamped relationships, shared infrastructure, bounded multi-hop reasoning, traceable paths, and multiple detection layers. The two recent preprints provide directional rather than production-grade evidence: one reports that causal graph features can add interpretable context when computed only from past edges, while the other reports improved risk ranking and calibration from graph structure with noise regularization.

Design implications:

- Give every graph query and derived feature an explicit `as_of` cutoff and lineage record.
- Keep structural features complementary to transaction/identity evidence; shared infrastructure is not guilt by association.
- Persist graph-path receipts so an analyst can reproduce each structural claim.
- Evaluate probabilities chronologically with Brier score, expected calibration error, reliability plots, and operational Precision@k.
- Treat both papers as unreviewed preprints and validate their ideas locally before relying on them.

## Human oversight

Source: [NIST AI RMF Appendix C on Human-AI Interaction](https://airc.nist.gov/airmf-resources/airmf/appendices/app-c-ai-risk-management-and-human-ai-interaction/).

NIST recommends clearly defining human and system roles and notes that override frequency and rationale can be useful operational data. It also warns that explanations and human-AI interaction can amplify bias rather than automatically correcting it.

Design implications:

- Assign evidence planning, policy enforcement, approval, and release validation to named owners.
- Preserve the original recommendation when an analyst overrides it.
- Record identity, rationale, evidence snapshot, and result for approvals and rejections.
- Analyze overrides as product feedback, but do not automatically promote them to training labels.

## LangGraph

Source: [LangGraph workflow design documentation](https://docs.langchain.com/oss/javascript/langgraph/thinking-in-langgraph).

LangGraph exposes explicit state, node-level checkpoints, retry policies, pause/resume interrupts, and human-in-the-loop workflows. Its documentation recommends storing raw state rather than formatted text and treating errors as workflow branches.

Design implications:

- Use one stateful workflow with checkpoints around evidence and approvals.
- Model L1/L2 approval as interrupts.
- Keep compact raw evidence in state and derive prose later.
- Retry transient graph/model errors, surface semantic failures to the planner, and never fabricate missing evidence.

## FinCEN narrative and supporting evidence

Sources:

- [October 2025 SAR FAQ](https://www.fincen.gov/resources/statutes-regulations/guidance/frequently-asked-questions-regarding-suspicious-activity)
- [SAR supporting-documentation guidance](https://www.fincen.gov/resources/statutes-regulations/guidance/suspicious-activity-report-supporting-documentation)
- [Common SAR narrative errors](https://www.fincen.gov/resources/statutes-regulations/guidance/suggestions-addressing-common-errors-noted-suspicious)
- [Cyber-event and cyber-enabled crime SAR FAQ](https://www.fincen.gov/resources/frequently-asked-questions-faqs-regarding-reporting-cyber-events-cyber-enabled-crime-and-cyber)

FinCEN emphasizes useful, accurate narratives, the who/what/when/where/why elements, detailed cyber identifiers where relevant, and retention of supporting records.

Design implications:

- Generate SAR prose only from the evidence ledger.
- Include device/email identifiers when relevant to the fraud mechanism.
- Preserve linked supporting evidence and make it retrievable.
- Treat challenge policy as the benchmark filing authority; use regulatory sources to improve narrative quality, not to override the supplied thresholds.

## Alternatives considered

| Alternative | Why not selected for the critical path |
|---|---|
| Multi-agent investigator/critic/policy swarm | More coordination, token cost, state inconsistency, and demo failure points; one explicit graph provides the same separation |
| Let the LLM write arbitrary GSQL | Harder to test, slower, broader access, and inconsistent evidence references |
| Treat all 400+ fields as graph entities | Bloats schema without adding traversal value |
| Risk score as initial fraud probability | Encodes the benchmark's intentionally unreliable signal as truth |
| Vector-only case memory | Misses exact shared-device/card/region structure |
| Graph-only memory | Misses narrative and policy similarity across structurally different cases |
| Build optional monitor first | Does not improve the 20-case accuracy gate and risks deadline completion |

## Open implementation decisions

- Exact LLM and embedding providers, based on credentials, latency, and structured-output reliability.
- Savanna workspace endpoint and resource size.
- Whether TigerGraph native embeddings or application-produced embeddings are fastest to configure in the available account.
- GitHub repository URL and license choice.

These choices do not change the architecture boundaries.
