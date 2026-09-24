# FraudLens

An agentic fraud investigation system for the TigerGraph Hacker House Goa
challenge. It takes an uncertain fraud signal, investigates it against a
property graph, decides whether it needs more evidence, recommends a next best
action under a deterministic policy, explains itself from an evidence ledger,
and writes the closed case back to the graph as memory for the next
investigation.

It is deliberately not a classifier. There is no model that reads a
transaction and emits a fraud score; there is an investigation that gathers
evidence, weighs innocent explanations, and stops when the decision is
defensible.

---

## How it fits together

```text
trigger ─► intake ─► plan ─► collect evidence ─► counter-evidence ─► memory
                                                                      │
                                                                      ▼
                                              assess ─► initial policy decision
                                                                      │
                                                    value of information gate
                                                       │              │
                                          request evidence        enough
                                                       │              │
                                                  reassess ─► final policy
                                                                      │
                                              explain ─► persist + read back
```

| Layer | Owns | Never owns |
|---|---|---|
| TigerGraph + GSQL | Relationships, traversal, pattern observation, case memory | Fraud verdicts |
| `fraudlens_policy` | R1–R10, approval routes, case/report predicates | Reasoning or graph access |
| `fraudlens_investigator` | State, tool selection, evidence sufficiency, stopping | Authorizing an action |
| LLM | Planning, synthesis, explanation | Facts, policy, IDs, probability |
| `fraudlens_contracts` | The answer schema and its validator | Runtime side effects |

The separation that matters most: **the LLM cannot authorize anything.** It
proposes a fact pattern; a deterministic engine decides which actions are
valid and which need a human. The API enforces that boundary a second time, so
a client calling it directly cannot execute a gated action either.

---

## Quick start

### 1. Backend

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # Windows PowerShell
python -m pip install -e ".[dev,api,graph,agent,data,mcp]"
```

### 2. Data

Download the four official files into `data/raw/` from the challenge Drive
folder. `case_pack.csv` and `closed_cases_history.csv` are already present and
SHA-256 verified; `transactions.csv` (708 MB) and `identity.csv` (26.7 MB)
must be downloaded manually.

```bash
python scripts/prepare_data.py           # verifies hashes, builds load files
```

The load is refused if any file disagrees with `data/source-manifest.json`.
The card-ID derivation is asserted against every supplied card ID before the
data is accepted — see [ADR-0006](docs/decisions/0006-card-identity-derivation.md).

No data yet? Everything runs on a synthetic fixture with the same column
structure and planted scenarios:

```bash
python scripts/prepare_data.py --fixture
python scripts/run_benchmark.py --fixture
```

### 3. TigerGraph

```bash
cp .env.example .env                     # fill in TG_HOST, a credential, LLM_API_KEY
python scripts/install_graph.py --check  # connection preflight
python scripts/install_graph.py --all    # schema, queries, loading job, derived links
```

`--load` creates the GSQL loading job in `graph/loading/01-loading-job.gsql`,
posts every processed file to it (all vertices and edges), then runs
`link_closed_case_devices` to derive the closed-case device links in-graph.

The LLM is Gemini by default (`LLM_PROVIDER=gemini`, `LLM_MODEL=gemini-3.5-flash`).
A free-tier key allows 20 requests per model per day, about ten cases; a
full 20-case run needs billing enabled. When the model is unavailable the
explanation falls back to deterministic text and the decision is unchanged.

### MCP

Two MCP servers are registered in `.mcp.json`, both reading `.env`:

| Server | Purpose |
|---|---|
| `fraudlens-graph` | Our 12 business-capability tools (`find_connected_accounts`, `trace_money_flow`, ...), cutoff-enforced and read-only |
| `tigergraph` | The official [TigerGraph MCP](https://github.com/tigergraph/tigergraph-mcp), restricted to `--allowed-tools read-only` |

```bash
python scripts/check_mcp.py              # handshake, list tools, call two on HHG-001
python -m fraudlens_graph.mcp_server     # run our server over stdio
tigergraph-mcp --env-file .env --allowed-tools read-only
```

Without a configured workspace the system falls back to a fixture backend so
the UI and tests still run. `/health` always reports which backend answered,
so it is never ambiguous. **Scored runs require a live graph.**

### 4. Run

```bash
python -m uvicorn app.main:app --reload --port 8000    # API
cd apps/web && npm install && npm run dev              # workbench on :5173
python scripts/run_benchmark.py                        # writes outputs/cases/
```

---

## What the workbench shows

The UI is an investigation interface, not a chat window. Per case:

- the trigger, and the model score alongside our independently assessed probability;
- the evidence ledger, with each claim's direction, source, and replayable query reference;
- competing hypotheses, including the innocent one, with their scores;
- the graph relationships — cards, transactions, devices, connected cards, prior cases;
- what evidence was requested, and the response that was assumed;
- initial and final actions with approval routes, and what changed between them;
- the approval controls, the SAR narrative when one is due, and why the investigation stopped.

---

## Design decisions worth knowing

**Evidence is separated from inference.** The ledger holds facts with a source
and a reproducible reference. Conclusions live elsewhere and are never
promoted into it. Derived device-profile IDs are our construction rather than
supplied data, so they stay out of `entity_ids` and appear as readable strings
in `connected_device_profiles` — invented IDs score zero.

**The risk score is capped.** The README is explicit that it is an input, not
an answer, and that above 0.7 most flagged transactions are legitimate. It
contributes at most 0.10 to the assessed probability and can never carry a
case past an action threshold on its own.

**Counter-evidence is mandatory.** Roughly half the benchmark alerts resolve
as legitimate, so the workflow always tests the innocent explanation before
concluding. A guard stops an episode from normalising its own device: the
baseline window ends at the cutoff and would otherwise contain the fraud's own
earlier activity.

**Evidence is only requested when it would change something.** Each possible
response is previewed through assessment and policy; if none changes the
recommended actions, the request is skipped and that is recorded as the
stopping reason.

**`written_to_graph` is earned.** The case bundle is written with
deterministic IDs, then read back and compared by hash and count. Only a
matching read-back sets the flag true.

**Temporal integrity is enforced, not assumed.** Every read query takes a
cutoff, windows are clamped to it, and device fan-out is recomputed as of the
cutoff rather than read from a whole-graph attribute computed later.

---

## Testing

```bash
python -m pytest tests -q        # 174 tests
python -m ruff check . && python -m black --check .
cd apps/web && npm run typecheck
```

| Suite | Covers |
|---|---|
| `tests/unit` | R1–R10 at every documented boundary, the answer contract, card/device derivation, preprocessing |
| `tests/integration` | Graph tool semantics, cutoff enforcement, the API authorization boundary |
| `tests/golden` | Investigation behaviours: scope, exposure arithmetic, counter-evidence, write-back, temporal leakage |

The contract suite parses the dataset README's own worked example, so if our
schema and the official contract ever disagree, that test fails first.

---

## Repository layout

See [docs/00-repository-map.md](docs/00-repository-map.md). Directory names are
hyphenated for ownership clarity; `pyproject.toml` maps each to an importable
module name.

| Path | Contents |
|---|---|
| `graph/schema`, `graph/queries`, `graph/algorithms` | GSQL: schema, installed investigation queries, ring discovery |
| `graph/loading` | Source verification, identity derivation, load-file generation |
| `graph/client` | The graph boundary, business-capability tools, the fixture backend |
| `services/policy-engine` | R1–R10, routing, case/SAR predicates |
| `services/investigator` | State, nodes, assessment, narrative, persistence, workflow |
| `services/evidence-simulator` | Seeded, ground-truth-blind simulated responses |
| `packages/contracts` | The answer schema and its dataset-aware validator |
| `apps/api`, `apps/web` | FastAPI control plane and the analyst workbench |

---

## Status

**Run against the official data.** All four source files verify against the
committed SHA-256 manifest. Preprocessing accepts 590,742 transactions with
zero rejections, producing 13,553 customers, 14,317 cards, 9,702 device
profiles, and 576,425 `NEXT` edges in about 1m45s. The card-ID derivation
reproduces **5,677 of 5,677** supplied card IDs.

All 20 benchmark cases run and pass the answer validator, in roughly 15
seconds total:

| | |
|---|---|
| Verdicts | 7 fraud, 12 legitimate, 1 uncertain |
| Reports | 6 of 20 |
| Graph calls | 21-34 per case |

The legitimate-heavy split is intended: the README warns that about half these
alerts resolve as legitimate and that an agent which blocks everything scores
badly.

**Not yet done.** The GSQL has not been executed against a live TigerGraph
instance — the runs above used the fixture backend over the same preprocessed
load files. Provisioning a workspace and running `scripts/install_graph.py
--all` is the remaining step, after which `written_to_graph` reflects a real
graph write-back rather than the in-memory one. Probability calibration
against the closed-case history and GraphRAG document ingestion are also
outstanding; see [docs/16-implementation-notes.md](docs/16-implementation-notes.md).
