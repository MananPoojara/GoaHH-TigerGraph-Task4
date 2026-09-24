# Implementation notes

What was actually built, what differs from the pre-implementation design, and
what a reviewer should look at first.

## Where the design changed

The architecture documents were written before implementation. These points
changed once the code met the data:

| Planned | Built | Why |
|---|---|---|
| Next.js workbench ([03](03-system-architecture.md)) | React + TypeScript + Vite | `CLAUDE.md` specifies Vite; it is also a smaller dependency surface for a two-day build |
| Cytoscape.js graph view | Hand-drawn SVG, deterministic column layout | Same picture on every run, which matters for a rehearsed demo and for comparing two cases; avoids a dependency for one view |
| `ClosedCase` as its own vertex | One `Case` vertex with `source` + `trust_tier` | Unifies memory retrieval while keeping the bank's labelled truth distinguishable from our own conclusions |
| Probability from a calibrated model | Versioned deterministic rubric | A probability scored for calibration must be reproducible; the calibrator can be fitted later against the same rubric outputs |

## Decisions made during implementation

### R6 requires that this case shows fraud

The policy reads "when several cards show *fraud* from the same device
profile". An early version triggered R6 on the sharing alone, which produced a
case where the cardholder confirmed their own purchase and the system still
recommended a regulatory filing. The answer contract caught it: a legitimate
verdict cannot file a report. R6 now requires
`strongly_suspected_or_confirmed`, and a golden test pins both directions.

Sharing an origin is not itself fraud. A household sharing a tablet, or a
popular device model, will share one profile innocently.

### Derived IDs stay out of `entity_ids`

Device-profile IDs are a hash we compute; they are not in the supplied
dataset. The README says every ID in an answer must exist in the dataset and
that made-up IDs score zero, and its own worked example cites cards and cases
in `entity_ids` while keeping the device in `connected_device_profiles` as a
readable string. The validator flags any ID it cannot resolve, which is how
this was found.

### An episode must not normalise its own device

The customer baseline window ends at the case cutoff, so it contains the
episode's own earlier transactions. A compromise running for a few hours would
therefore "establish" its own device as familiar, and the counter-evidence
step would cite that as evidence of innocence — in one run producing an answer
that called the same device both new and familiar in consecutive sentences.

The identity record's `id_15` New/Found marking is the bank's own judgement
for that account, so the familiarity check now defers to it.

### `tool_calls` is a per-case delta

The graph client is reused across the 20 cases, so its lifetime call count is
not what the answer file asks for. Each case records the count at intake and
reports the difference.

### The verdict baseline precedes the case requirement

Opening a case is record-keeping, not a response to the fraud. An early
version treated the 3a case requirement as satisfying the action list, so a
fraud verdict at 0.70 produced `CREATE_CASE` and no containment action at all.
The engine now applies the verdict baseline first and adds record-keeping
actions after.

## The fixture backend

`FixtureGraphClient` implements the same installed-query contract over
preprocessed CSVs. It exists so tests and the workbench run without a
provisioned workspace, and it plants known-answer scenarios (a card-testing
sequence, a two-customer device ring, a novel region with concurrent home
activity, and a clean control customer).

It is a test double, not an alternative architecture. Every method mirrors a
query written in GSQL under `graph/queries/`; the GSQL is authoritative and is
what a scored run executes. Cutoff handling is duplicated faithfully on
purpose — a temporal-leak bug that only reproduced against the real backend
would be found far too late.

`/health` always reports which backend answered.

## Bugs the official data exposed

The synthetic fixture passed everything. Running against the real 590,742
transactions surfaced four faults that a fixture could not have:

**The SAR rate was 70%.** The bank's own history files a report on 7% of
cases. The cause was device linking: the most-shared "device profiles" in the
data are `unknown | unknown | unknown | unknown` (1,011 customers) and
`Windows | Windows 10 | chrome 63.0 | 1920x1080` (842 customers). Those are
configurations, not devices, and connecting cardholders through them made the
policy 3a connection predicate fire almost everywhere. `device_identity.py`
now requires a profile to be specific before it may link anyone. The rate fell
to 6 of 20.

**R5's "within an hour" was never checked.** `within_one_hour` was being set
from the authorization count rather than measured, over a 24-hour window. One
case was labelled card testing on the strength of three small charges and
*25* larger purchases spread across a day. The span is now computed from the
timestamps, and a larger purchase only completes the pattern if it follows the
run.

**Episodes were unbounded.** A cardholder with 10,315 prior transactions
produced a 55-transaction "episode" worth $2,102. The episode is now
contiguous activity within 48 hours of the flagged transaction, capped at 25
transactions. The same case now reports $1,034, and a customer-report case
reports exactly the $49.00 named in its own trigger text.

**`connected_device_profiles` listed everything.** It was reporting every
profile the card had ever touched — around 250 entries on one case — when the
field means profiles linking this case to *other cards*. It now carries only
the profile that actually connected something.

Two policy-interpretation questions also surfaced, resolved the same way in
both cases: a rule whose premise has failed should not fire. R6 names a ring
only when this case shows fraud, and R7 ("Disputed but *legitimate*") applies
only when the recurring match is the best explanation — otherwise it would bar
a block on precisely the cases that need one.

## What is not done

- The GSQL has not been executed against a live TigerGraph instance. It is
  written against the 3.x/4.x `SYNTAX v2` dialect and reviewed, but syntax
  errors are likely on first install and should be expected.
- Probability calibration against the chronological closed-case history. The
  rubric is versioned and its outputs are reproducible, so a Platt or isotonic
  fit can be added without changing the workflow.
- GraphRAG document ingestion. The retrieval path, chunk vertices, and
  citation edges are in the schema; the policy and regulatory documents are
  not yet chunked and embedded.
- TigerGraph MCP: our server (`graph/client/fraudlens_graph/mcp_server.py`,
  twelve business-capability tools over stdio) is driven end to end by an MCP
  client in `scripts/check_mcp.py`, and the official `tigergraph-mcp` server
  is registered read-only in `.mcp.json`. The investigator itself still calls
  the same tool functions in-process rather than over MCP.
- Edges are loaded by the GSQL loading job `graph/loading/01-loading-job.gsql`;
  closed-case device links are derived in-graph by
  `graph/loading/02-derive-case-links.gsql`. Neither has run on a live
  instance yet.

## Where to look first

| Question | File |
|---|---|
| Does it respect the answer contract? | `packages/contracts/fraudlens_contracts/answer.py` and `tests/unit/test_answer_contract.py` |
| Is policy really deterministic? | `services/policy-engine/fraudlens_policy/rules.py` |
| Can the LLM bypass authorization? | `apps/api/app/main.py:execute_action` and `tests/integration/test_api.py` |
| Is graph work actually in GSQL? | `graph/queries/`, `graph/algorithms/` |
| How is evidence kept separate from inference? | `services/investigator/fraudlens_investigator/state.py` |
| Does it handle uncertainty honestly? | `services/investigator/fraudlens_investigator/assessment.py` |
