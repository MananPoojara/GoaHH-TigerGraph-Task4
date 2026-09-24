# CLAUDE.md

# TigerGraph Agentic Fraud Investigation

## 1. Project Overview

This repository implements an Agentic Fraud Investigation system for the TigerGraph Agentic Fraud Investigation hackathon.

The system must investigate potentially fraudulent activity, gather and reason over evidence, determine uncertainty, request additional evidence when necessary, recommend or execute authorized next-best actions, explain decisions, maintain fraud cases, and use historical case outcomes as memory.

The core investigation flow is:

1. Trigger investigation
2. Investigate relevant entities and activity
3. Gather evidence
4. Assess risk and uncertainty
5. Gather additional evidence if necessary
6. Recommend or execute next-best action
7. Explain the decision
8. Update case memory

Do not simplify this into a generic chatbot or a simple fraud classification model.

The goal is an end-to-end investigation agent.

---

## 2. Core Project Requirements

The implementation MUST use the following core technologies/components:

- TigerGraph
- GSQL
- TigerGraph graph algorithms
- TigerGraph MCP
- GraphRAG
- An agent framework
- A user interface

TigerGraph is a core part of the system and must not be treated as an optional database.

The agent should use the graph for:

- Entity relationships
- Transaction relationships
- Connected accounts
- Device relationships
- Identity relationships
- Money movement
- Fraud pattern detection
- Historical case relationships
- Graph-based evidence retrieval

GSQL and TigerGraph graph algorithms should be used for graph analysis rather than asking the LLM to infer graph relationships from raw tabular data.

---

## 3. Technology Stack

### Frontend

Use:

- React
- TypeScript
- Vite
- React Router
- TanStack Query
- Axios
- Recharts
- Lucide React

The frontend is an analyst-facing investigation dashboard.

It should clearly expose:

- Investigation trigger
- Case information
- Investigation status
- Risk level
- Confidence / uncertainty
- Evidence
- Graph relationships
- Fraud patterns
- Investigation timeline
- Recommended actions
- Approval requirements
- Additional evidence requests
- Final decision
- Case history

### Backend

Use:

- Python
- FastAPI
- Pydantic
- Uvicorn
- LangGraph
- LangChain
- LangChain MCP adapters
- TigerGraph / pyTigerGraph
- TigerGraph MCP
- Pandas
- NumPy
- scikit-learn where useful
- pytest
- Ruff
- Black

Do not use a globally installed Python environment for project dependencies.

Always activate the virtual environment before installing or running backend dependencies.

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Prefer:

```bash
python -m pip install ...
```

instead of:

```bash
pip install ...
```

Prefer:

```bash
python -m uvicorn ...
```

instead of relying on a globally installed uvicorn.

---

## 4. Repository Architecture

Maintain the following high-level structure:

```text
GoaHH-TigerGraph-Task4/
├── .github/                    # CI, issue templates, and PR template (implementation phase)
├── apps/
│   ├── api/                    # FastAPI control plane and streaming endpoints
│   └── web/                    # Analyst workbench (React/TS/Vite frontend)
├── services/
│   ├── investigator/           # LangGraph state machine and evidence planner
│   ├── policy-engine/          # Deterministic R1–R10 and approval routing
│   └── evidence-simulator/     # Reproducible customer/auth/analyst responses
├── packages/
│   ├── contracts/              # Shared typed models and answer schema
│   ├── prompts/                # Versioned prompts and output instructions
│   └── observability/          # Trace, cost, latency, and provenance helpers
├── graph/
│   ├── schema/                 # TigerGraph vertex, edge, and index definitions
│   ├── loading/                # Loading jobs and transforms
│   ├── queries/                # Installed investigation queries (GSQL)
│   ├── algorithms/             # Bounded analytics and optional batch graph jobs
│   └── migrations/             # Ordered schema/query evolution
├── data/
│   ├── raw/                    # Ignored official CSVs
│   ├── processed/              # Ignored derived load files
│   ├── fixtures/                # Small synthetic, safe test data
│   └── source-manifest.json    # Safe Drive IDs, byte counts, and SHA-256 baseline
├── knowledge/
│   ├── policy/                 # Versioned challenge policy chunks
│   ├── typologies/             # Known/undocumented pattern knowledge
│   ├── regulatory/             # Approved FinCEN/FATF/FFIEC sources and manifests
│   └── raw/                    # Ignored downloaded source documents
├── outputs/
│   ├── cases/                  # HHG-001.json … HHG-020.json
│   ├── optional-monitoring/    # Innovation-only alerts
│   └── traces/                 # Local run traces, ignored
├── tests/
│   ├── unit/                   # Policy, scoring, parsing, validation
│   ├── integration/            # TigerGraph/MCP/workflow boundaries
│   ├── e2e/                    # Full official-case runs
│   └── golden/                 # Expected synthetic investigation behaviors
├── scripts/                    # Repeatable setup, ingestion, run, and validation commands
├── infra/                      # Local compose and deployment manifests
├── docs/                       # Architecture, evaluation, UI, demo, ADRs
├── .env.example
├── .gitignore
├── AGENTS.md
├── CONTRIBUTING.md
├── SECURITY.md
├── README.md
└── CLAUDE.md
```

This mirrors [docs/00-repository-map.md](docs/00-repository-map.md), which is the source of truth for structure and ownership boundaries — check it before introducing or renaming a top-level directory.

Do not randomly introduce new top-level directories.

If a new directory is necessary, first determine whether an existing directory already represents that responsibility.

---

## 5. Core Architecture Principle

TigerGraph is the source of graph truth.

Do not duplicate the graph into an unrelated database unless there is a clear technical reason.

Do not replace TigerGraph graph traversal with:

- Python dictionaries
- Pandas joins
- SQL joins
- LLM reasoning
- Manually constructed relationship lists

when the relationship can be represented and queried naturally in TigerGraph.

The LLM should reason over evidence retrieved from the graph. It should not replace graph analysis.

---

## 6. Agent Architecture

Use LangGraph for the investigation workflow.

The agent should be stateful.

The investigation state should contain relevant information such as:

- `case_id`
- `trigger`
- `entities`
- `transactions`
- `evidence`
- `findings`
- `fraud_patterns`
- `risk`
- `confidence`
- `uncertainty`
- `requested_evidence`
- `actions`
- `approval_requirements`
- `decision`
- `explanation`
- `investigation_history`
- `case_memory`

Do not put the entire investigation into one huge agent function.

Prefer explicit nodes such as:

```text
trigger
    ↓
load_case
    ↓
investigate_graph
    ↓
retrieve_policy
    ↓
retrieve_case_memory
    ↓
analyze_evidence
    ↓
assess_uncertainty
    ↓
need_more_evidence?
   /              \
 YES              NO
  ↓                ↓
request_evidence  determine_action
  ↓                ↓
receive_evidence  policy_check
  ↓                ↓
analyze_again     approval_check
                   ↓
                action
                   ↓
                explain
                   ↓
             update_case_memory
```

The graph should have clear state transitions.

---

## 7. Agent Responsibilities

The agent must be capable of:

- Starting an investigation from a trigger.
- Creating or opening a fraud case.
- Identifying relevant entities.
- Traversing relationships in TigerGraph.
- Gathering transaction evidence.
- Investigating device and identity relationships.
- Examining account behavior.
- Retrieving prior cases.
- Identifying possible fraud patterns.
- Assessing risk.
- Assessing confidence.
- Identifying uncertainty.
- Determining whether additional evidence is required.
- Requesting controlled additional evidence.
- Re-evaluating the case after receiving new evidence.
- Recommending a next-best action.
- Determining whether approval is required.
- Executing only authorized actions.
- Explaining the recommendation.
- Updating case memory.

---

## 8. Do Not Build a Simple Fraud Classifier

The system is NOT:

```text
transaction
    ↓
ML model
    ↓
fraud / not fraud
```

The system should instead be:

```text
fraud signal
    ↓
investigation
    ↓
graph investigation
    ↓
evidence gathering
    ↓
pattern identification
    ↓
risk + uncertainty
    ↓
additional evidence if needed
    ↓
policy evaluation
    ↓
next-best action
    ↓
explanation
    ↓
case memory
```

The dataset does not contain a universal "Is Fraud" flag for every transaction.

Do not invent a fraud label where the source data does not provide one.

---

## 9. Dataset Rules

Before implementing the graph schema or data pipeline:

1. Read the dataset README.
2. Understand every relevant file.
3. Understand the columns.
4. Understand the case structure.
5. Understand the answer format.
6. Identify available fraud patterns.
7. Identify available historical investigation information.
8. Only then design the TigerGraph schema.

Do not guess the dataset schema.

The dataset README is the source of truth for dataset-specific details.

Do not assume fields or relationships that have not been verified.

---

## 10. TigerGraph Rules

All graph work must be represented explicitly.

Before implementing graph queries:

1. Understand the dataset.
2. Identify entities.
3. Identify relationships.
4. Identify attributes.
5. Design the graph schema.
6. Define loading strategy.
7. Define GSQL queries.
8. Define graph algorithms where appropriate.

Use TigerGraph for:

- Connected accounts
- Money flow
- Device connections
- Shared identities
- Transaction relationships
- Suspicious clusters
- Fraud pattern traversal
- Historical case relationships
- Similar entities
- Risk-related graph analysis

Do not move graph logic into Python merely because it is easier.

Python should orchestrate and consume graph results.

TigerGraph should perform graph-oriented computation.

---

## 11. GSQL Rules

Use GSQL for meaningful graph operations.

Examples:

- Connected accounts
- Money flow
- Device connections
- Fraud pattern traversal
- Historical case relationships
- Similar entities
- Customer relationship analysis
- Transaction relationship analysis

Prefer dedicated GSQL queries over repeatedly constructing ad-hoc graph logic inside Python.

Keep GSQL organized under:

- `graph/schema/`
- `graph/queries/`
- `graph/loading/`
- `graph/algorithms/`

---

## 12. TigerGraph MCP Rules

TigerGraph MCP exposes graph capabilities to the agent.

The agent should interact with TigerGraph through well-defined tools.

Prefer business-level tools such as:

- `get_customer`
- `get_transaction`
- `get_transaction_history`
- `find_connected_accounts`
- `trace_money_flow`
- `find_device_connections`
- `detect_fraud_pattern`
- `get_customer_risk`
- `find_similar_cases`
- `get_case_history`

Tool names should describe business capabilities rather than low-level implementation details.

Avoid giving the LLM unrestricted database access when a narrower tool can safely perform the required operation.

---

## 13. Tool Design

Tools should be:

- Small
- Deterministic where possible
- Typed
- Well documented
- Permission-aware
- Easy to test

Every tool should have:

- Name
- Purpose
- Input schema
- Output schema
- Failure behavior
- Permission requirements

Do not create one tool responsible for the entire investigation.

Bad:

```python
investigate_everything()
```

Prefer:

```python
get_transaction_history()
find_connected_accounts()
trace_money_flow()
find_device_connections()
get_prior_cases()
evaluate_policy()
request_customer_validation()
```

---

## 14. GraphRAG Rules

GraphRAG should provide contextual evidence to the LLM.

Do not simply dump raw database rows into the prompt.

Prefer:

```text
TigerGraph
    ↓
Graph retrieval
    ↓
Relevant entities / relationships
    ↓
Evidence transformation
    ↓
Context
    ↓
LLM
```

The context should explain relationships.

Example:

```text
Account A
    ├── used Device D1
    ├── transferred to Account B
    ├── shares device with Account C
    └── appears in prior fraud case C-102
```

rather than simply passing raw database rows.

---

## 15. LLM Responsibilities

The LLM should primarily handle:

- Reasoning
- Evidence synthesis
- Tool selection
- Investigation planning
- Uncertainty interpretation
- Explanation generation
- Action recommendation

The LLM should NOT be the sole source of:

- Graph relationships
- Transaction facts
- Policy rules
- Authorization
- Approval requirements
- Case state
- Historical evidence

Whenever possible, factual claims must originate from tools or stored data.

---

## 16. Policy Engine

Policy enforcement must be deterministic.

Do not rely solely on an LLM prompt to enforce policy.

The policy engine should determine:

- Allowed action
- Required evidence
- Risk threshold
- Approval requirement
- Whether action can be automatically executed
- Whether escalation is required

Example:

```text
Agent recommendation
        ↓
Policy Engine
        ↓
Permission Check
        ↓
Evidence Check
        ↓
Approval Check
        ↓
ALLOW / REQUIRE_APPROVAL / DENY
```

---

## 17. Never Allow the LLM to Bypass Authorization

Never implement:

```python
if llm_says_block:
    block_account()
```

Instead:

```text
LLM recommendation
        ↓
Policy Engine
        ↓
Permission Check
        ↓
Approval Check
        ↓
Authorized Action
```

The LLM must never bypass:

- Policy checks
- Permission checks
- Approval requirements
- Evidence requirements

---

## 18. Additional Evidence

The agent must be able to identify when evidence is insufficient.

Possible controlled evidence requests include:

- Ask account owner to validate a transaction.
- Request step-up authentication.
- Request additional information from an analyst.
- Request information from an approved source.

Model evidence requests explicitly:

```text
EvidenceRequest
    ├── id
    ├── type
    ├── reason
    ├── requested_by
    ├── required_for
    ├── status
    └── result
```

---

## 19. Next-Best Action

Possible actions include:

- `ALLOW_TRANSACTION`
- `BLOCK_TRANSACTION`
- `MONITOR_ACCOUNT`
- `BLOCK_ACCOUNT`
- `WARN_CUSTOMER`
- `CREATE_CASE`
- `REQUEST_MORE_EVIDENCE`
- `ESCALATE_TO_ANALYST`
- `FILE_REPORT`

Do not hard-code one universal action.

The action must depend on:

- Evidence
- Risk
- Confidence
- Uncertainty
- Policy
- Authorization
- Case context

Actions may be:

- Recommended
- Pending approval
- Approved
- Executed
- Rejected

depending on policy.

---

## 20. Case Management

Every investigation should produce a persistent case record.

A case should track:

- `case_id`
- `trigger`
- `status`
- `entities`
- `transactions`
- `evidence`
- `findings`
- `fraud_patterns`
- `risk`
- `confidence`
- `uncertainty`
- `actions`
- `approvals`
- `decisions`
- `explanation`
- `timestamps`
- `investigation_steps`
- `outcome`

Example statuses:

- `OPEN`
- `INVESTIGATING`
- `WAITING_FOR_EVIDENCE`
- `AWAITING_APPROVAL`
- `ACTION_RECOMMENDED`
- `ACTION_EXECUTED`
- `ESCALATED`
- `RESOLVED`

Do not overwrite investigation history.

Maintain an audit trail.

---

## 21. Case Memory

Case memory is a core feature.

Store relevant:

- Findings
- Decisions
- Actions
- Outcomes
- Fraud patterns
- Entities
- Relationships
- Analyst decisions

Historical cases should be retrievable during new investigations.

The system should be able to answer:

- Have we seen a similar case?
- What happened?
- What evidence was important?
- What action was taken?
- What was the outcome?
- What did the analyst decide?

Do not treat case memory as a generic chat-history store.

It should contain investigation-relevant knowledge.

---

## 22. Explainability

Every final recommendation should explain:

```text
Evidence considered
    ↓
Observed relationships
    ↓
Fraud pattern identified
    ↓
Risk assessment
    ↓
Remaining uncertainty
    ↓
Additional evidence requested
    ↓
Policy applied
    ↓
Recommended action
    ↓
Approval requirement
```

Avoid vague explanations such as:

> "The transaction looks suspicious."

Prefer concrete evidence-backed explanations.

Example:

> The transaction is associated with a device previously linked to multiple accounts involved in historical investigations. The destination account is also connected through an observed money-flow relationship. However, ownership of the destination account has not been independently validated. Additional validation is therefore requested before taking an irreversible action.

---

## 23. Evidence vs Inference

Always distinguish between evidence and inference.

**Evidence** — facts returned by:

- TigerGraph
- Dataset
- Policy documents
- Historical cases
- Approved external sources

**Inference** — conclusions generated by the agent based on those facts.

Example:

- Evidence: Account A and Account B share Device D.
- Inference: The shared device may indicate a relationship between the accounts.

Never represent an inference as a database fact.

---

## 24. Benchmark Rules

The final two months contain 20 benchmark cases.

Do not modify benchmark cases.

Do not leak benchmark answers into prompts or hard-coded rules.

Never implement:

```python
if case_id == "case_17":
    return expected_answer
```

Never implement:

```text
transaction_id → predetermined answer
```

unless the mapping is genuinely part of the supplied source data.

The system must derive findings from available evidence.

---

## 25. Data Handling

Do not commit the hackathon dataset into Git unless explicitly required.

Use:

- `data/raw/`
- `data/processed/`
- `data/fixtures/`

for local data.

Never commit:

- `.env`
- API keys
- TigerGraph credentials
- LLM API keys
- Tokens
- Passwords
- Private credentials

Use `.env.example` for configuration documentation.

---

## 26. Mock Actions

Real financial actions are not required.

Actions such as:

- Freeze account
- Block card
- Refund customer
- Send customer message
- Update CRM
- Close case

may be simulated or represented through mock APIs (see `services/evidence-simulator/`).

Prefer safe mock implementations for the hackathon.

Do not connect the prototype to real financial systems unless explicitly authorized.

---

## 27. Frontend Rules

The frontend should be an analyst investigation interface, not just a chat window.

The UI should make it possible to understand:

- What triggered this investigation?
- Who/what is involved?
- What evidence was found?
- How are the entities connected?
- What fraud pattern is suspected?
- What is the current risk assessment?
- How confident is the agent?
- What evidence is missing?
- What action is recommended?
- Does the action require approval?
- What happened during the investigation?

The graph relationship view is an important part of the interface.

Use visualizations where they improve investigation understanding.

---

## 28. Investigation Timeline

The UI should expose investigation progress.

Example:

```text
10:01  Investigation triggered
10:01  Case created
10:02  Transaction history retrieved
10:02  Connected accounts discovered
10:03  Device relationship discovered
10:03  Prior cases retrieved
10:04  Fraud pattern identified
10:04  Confidence assessed
10:05  Additional validation requested
10:07  Validation received
10:07  Risk reassessed
10:08  Action recommended
10:08  Approval requested
10:09  Action approved
10:09  Action executed
10:09  Case updated
```

---

## 29. API Design

FastAPI endpoints should represent business operations.

Prefer:

```text
POST /investigations
GET  /investigations/{id}

GET  /cases/{id}
GET  /cases/{id}/evidence
GET  /cases/{id}/timeline
GET  /cases/{id}/actions

POST /cases/{id}/evidence-request
POST /cases/{id}/approve
POST /cases/{id}/execute
```

Avoid exposing internal implementation details unnecessarily.

---

## 30. Structured Outputs

Prefer structured Pydantic models over free-form strings.

Example:

```python
class ActionRecommendation(BaseModel):
    action: str
    reason: str
    confidence: float
    evidence_ids: list[str]
    requires_approval: bool
```

Do not make critical business logic depend on parsing arbitrary LLM prose.

---

## 31. Error Handling

Never silently swallow errors.

Bad:

```python
try:
    ...
except Exception:
    pass
```

Prefer:

```python
try:
    ...
except Exception:
    logger.exception("TigerGraph query failed")
    raise
```

Errors should contain enough context to debug failures.

Never expose secrets in logs.

---

## 32. Logging

Log important investigation events:

- `investigation_started`
- `case_created`
- `tool_called`
- `tool_failed`
- `evidence_added`
- `risk_updated`
- `evidence_requested`
- `action_recommended`
- `approval_requested`
- `action_executed`
- `case_resolved`

Never log:

- API keys
- Passwords
- Access tokens
- Secrets

---

## 33. Configuration

Centralize configuration in:

```text
apps/api/app/core/config.py
```

Prefer:

```python
settings.tg_host
settings.tg_graphname
settings.openai_api_key
settings.backend_port
```

Do not scatter environment variable access throughout business logic.

---

## 34. Code Quality

Use:

- Ruff
- Black
- Pytest

Python code should follow:

- Type hints
- Small functions
- Clear naming
- Single responsibility
- Explicit error handling
- Pydantic models for external data
- Dependency injection where useful

Avoid:

- Giant functions
- Giant agent prompts
- Global mutable state
- Hidden side effects
- Hardcoded credentials
- Hardcoded benchmark answers

---

## 35. Agent Prompt Rules

Agent prompts should:

- Define the agent's role.
- Define available tools.
- Define evidence rules.
- Define uncertainty behavior.
- Define policy constraints.
- Define action constraints.
- Require evidence-backed reasoning.
- Require structured outputs where possible.

Do not prompt the model to blindly classify transactions.

Prompt the agent to investigate.

---

## 36. Tool Selection Rules

When factual information is needed, prefer a tool over guessing.

Bad: LLM guesses whether accounts are connected.

Good: LLM calls `find_connected_accounts()`.

Bad: LLM guesses transaction history.

Good: LLM calls `get_transaction_history()`.

Tool-returned evidence should be treated as the authoritative source for factual claims.

---

## 37. External Data

External APIs may be used when they provide meaningful complementary evidence.

External sources must not replace TigerGraph.

External data should be:

- Clearly identified
- Traceable
- Relevant
- Included in case evidence
- Handled according to reliability

Do not introduce external services unnecessarily.

---

## 38. Testing

At minimum, maintain tests for:

- Agent
- Graph
- Policy
- Cases
- API
- Benchmark
- End-to-end flow

Test:

- Tool inputs
- Tool outputs
- Graph queries
- Policy decisions
- Permission checks
- Case transitions
- Agent state transitions
- Evidence handling
- Action authorization

For deterministic logic, use deterministic unit tests.

For LLM behavior, test structured outputs and invariants rather than exact prose whenever possible.

---

## 39. Development Workflow

Before implementing a feature:

1. Understand the requirement.
2. Inspect the existing implementation.
3. Identify the correct layer.
4. Check whether an existing abstraction can be reused.
5. Implement the smallest clean change.
6. Add or update tests.
7. Run formatting and linting.
8. Run tests.
9. Verify API/UI behavior.
10. Update documentation when architecture changes.

Do not immediately rewrite large parts of the system.

---

## 40. Architecture Change Rules

If a change affects:

- TigerGraph schema
- Agent state
- LangGraph workflow
- Case model
- Policy engine
- API contract
- Frontend/backend contract

first inspect the existing implementation.

Do not introduce a second competing architecture.

Keep one clear source of truth.

---

## 41. Dependency Rules

Before installing a dependency:

1. Check whether an existing dependency already provides the capability.
2. Check whether the package is actually required.
3. Prefer maintained packages.
4. Keep dependency count reasonable.
5. Update `requirements.txt`.
6. Verify installation in a clean virtual environment.

Use:

```bash
python -m pip install <package>
```

Then update:

```bash
python -m pip freeze > requirements.txt
```

---

## 42. Git Rules

Use small, meaningful commits.

Good examples:

```text
feat: add TigerGraph schema
feat: add transaction graph queries
feat: add investigation state
feat: add fraud investigation agent
feat: add policy engine
feat: add case memory
feat: add investigation dashboard

fix: handle TigerGraph timeout
fix: validate action authorization

test: add graph traversal tests
test: add benchmark pipeline

docs: document graph architecture
```

Avoid:

- `update`
- `changes`
- `stuff`
- `final`
- `final-final`

---

## 43. Documentation

Keep the following documentation updated:

- `docs/03-system-architecture.md`
- `docs/05-agent-workflow.md`
- `docs/04-data-and-graph-model.md`
- `docs/06-policy-safety-explainability.md`
- `docs/07-evaluation-plan.md`
- `docs/08-ui-ux-spec.md`
- `docs/11-demo-storyboard.md`

Documentation should cover:

- What was built
- Architecture
- TigerGraph usage
- Agentic capabilities
- What was learned
- What could be improved

---

## 44. Definition of Done

A feature is not complete merely because the code compiles.

A feature is complete when:

- Implementation exists.
- Types/models are defined.
- Error handling exists.
- Tests exist.
- Relevant documentation is updated.
- Integration works.
- Logs are meaningful.
- No secrets are committed.
- No benchmark-specific hacks are introduced.

---

## 45. End-to-End Definition of Done

The complete system should demonstrate:

```text
Trigger
  ↓
Create/Open Case
  ↓
Investigate Graph
  ↓
Gather Evidence
  ↓
Retrieve Policies
  ↓
Retrieve Prior Cases
  ↓
Identify Fraud Pattern
  ↓
Assess Risk
  ↓
Assess Confidence
  ↓
Determine Uncertainty
  ↓
Request Additional Evidence if Necessary
  ↓
Reassess
  ↓
Recommend Next Best Action
  ↓
Policy Check
  ↓
Approval Check
  ↓
Execute / Escalate
  ↓
Explain Decision
  ↓
Update Case
  ↓
Write Case Memory
  ↓
Display Complete Investigation in UI
```

The final system should demonstrate the complete investigation lifecycle rather than only producing a final fraud prediction.

---

## 46. Priority Order

When making engineering decisions, prioritize:

1. Investigation correctness
2. Evidence quality
3. TigerGraph integration
4. Agent workflow reliability
5. Policy and permission enforcement
6. Case memory
7. Explainability
8. API reliability
9. UI usability
10. Performance optimization

Do not sacrifice correctness for unnecessary complexity.

---

## 47. General Rules for Claude

When working on this repository:

- Inspect before changing.
- Read relevant existing code before implementing.
- Reuse before creating.
- Use TigerGraph for graph problems.
- Use GSQL for graph operations.
- Use TigerGraph MCP for agent-to-TigerGraph interaction.
- Use GraphRAG for contextual evidence.
- Use LangGraph for investigation orchestration.
- Use deterministic code for policies and authorization.
- Use the LLM for reasoning and synthesis.
- Keep evidence separate from inference.
- Never invent evidence.
- Never invent dataset fields.
- Never hardcode benchmark answers.
- Never bypass permissions.
- Never expose secrets.
- Keep investigation history auditable.
- Keep changes small and testable.
- Prefer explicit state over hidden agent behavior.
- Make important recommendations evidence-backed and explainable.
- Do not replace TigerGraph with another graph/database without a clear reason.
- Do not turn the project into a generic chatbot.
- Do not turn the project into a simple fraud classifier.
- Do not add unnecessary dependencies.
- Do not make architectural changes without inspecting the current architecture first.

The final product must behave like an end-to-end fraud analyst investigation system, not an LLM demo.
