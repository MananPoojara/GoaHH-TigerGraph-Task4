# Problem brief and acceptance contract

## Mission

Build a TigerGraph-powered AI agent that can move from an uncertain fraud trigger to a defensible action. It must investigate connected activity, create and progress a case, retrieve prior-case memory, request additional evidence when useful, enforce the supplied policy and approval routes, explain its reasoning, and know when to stop.

The submission deadline in the supplied brief is **24 September 2026 at 11:59 PM IST**. The current plan therefore optimizes for a reliable scored path before optional features.

## Authoritative inputs

| Source | Authority | Key facts |
|---|---|---|
| Supplied challenge PDF | Challenge scope and judging | Required TigerGraph, GSQL/algorithms, TigerGraph MCP, GraphRAG, UI, 20 answer files, demo, blog, social post |
| [Dataset Drive folder](https://drive.google.com/drive/folders/1YDJUW1fiE7Jx8R9KqknC4IcsED9zll2A) | Data, policy, answer contract | Exact files, policy R1–R10, fields, cases, and example |
| Dataset `README.md` | Highest detail for benchmark behavior | Explicitly says to read it first; defines scoring-sensitive invariants |

If the brief and dataset README differ in detail, use the dataset README for the answer contract because it defines the data and grading format.

## Dataset facts

| File | Scale | Role |
|---|---:|---|
| `transactions.csv` | 590,742 rows, about 708 MB | All original 393 Vesta columns plus customer, timestamp, channel, risk score; no fraud label |
| `identity.csv` | 144,432 rows, about 26.7 MB | Online identity/device data joined on `TransactionID` |
| `closed_cases_history.csv` | 5,565 cases | 4,665 confirmed fraud and 900 cleared cases from July–October; labeled memory |
| `case_pack.csv` | 20 cases | November–December benchmark triggers |

The public IEEE-CIS/Kaggle labels cannot be used to recover outcomes. IDs, times, and amounts were transformed, and attempting label recovery is disqualifying.

## Required system behavior

1. Accept risk-score, customer-report, and analyst-request triggers.
2. Open or create a case and inspect the flagged transaction in its temporal and relational context.
3. Gather evidence from graph structure, transaction history, identity/device signals, behavior, closed cases, policy, and approved external sources.
4. Detect the five documented patterns and allow `undocumented` when evidence shows abuse that fits none.
5. Estimate a fraud probability independently from the supplied risk score.
6. Decide whether evidence is sufficient, which missing evidence has the highest decision value, and whether to request it.
7. Record both the initial action and the final action after any assumed response.
8. Map every action to `auto`, `L1`, or `L2` exactly as policy version 1.0 specifies.
9. Execute only `auto` actions; represent L1/L2 as pending human approvals.
10. Produce an internal case, an optional SAR, and next-best actions in the exact JSON contract.
11. Write the case and its evidence/action links to the graph for future retrieval.
12. Explain used evidence, requested evidence, uncertainty, policy basis, and stopping reason.

## Required output invariants

- Twenty files exist in `outputs/cases/`, named `HHG-001.json` through `HHG-020.json`.
- Every required field is present and correctly typed.
- Every entity ID exists in the supplied dataset.
- `legitimate` implies empty affected transactions, zero exposure, and no SAR.
- `sar.file == true` if and only if `FILE_REPORT` is in final actions.
- A report always has a case behind it.
- `written_to_graph == true` only after successful graph persistence and readback.
- Final action routes match the exact action/threshold matrix.
- Initial and final actions are identical when no evidence was requested.
- Exposure equals the sum of absolute amounts for the affected transactions.
- Stop criteria and the evidence supporting them are recorded.

## Five known patterns

| Pattern | Core signature | Key ambiguity |
|---|---|---|
| `card_testing` | At least three tiny online authorizations within an hour, then a larger purchase | Sequence must be verified, not inferred from score |
| `card_not_present_fraud` | Uncharacteristic online amounts/products, often a 2–4 transaction burst in 48 hours | One unusual purchase is ambiguous |
| `card_not_present_new_device` | CNP pattern plus a device marked new, possibly proxied | A new phone is legitimate evidence against certainty |
| `out_of_region_use` | In-person activity in a novel region while normal home activity continues | Multi-day coherent travel may be legitimate |
| `account_takeover` | Mixed-channel activity with device and match anomalies | Requires multiple independent signals |

## Submission artifacts

- Working agent and usable analyst interface
- GitHub repository
- 20 validated answer files, with cases written into TigerGraph
- 3–5 minute end-to-end demo video
- Technical blog covering product, architecture, TigerGraph, agentic capabilities, lessons, and improvements
- X or LinkedIn post linking the blog/demo and tagging `@TigerGraphDB`
- One final form submission by the team lead; the brief says there are no resubmissions

## Acceptance definition

Architecture is ready for implementation when the graph schema, query contracts, workflow states, policy invariants, answer validator, evaluation gates, and demo path are all defined without relying on hidden labels. The product is submission-ready only when every artifact above is generated, reviewed, and replayable from a clean run.
