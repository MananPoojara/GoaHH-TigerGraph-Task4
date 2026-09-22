# Analyst workbench specification

## Experience goal

An analyst should understand what happened, why FraudLens believes it, what remains uncertain, and which action needs approval within 30 seconds. The interface is an investigation workbench, not a chat transcript.

## Primary desktop layout

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ FraudLens  Case HHG-014  In progress  Run 8F31  [Export] [Replay]          │
├──────────────┬────────────────────────────────┬─────────────────────────────┤
│ CASE QUEUE   │ EVIDENCE GRAPH / TIMELINE      │ ASSESSMENT                  │
│ 001 ✓        │                                │ Verdict: uncertain          │
│ 002 ●        │  card ─ txn ─ device ─ card    │ Probability: 0.64           │
│ ...          │       timestamp timeline       │ Pattern candidates          │
│ filters      │                                │ Evidence for / against      │
├──────────────┴────────────────────────────────┼─────────────────────────────┤
│ INVESTIGATION PROGRESS                        │ NEXT-BEST ACTION             │
│ Trigger → Evidence → Countercheck → Request   │ Initial / Final tabs        │
│ → Reassess → Policy → Persist                 │ Route + rule + approval     │
├───────────────────────────────────────────────┴─────────────────────────────┤
│ Evidence ledger | Similar cases | Policy | Case JSON | Audit trace          │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Key views

### Case queue

Shows all 20 official cases with trigger type, opened time, run state, verdict, validation status, and graph-write status. Filters: unresolved, uncertain, approval pending, SAR required, failed validation.

### Investigation timeline

Displays workflow checkpoints and elapsed time. Each step opens its tool calls, evidence added, probability revision, and errors/retries. This makes the agentic process visible during the demo.

### Evidence graph

Shows only the case-relevant subgraph. Node types have stable shapes/colors; edge labels and timestamps are visible on selection. Analysts can pin evidence, hide context nodes, and jump from a claim to its supporting path. A receipt drawer shows query version, cutoff, result hash, and feature lineage.

### Evidence ledger

Separates supporting, opposing, and contextual evidence. Each row shows the claim, source, reference, entity IDs, and source family. Simulated customer/analyst responses have a prominent `ASSUMED FOR BENCHMARK` badge.

### Assessment

Shows verdict, calibrated fraud probability, uncertainty band and type, leading and alternative patterns, episode dates/exposure, and strongest counter-evidence. The risk score and network scores appear as small attributed input signals so they cannot visually dominate the conclusion. Calibration version and historical reliability are available on demand.

### Next-best action

Initial and final tabs show ordered actions, route badges, policy citations, execution/approval state, and `what_changed`. Before an evidence request, a compact outcome preview shows which possible responses would change the action. L1/L2 rows use explicit approve/reject controls in demo mode and require a rationale.

### Case and SAR

Case summary is concise and links claims to evidence. SAR appears only when required and includes its policy predicate, subjects, amount, dates, and narrative-quality checklist.

### Similar cases

Shows fused similarity with separate structural and semantic scores, outcome, pattern, reason retrieved, and trust tier. An analyst can open the source case without losing current state.

## Interaction rules

- Starting a case always shows the canonical trigger before analysis begins.
- Progress streams without exposing raw chain-of-thought; visible content is evidence, concise rationale, tool status, and policy evaluation.
- Probability revisions show the evidence event that caused them.
- Approval clicks record actor, timestamp, action, route, and decision.
- Reject/override actions preserve the original recommendation and record a reason plus evidence-snapshot hash.
- Export is disabled until answer validation and graph readback succeed.
- Errors stay attached to the failed step and offer a bounded retry.

## Accessibility and visual discipline

- Do not rely on color alone; pair color with labels/icons and patterns.
- Support keyboard focus for queue, tabs, graph nodes, and approvals.
- Maintain WCAG AA contrast and readable text at 125% zoom.
- Use restrained motion; the graph animates only newly discovered relationships.
- Prefer a dense but calm analyst aesthetic: neutral background, red reserved for risk/policy breaches, amber for uncertainty/approval, green for validated state.

## Demo mode

Demo mode preselects one representative case, clears its prior run, warms required queries, and shows a visible `LIVE` indicator. A fallback replay may be available only for presentation recovery and must be labeled `RECORDED RUN`; it cannot masquerade as a live result.

## Responsive scope

Desktop is the required experience. Tablet may support review and approvals. Mobile optimization is outside the hackathon critical path.
