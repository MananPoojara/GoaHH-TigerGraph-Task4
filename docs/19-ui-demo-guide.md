# FraudLens UI: what every panel means, and what to say in the demo

Plain-language guide to every panel, badge, number, and code the workbench
shows, in the order they appear on screen. Each section ends with a line you
can say in the demo.

---

## 1. The alert queue (home page)

The list of all 20 alerts waiting to be investigated.

| Column | What it means |
|---|---|
| **Case** | The case ID (`HHG-001` … `HHG-020`) and when the alert was opened. |
| **Trigger** | Why the alert exists: `risk_score` (the bank's model flagged it), or a customer or analyst report. The text is the original alert message. |
| **Card** | The card that was flagged (`C12382-K1`) and its owner (`C12382`). `K1` / `K2` = the customer's first / second card. |
| **Model score** | The bank's own fraud score (0–1). This is **their** number, not ours. |
| **Verdict** | Our conclusion once investigated: `fraud`, `legitimate`, or `uncertain`. |
| **Our probability** | **Our** fraud probability, worked out from the evidence. |
| **Exposure** | Dollars at risk: the total of the transactions we judged part of the fraud. |
| **Investigate / Re-run** | Starts the agent live on that case. |

The top-right counter shows "X of 20 investigated · N awaiting approval".

The note at the bottom says the model score is *"a reason to look, not a
verdict."*

> **Say:** "The bank's model flags transactions, but about half of these alerts
> turn out to be legitimate. So we don't trust the score. We investigate. Watch
> how our probability differs from the model score."

---

## 2. Case header

- **Case ID**, then a **status badge**: `closed fraud` (red), `closed legitimate`
  (green), `escalated` (amber, a human needs to look), or another state (grey).
- **Verdict badge**: the final conclusion.

---

## 3. "What triggered this investigation"

**Pills (small tags):** trigger type · flagged transaction ID · card · customer ·
when it opened. Below them is the original alert text.

**Stat row:**

| Stat | Meaning |
|---|---|
| **Model score** | The bank's score (e.g. 0.61). |
| **Our probability** | Our assessed probability (e.g. 0.08 = very likely legitimate). |
| **Exposure** | Money at risk in the fraud episode ($0 if legitimate). |
| **Affected txns** | How many transactions we believe belong to the fraud. |
| **Connected cards** | Other cards linked to this case through a shared device or other shared details. |
| **Graph calls** | How many TigerGraph queries this investigation ran (usually 21–34). |
| **Latency** | How long the whole investigation took. |

> **Say:** "The model said 0.61, but after investigating, our probability is
> 0.08. We didn't just take the score, and we can show you why. The agent made
> about 25 TigerGraph queries to get here."

---

## 4. Assessment panel

**Header:** "N independent evidence families". This counts how many *different
kinds* of evidence agree (device, amount, region, history, and so on). One
strong signal on its own is weak. Several independent ones are strong.

**Probability meter:** the colour shows the band.
- 🟢 **Green, below 0.30:** likely legitimate
- 🟡 **Amber, 0.30–0.70:** uncertain
- 🔴 **Red, 0.70 and above:** likely fraud

| Field | Meaning |
|---|---|
| **Pattern** | Which fraud pattern fits best (see the glossary below). `none` = no fraud pattern. |
| **Confidence** | How sure the agent is of its own conclusion (0–1). |
| **Uncertainty** | `resolved` = nothing important is still unknown. Otherwise it names what's still unclear. |
| **Description** | Only for `undocumented` patterns: the agent describes the new pattern in its own words. |

**Competing hypotheses (bar chart):** every possible explanation gets a score,
*including the innocent one*. They all stay on the chart until the evidence
rules them out. Even when we decide "fraud", the chart shows what else we
considered.

**Rationale box (?):** one line on why the leading explanation won.

**Summary:** the plain-English conclusion.

**Why the investigation stopped:** the agent must justify *stopping*. For
example: "the customer's answer settled it, and the scope is known."

**Graph notice (🗄️):** "Case written to the graph as `CASE-2016-HHG-001` and
verified by read-back." We saved the case into TigerGraph and read it back to
confirm it matches. It is now memory for future cases.

> **Say:** "We don't just give a verdict. We show the competing explanations,
> why the winner won, and why we stopped looking. And the finished case is
> written back into TigerGraph and checked, so the next investigation can learn
> from it."

---

## 5. Evidence ledger

Every fact the agent collected, one row each. The header shows *"N items ·
X for fraud · Y against"*.

Each row shows:
- **Claim:** the fact itself, e.g. *"Flagged transaction 3514030 for $77.07 on
  2016-12-04 is confirmed on card C12382-K1."*
- **Direction badge:** 🔴 `supports fraud` · 🟢 `supports legitimate` · ⚪
  `context` (neutral background information)
- **Source pill:** where the fact came from, e.g. `graph` for TigerGraph or
  `customer` for the simulated customer reply.
- **Ref (grey mono text):** the **exact query and inputs** that produced it,
  e.g. `query:get_case_anchor(card_id=…, txn_id=…)`. Anyone can re-run it and
  check.
- **ID pills:** the real transaction, card, or case IDs involved.

> **Say:** "Every claim here comes from a real query. Nothing is made up by the
> AI. See this reference? That's the exact TigerGraph query that proved it, and
> you can re-run it. We also keep evidence *against* fraud, not just for it."

---

## 6. Graph relationships

A picture of the case, laid out left to right in fixed columns:

**Customer → Card → Transaction → Device profile → Connected cards → Prior cases**

| Colour | Entity |
|---|---|
| Blue | Customer |
| Purple | Card |
| Red | Transaction (a **thicker border** = part of the fraud episode) |
| Yellow | Device profile (a device "fingerprint": OS, browser, screen) |
| Orange | Connected card (another card linked by a shared device) |
| Green | Prior case from the bank's history, with its outcome |

**Edge labels:** `OWNS` (customer owns card) · `MADE` (card made transaction) ·
`FROM_DEVICE` (transaction came from that device) · link reasons such as "same
customer", "shared device profile" or "same card" (the strongest reason a prior
case is related).

The layout is fixed, so the same case always draws the same picture.

> **Say:** "This is the graph TigerGraph gave us: the customer, their card, the
> flagged transaction, the device it came from, and five past cases linked to
> the same customer. The link to the past cases is the relationship a normal
> table would hide."

---

## 7. Suspicious activity report (SAR)

A SAR is the report a bank must file with regulators when fraud is serious
enough.
- **"no filing required"** plus the policy reason (e.g. *"fraud is not
  confirmed or strongly suspected"*).
- **"filing recommended"** plus the reason **and** a full written report
  covering who, what, when, where, how and why.

Filing a report always needs **L2** approval (a fraud manager).

> **Say:** "The report is only written when policy requires it. Here it's 6 of
> 20 cases. And even then, a fraud manager must approve it. The AI can't file on
> its own."

---

## 8. Next best action (the most important panel)

**Header:** "rules R3, R10" = which policy rules fired for this case.

### INITIAL, before any requested evidence
What the agent would do *right now*, before asking anyone anything.

### What changed (→ arrow box)
One line explaining how the new evidence changed the decision.

### FINAL, after the assumed response
The final recommended actions.

### Each action row shows
- **Action name**, e.g. `BLOCK_CARD`
- **Route badge**, meaning who must approve it:

| Badge | Meaning |
|---|---|
| **`auto`** | Low-risk. The agent may do this alone. |
| **`L1`** | Needs a **team lead** to approve. |
| **`L2`** | Needs a **fraud manager** to approve (the highest level). |

- **State badge:** `recommended` · `pending approval` (waiting on a human) ·
  `approved` · `rejected` · `executed`
- **Reason:** which rule required it, e.g. *"R3: cardholder confirmed they made
  the transaction"*

### Buttons
- **Decide:** for L1/L2 actions. Type a rationale (required for the audit
  trail), then **Approve** or **Reject**.
- **Execute:** only appears for `auto` actions, or after a human has approved.
  Actions are **simulated**; nothing touches a real bank.

### 🔒 "Barred by policy"
Actions the policy *blocked*, e.g. `BLOCK_CARD` when the customer confirmed the
purchase. We record what we were **not** allowed to do, not only what we did.

### Approval record
Who approved or rejected what, when, and why. This is the audit trail.

> **Say:** "Here's our main safety feature: **the AI recommends, the rules
> decide.** Blocking a card needs a team lead, and filing a report needs a
> manager. The buttons only show what's allowed, and the API rejects anything
> else even if you call it directly. Watch: I approve this block with a reason,
> and it goes into the audit trail."

### How the route is decided

| Action | Route |
|---|---|
| `ALLOW_TRANSACTION`, `MONITOR_CARD`, `MONITOR_CONNECTED_CARDS`, `WARN_CUSTOMER`, `VERIFY_WITH_CUSTOMER`, `STEP_UP_AUTH`, `GENERATE_REPORT`, `CREATE_CASE`, `ESCALATE_TO_ANALYST`, `CLOSE_NO_FRAUD` | **auto** |
| `DECLINE_TRANSACTION` | always **L1** |
| `BLOCK_CARD` | **L1** if exposure ≤ $2,500, **L2** above |
| `BLOCK_ALL_CARDS`, `FILE_REPORT` | always **L2** |

### What each action means

| Action | Plain meaning |
|---|---|
| `ALLOW_TRANSACTION` | Let it go through |
| `DECLINE_TRANSACTION` | Stop a pending payment |
| `BLOCK_CARD` | Freeze this one card |
| `BLOCK_ALL_CARDS` | Freeze every card the customer has |
| `MONITOR_CARD` | Keep watching this card |
| `MONITOR_CONNECTED_CARDS` | Watch every card linked by the shared device |
| `VERIFY_WITH_CUSTOMER` | Ask the customer "was this you?" |
| `STEP_UP_AUTH` | Require extra login proof (e.g. OTP) |
| `WARN_CUSTOMER` | Send the customer a heads-up |
| `CREATE_CASE` | Open an internal investigation record |
| `ESCALATE_TO_ANALYST` | Hand it to a human analyst |
| `FILE_REPORT` | File the SAR with regulators |
| `CLOSE_NO_FRAUD` | Close the case as legitimate |

---

## 9. The policy rules R1–R10

These are fixed rules in code (`services/policy-engine`), **not** AI decisions.
The same facts always produce the same actions. A rule that *forbids* an action
always beats a rule that *requires* it.

| Rule | Plain meaning | Result |
|---|---|---|
| **R1: Verify before blocking** | Only one signal and probability below 0.70? Don't block, check with the customer first. | Requires `VERIFY_WITH_CUSTOMER`; **forbids** blocking |
| **R2: Customer denies it** | The customer says "that wasn't me". | `BLOCK_CARD` + `CREATE_CASE`; plus `FILE_REPORT` if over $1,000 or linked to a shared device or other fraud |
| **R3: Customer confirms it** | The customer says "yes, that was me". | `CLOSE_NO_FRAUD`; **forbids** blocking |
| **R4: No reply in 24h** | The customer didn't answer. | `MONITOR_CARD`; decline pending payments; escalate if over $500 |
| **R5: Card testing** | Several small online payments within an hour, then a bigger one (fraudsters testing a stolen card). | `DECLINE_TRANSACTION` + `STEP_UP_AUTH`; `BLOCK_CARD` if a purchase over $100 already went through |
| **R6: Shared device ring** | Several cards showing fraud from the same device. Only fires if *this* case shows fraud. | `CREATE_CASE` + `FILE_REPORT` + `MONITOR_CONNECTED_CARDS` |
| **R7: Disputed but legitimate** | The customer disputes a charge that matches their own regular subscription. | Verify + warn; **forbids** blocking |
| **R8: Uncertain and risky** | Unsure with over $500 at stake, or the evidence conflicts. | `ESCALATE_TO_ANALYST` |
| **R9: New fraud pattern** | Coordinated abuse that fits no known pattern. | `CREATE_CASE` + `FILE_REPORT` + escalate; the agent must describe the pattern |
| **R10: Block-all guard** | Never block *all* cards unless 2+ cards show confirmed fraud or login details are confirmed stolen. | **Forbids** `BLOCK_ALL_CARDS` (fires on most cases, which is normal) |

A case is also opened (`CREATE_CASE`) when probability is 0.30 or above.

> **Say:** "These ten rules come straight from the bank's policy. Each one is a
> small, tested function. R10 fires on almost every case. It's a guard that
> stops us freezing all of a customer's cards without strong proof."

---

## 10. Additional evidence

The agent asked someone for more information.
- **Type:** e.g. `customer_validation` (ask the customer if they made the
  purchase).
- **🧪 `simulated` badge:** the answer comes from our **evidence simulator**,
  not a real customer. We say so openly.
- **"after step N":** at which step of the investigation it asked.
- **Reason:** *why* it's worth asking. The agent only asks when a possible
  answer would **change the decision**. If no answer could change anything, it
  skips the request and says so.
- **Quoted text:** the (simulated) answer it received.

> **Say:** "The agent wasn't sure, so it asked for more evidence, but only
> because the answer could change the action. In a real bank this would be an
> SMS to the customer. Here it's simulated, and we mark it clearly. Look at
> how the action changed after the reply."

---

## 11. Case memory

Similar closed cases from the bank's history, found in TigerGraph.
- **Case ID** (e.g. `CC-3587`), **outcome badge** (🔴 `confirmed_fraud` / 🟢
  `cleared`), and **pattern**.
- **"Linked by …":** the strongest reason it's related.
- **Score:** how strong that link is: 1.0 same customer, 0.9 shared device,
  0.6 same card, 0.3 same fraud pattern only. Only the top 5 are shown,
  strongest first.
- **Analyst notes:** what the human analyst wrote back then, when available.

> **Say:** "Have we seen this before? The agent pulls past cases through the
> graph. Here are four earlier cases on the same customer and card. Past
> outcomes are evidence, but they don't decide this case on their own."

---

## 12. Investigation timeline

Every step the agent took, in order: *investigation started → case created →
anchor confirmed → baseline retrieved → patterns checked → devices checked →
prior cases retrieved → assessed → evidence requested → reassessed → action
recommended → explained → case written to graph*.

> **Say:** "This is the full audit trail. Every step is recorded, so an analyst
> can see exactly how we got here."

---

## 13. Pattern glossary

| Pattern | Plain meaning |
|---|---|
| `card_testing` | Small test payments to check a stolen card works, then a big purchase |
| `account_takeover` | Someone else got into the account: new device, mixed channels, mismatched details |
| `card_not_present_new_device` | Online purchase from a device never seen before on this account |
| `card_not_present_fraud` | A burst of online fraud without the physical card |
| `out_of_region_use` | Spending in a new region while the customer is still active at home |
| `undocumented` | Fraud that fits none of the known patterns; the agent describes it |
| `none` | No fraud pattern; the activity fits the customer's normal behaviour |

---

## The agent, in brief

FraudLens is a **LangGraph** agent. It runs the investigation as a series of
clear steps, not one big prompt:

1. **Intake.** Take the alert and confirm, using TigerGraph, that the
   transaction, card and customer actually belong together.
2. **Gather evidence.** Run GSQL queries: spending baseline, the transactions
   around the alert, pattern checks, devices, and connected cards. Every query
   only sees data from *before* the alert time, so nothing leaks from the
   future.
3. **Counter-evidence.** Actively look for the innocent explanation.
4. **Memory.** Find similar past cases in the graph.
5. **Assess.** Score each possible explanation, then set a probability and
   uncertainty.
6. **Initial policy decision.** The rule engine (R1–R10) decides the actions
   and approval routes.
7. **Ask or stop?** Preview each possible answer. Ask for evidence only if an
   answer could change the actions; otherwise stop and say why.
8. **Reassess and decide.** Update with the reply, then run the rules again to
   get the final actions.
9. **Explain.** The LLM (Gemini) writes the summary, using only the evidence.
   If it's unavailable, a template writes it from the same evidence, and the
   decision doesn't change.
10. **Save.** Write the case into TigerGraph, read it back, and confirm it
    matches. It is now memory for the next case.

**One line for the demo:** *"TigerGraph finds the facts, the agent reasons over
them, the rules decide what's allowed, and a human approves anything risky."*
