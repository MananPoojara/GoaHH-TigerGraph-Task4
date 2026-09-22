# Demo storyboard

Target duration: 3 minutes 45 seconds. Choose an official case that starts ambiguous, reveals a graph connection, requests meaningful evidence, changes the action, and results in a clear case-memory writeback.

## 0:00–0:25 — The problem

Show the case queue and open the selected trigger.

Narration: fraud teams receive a score or complaint, but the flagged transaction is only the starting point. FraudLens investigates the episode, relationships, prior cases, uncertainty, and policy before recommending action.

## 0:25–1:20 — Graph investigation

Start the live case. Show the timeline as bounded queries retrieve:

- the card/customer history;
- the local transaction window;
- device, email, and region relationships;
- similar historical cases;
- one relevant policy/typology chunk.

Let the evidence graph reveal the strongest connection. Open one evidence row and show the exact query reference and real IDs.

## 1:20–2:05 — Uncertainty and more evidence

Show the initial probability, leading hypothesis, alternative explanation, and counter-evidence. The policy panel should display the initial action and route.

Trigger the selected evidence request. Clearly show that the benchmark response is simulated and record the assumption. Then show the probability and recommended action update with `what_changed`.

## 2:05–2:50 — Policy and approval

Show the final ordered actions with R-rule citations and `auto`/`L1`/`L2` badges. Approve one non-auto demo action if applicable. Explain that the LLM cannot bypass routing and that only auto actions execute without a human.

Open the SAR only if the selected case requires it. Highlight the who/what/when/where/how/why evidence mapping.

## 2:50–3:25 — Case memory and validation

Finish the run. Show:

- output validation passed;
- the case bundle was written and read back from TigerGraph;
- the graph now connects the case to its evidence, actions, and prior cases;
- the exact JSON export is available.

Search similar cases and show the newly completed case as memory, with its lower benchmark-derived trust tier.

## 3:25–3:45 — Close

Return to the queue with all 20 cases and validation/writeback status.

Closing line: “FraudLens turns an uncertain alert into a traceable, policy-compliant action—and leaves behind better evidence for the next investigation.”

## Rehearsal checklist

- Savanna workspace is running and warm.
- Selected case has been reset idempotently.
- Model quota and network are healthy.
- Browser is logged in and zoom/notifications are controlled.
- No secrets or private traces are visible.
- Live run finishes under the target twice.
- Recorded-run fallback is current and visibly labeled.
- Demo video playback, audio, and shared URL are verified from a logged-out session.
