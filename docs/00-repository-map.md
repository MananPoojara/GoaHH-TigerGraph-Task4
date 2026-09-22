# Repository map

```text
GoaHH/
├── .github/                    # CI, issue templates, and PR template (implementation phase)
├── apps/
│   ├── api/                    # FastAPI control plane and streaming endpoints
│   └── web/                    # Analyst workbench
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
│   ├── queries/                # Installed investigation queries
│   ├── algorithms/             # Bounded analytics and optional batch graph jobs
│   └── migrations/             # Ordered schema/query evolution
├── data/
│   ├── raw/                    # Ignored official CSVs
│   ├── processed/              # Ignored derived load files
│   └── fixtures/               # Small synthetic, safe test data
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
└── README.md
```

## Ownership boundaries

| Area | Owns | Must not own |
|---|---|---|
| `graph/` | Graph schema, loading, installed queries, algorithms | LLM prompts or business-policy decisions |
| `services/investigator/` | State transitions, tool selection, evidence plan | Final permission decisions |
| `services/policy-engine/` | Exact actions, routes, thresholds, invariants | Free-form reasoning or graph access |
| `services/evidence-simulator/` | Seeded assumed responses and provenance | Hidden ground truth |
| `packages/contracts/` | Shared request, state, evidence, action, output types | Runtime side effects |
| `apps/api/` | Authentication, orchestration, streaming, approval endpoints | Graph analytics logic |
| `apps/web/` | Analyst experience, visualization, approval interaction | Credentials or policy enforcement |
| `outputs/` | Validated submission and run artifacts | Raw data or secrets |

Each implementation directory starts with a README and receives source files only when its contract and acceptance tests are ready.
