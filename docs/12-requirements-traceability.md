# Requirements traceability

This matrix prevents a polished subset from being mistaken for a complete submission.

| Requirement | Design owner | Planned proof |
|---|---|---|
| Official data integrity and exact IDs | Data foundation | `data/source-manifest.json` plus source profile; byte/hash, row, null, reference, exposure, and card-mapping checks |
| Trigger from risk score, customer report, analyst | Investigator intake | Contract tests for all three trigger types |
| Graph, transaction, device, behavior, prior case, external evidence | Graph queries + GraphRAG | Evidence ledger/source coverage report |
| Identify pattern and risk | Hypothesis/assessment nodes | Historical validation + per-case review |
| Create and progress a case | Workflow + Case vertex | Checkpoint timeline and graph readback |
| Use prior-case memory | Structural/vector retrieval | Cited `similar_prior_cases`; retrieval tests |
| Gather controlled additional evidence | Value-of-information + simulator | Initial/final action change trace |
| Recommend allowed next actions | Policy engine | R1–R10 boundary tests |
| Enforce permissions/approvals | Policy engine + approval interrupt | Zero route violations; UI approval audit |
| Know when to stop | Stop predicate | Stop-reason and evidence-independence tests |
| Explain evidence and decision | Evidence ledger + narrative builder | Claim-to-source coverage validation |
| Use TigerGraph Savanna/CE | Graph platform | Workspace/schema/query evidence |
| Use GSQL and graph algorithms | `graph/queries`, optional algorithms | Installed-query manifest and tests |
| Use TigerGraph MCP | MCP adapter | Tool trace and connection preflight |
| Use GraphRAG | Dual retrieval | Structural/semantic/fused scores and citations |
| Provide UI | Analyst workbench | End-to-end demo and Playwright smoke test |
| 20 exact answer files | Output writer/validator | File inventory and schema report |
| Write cases to graph | Persistence adapter | 20 matching readback receipts |
| SAR when required | Policy + SAR builder | Filing/action consistency and narrative checks |
| Initial and final actions/routes | Workflow + policy | Required fields and `what_changed` checks |
| Demo video | Demo script | Verified public video URL |
| Technical blog | Publication artifact | Verified public article URL |
| Social post with tag/link | Publication artifact | Verified post URL and `@TigerGraphDB` |
| GitHub repository | Repository setup | Public `main` at `MananPoojara/GoaHH-TigerGraph-Task4`, verified through GitHub API |
| One final form submission | Team lead | Submission confirmation before deadline |

## Challenge success criteria coverage

All eleven success criteria from the PDF map to the workflow, graph, policy, validation, and UI components above. Completion cannot be claimed until the proof column has authoritative evidence, not merely an implemented component.
