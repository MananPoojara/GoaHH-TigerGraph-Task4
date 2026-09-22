# Working agreement for coding agents

Read `README.md` and `docs/01-problem-brief.md` through `docs/09-delivery-roadmap.md` before changing the design.

## Non-negotiable domain rules

1. Treat `risk_score` as one signal, never as the verdict.
2. Use only entity IDs that exist in the supplied dataset. Do not recover labels from the public IEEE-CIS/Kaggle data.
3. Keep graph evidence, document evidence, customer evidence, and simulated evidence distinct and attributable.
4. Validate action names and approval routes against policy version 1.0. Only `auto` actions may execute; L1/L2 actions must wait for human approval.
5. Preserve both `next_best_actions.initial` and `next_best_actions.final` whenever evidence is requested.
6. Keep `CREATE_CASE` separate from `FILE_REPORT` and enforce the policy thresholds for each.
7. A legitimate case has no affected transactions, zero exposure, and no SAR.
8. A filed SAR must correspond to `FILE_REPORT` in final actions and must identify who, what, when, where, how, and why.
9. Stop only under the challenge stop criteria and record the reason.
10. Write a case vertex and its evidence/action relationships before setting `written_to_graph` to true.

## Engineering rules

- Keep the policy engine deterministic and independent of the LLM.
- Use typed contracts at every service boundary and validate answer JSON before persistence.
- Make graph queries bounded by time, hops, and result count.
- Store raw evidence in workflow state; generate prose only after evidence validation.
- Never expose TigerGraph or LLM credentials to the browser.
- Preserve run metadata: run ID, timestamps, model and prompt version, query versions, latency, token counts, and tool-call counts.
- Process benchmark cases in opened-time order when case memory is enabled. Never let a later benchmark case inform an earlier one.
- Add or update tests for policy invariants, graph-query semantics, answer contracts, and benchmark regressions with every implementation change.

## Scope discipline

The immediate target is the 20 official cases and a reliable 3–5 minute demo. Optional autonomous monitoring begins only after all required output validators and policy tests pass.
