# FraudLens demo script (word for word)

A spoken script, screen by screen and panel by panel. Lines in quotes are what
you say. Lines marked **[DO]** are what you click or point at.

- **Length:** about 5 minutes.
- **Main case:** **HHG-018** (fraud; the action changes after new evidence; a
  report is filed).
- **Optional second case:** **HHG-015** (the opposite: looks like fraud at
  first, turns out legitimate).
- Where a line says **[read it]**, say the number that's actually on screen.

**Before you start:** check the TigerGraph workspace is running, then run
HHG-018 once so it's warm and fast.

---

## Opening (before touching the screen)

"Hi, we're Team TrustMeBro: Yash, Manan and Priyank. This is **FraudLens**.

Banks get thousands of fraud alerts. Most tools just give each transaction a
score and stop there. But a score isn't an answer. About half of these alerts
turn out to be completely legitimate.

So we built an AI agent that actually **investigates** an alert, the way a
human fraud analyst would. It follows the connections, checks the evidence, and
recommends what to do. And all of it runs on **TigerGraph**."

---

## Screen 1: The alert queue

**[DO]** Open http://localhost:5173.

### The table
"This is the analyst's queue: 20 real alerts from the bank.

Each row is one alert. Here's the case ID, and here's **why** it was flagged.
Most came from the bank's risk model, and some came from a customer complaint."

**[DO]** Point at the **Model score** column.

"This column is the bank's own model score. Look, some of these are high. But a
high score doesn't mean fraud. It just means *someone should look at this*.
That's exactly what our agent does."

### The note at the bottom
**[DO]** Point at the yellow note.

"We even say it on screen: the score is a reason to look, not a verdict. Our
agent works out its **own** probability, from real evidence."

### Start the investigation
**[DO]** Click **Investigate** on **HHG-018**.

"Let's run one live. I'm clicking Investigate on case 018. Right now, the agent
is running dozens of queries against TigerGraph."

*(While it loads)* "It's checking the customer's history, their devices, the
cards linked to them, and similar past cases, all inside the graph."

---

## Screen 2: The case page

### Top header
**[DO]** Point at the case ID and the badges.

"Here's the result. Case 018: the verdict is **fraud**, and the case is closed
as fraud. Now let me show you **how** it got there. That's the part that
matters."

---

### Panel: "What triggered this investigation"
**[DO]** Point at the pills, then the alert text.

"First, what started this. Here's the flagged transaction, the card, and the
customer, and this is the original alert message."

**[DO]** Point along the stat row.

"And here's the summary in numbers:
- The bank's model score was **[read it]**.
- Our own probability is **[read it]**. We didn't copy the score, we worked it
  out from evidence.
- The money at risk, the exposure, is **[read it]**.
- It found **[read it]** transactions belonging to this fraud, and
  **[read it]** other connected cards.
- And look at **graph calls: [read it]**. That's how many TigerGraph queries
  this one investigation ran.
- The whole thing took **[read it]** seconds."

---

### Panel: Evidence ledger
**[DO]** Scroll to **Evidence ledger**.

"Now, **evidence**. This is the most important idea in our project. Every fact
the agent uses is listed here, one per row."

**[DO]** Point at one row's claim.

"For example, this line: [read the claim]."

**[DO]** Point at the red and green badges.

"Each fact is marked **red** if it points to fraud, and **green** if it points
to the customer being innocent. We deliberately collect evidence **against**
fraud too, not just for it."

**[DO]** Point at the grey reference text.

"And see this grey text? That's the **exact TigerGraph query** that produced
this fact, with its inputs. So nothing here is made up by the AI. Anyone can
re-run the query and check it."

---

### Panel: Graph relationships
**[DO]** Scroll to **Graph relationships**.

"And here's the part TigerGraph makes possible: the **relationship graph** for
this case.

Reading left to right: the **customer** (blue), owns this **card** (purple),
which made this **transaction** (red), which came from this **device** (yellow).
And on the right, in green, are **past fraud cases** linked to this customer."

**[DO]** Point at the device and the linked cases.

"This is the key point. In a normal spreadsheet, these links are invisible. In
a graph, they're one hop away. Asking *'what else used this device?'* is a
quick query, not a huge join."

---

### Panel: Assessment
**[DO]** Scroll up to **Assessment**.

"Now the agent's thinking.

The probability here is **[read it]**. The colour tells you the band: green
means likely fine, amber means unsure, red means likely fraud.

The pattern it found is **[read it]**."

**[DO]** Point at the header text "N independent evidence families".

"This part matters too. It says **[read it] independent kinds of evidence**
agree. One clue alone is weak. Several different clues pointing the same way
are strong."

**[DO]** Point at the bar chart.

"And this chart shows **every possible explanation** it considered, including
*'no fraud at all'*. The agent has to rule out the innocent explanation
before it's allowed to conclude fraud."

**[DO]** Point at **Summary**, then **Why the investigation stopped**.

"Here's the summary in plain English. And here's something most tools don't
do: it explains **why it stopped** investigating. It has to justify that it
knows enough."

**[DO]** Point at the grey database notice at the bottom.

"And this line says the case was **saved back into TigerGraph**, then read back
to confirm it saved correctly. So the next investigation can learn from this
one."

---

### Panel: Additional evidence (right side)
**[DO]** Point at **Additional evidence**.

"Halfway through, the agent wasn't fully sure. So it **asked for more
evidence**: it asked the customer to confirm the transaction."

**[DO]** Point at the **simulated** badge.

"We're honest about this: the customer's reply here is **simulated**, and it's
clearly marked. In a real bank, this would be an SMS or a call.

And the agent doesn't ask questions for the sake of it. It only asks when the
answer could **change** what it does."

---

### Panel: Next best action (right side, most important)
**[DO]** Point at the **INITIAL** list.

"Now the actions. And this is where you can see the evidence actually matter.

**Before** asking the customer, the agent's plan was cautious: verify with the
customer, warn them, and escalate to an analyst."

**[DO]** Point at the arrow box "what changed".

"Then the answer came back, and this line explains exactly what changed."

**[DO]** Point at the **FINAL** list.

"**After** the new evidence, the plan got stronger: **block the card**, **file
a report**, and **monitor the connected cards**."

**[DO]** Point at the **auto / L1 / L2** badges.

"Now look at these small badges. This is our main safety feature.
- **auto** means the agent can do it alone, like monitoring. Low risk.
- **L1** means a **team lead** must approve, like blocking this card.
- **L2** means a **fraud manager** must approve, like filing a report with
  regulators."

**[DO]** Point at the rule names in the header (e.g. "rules R6, R10").

"These R-numbers are the bank's policy rules. **The AI does not decide these
actions.** A fixed rule engine does. The AI can recommend blocking a card, but
it can never approve that itself. We even check this again in the API, so
nobody can get around it."

**[DO]** Click **Decide** on `BLOCK_CARD`, type *"Evidence confirms account
takeover"*, then click **Approve**.

"Let me approve this as the team lead. I have to give a reason. And now it's in
the **approval record**: who approved it, when, and why. That's a full audit
trail."

*(Only if you see the lock box)* "And this box shows actions the policy
**blocked**. We record what we weren't allowed to do, too."

---

### Panel: Suspicious activity report
**[DO]** Scroll to **Suspicious activity report**.

"Because policy required it, the agent also wrote a **suspicious activity
report**, the report a bank files with regulators. It covers who, what, when,
where and how, all from the evidence.

And remember, filing it still needs a fraud manager's approval. The AI can't
file it on its own."

---

### Panel: Case memory
**[DO]** Point at **Case memory**.

"Here's the memory part. The agent asked: *have we seen something like this
before?* And it found these past cases in the graph. Here's each outcome, fraud
or cleared, and **why** each one is linked, like the same customer or the same
device.

Past cases are evidence, not the answer. They help, but they don't decide this
case alone."

---

### Panel: Investigation timeline
**[DO]** Point at **Investigation timeline** and scroll it.

"And finally, the timeline. Every single step the agent took, in order: from
the alert, to gathering evidence, to asking the customer, to the decision, to
saving the case. Nothing is hidden."

---

## Optional: second case, the opposite result (about 30 seconds)

**[DO]** Go back to the queue and open or run **HHG-015**.

"One quick example going the other way. This one looked risky at first. The
first plan was to **block the card**.

**[DO]** Point at the INITIAL, then FINAL actions.

But the customer confirmed they made the purchase, so the final action is
**close, no fraud**. The policy even **blocks** us from blocking the card now.

That's why investigation beats a simple score. A score would have annoyed an
innocent customer."

---

## Closing

**[DO]** Go back to the queue.

"So that's FraudLens. We ran it on about **590,000 real transactions** and all
**20 cases**. It found 7 fraud, 12 legitimate, and 1 it honestly couldn't
decide. It filed 6 reports, and every case was saved back into TigerGraph and
checked.

In one line: **TigerGraph finds the facts, the agent reasons over them, the
rules decide what's allowed, and a human approves anything risky.**

Thank you!"

---

## If a judge asks…

**"Why a graph and not a normal database?"**
"Fraud is about connections: shared devices, linked cards, past cases.
Following those links is what a graph is built for. In a normal database it's
many slow joins."

**"What does TigerGraph actually do here?"**
"All the graph work. We have about 26 GSQL queries for the timeline, patterns,
shared devices, connected cards and similar cases, plus graph algorithms for
finding rings. The finished case is written back into the graph as memory."

**"Can the AI block a card by itself?"**
"No. The AI only recommends. A fixed rule engine decides what's allowed and who
must approve it, and the API checks it again. Risky actions always need a
human."

**"What if the AI is wrong or goes down?"**
"The AI only writes the explanation. The facts come from TigerGraph, and the
decisions come from the rules. If the AI is down, the case still finishes with
the same decision. Only the wording gets simpler."

**"Can it cheat by looking at the future?"**
"No. Every query takes the alert's time as a cutoff, so it can only see data
from before the alert."

**"Is the customer reply real?"**
"It's simulated, and we mark it clearly. In production it would be an SMS or a
call."

**"Why is one case uncertain?"**
"Because the evidence genuinely didn't settle it. Instead of guessing, it says
so, and the policy escalates it to a human analyst."
