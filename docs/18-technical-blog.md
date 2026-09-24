# FraudLens: building a fraud investigator on TigerGraph, not a fraud classifier

*By Team TrustMeBro (Yash, Manan, Priyank), built at Goa Hackerhouse 2026 with @TigerGraphDB and @247pmstudio*

---

## Why we didn't build a classifier

Before Goa Hackerhouse 2026, none of us had used a graph database seriously. The challenge changed that. We were given a bank's card transactions, a history of closed fraud investigations, and 20 open alerts, and asked to build an agent that *investigates*.

That word matters. A classifier looks at one transaction and outputs "fraud: 0.91". But the data warns that most high-scoring alerts are actually legitimate. A real analyst doesn't stop at the score. They ask:

- Does this purchase fit how this customer normally spends?
- Has this device been used on other cards?
- Have we seen this pattern before, and how did that case end?
- Is there an innocent explanation?
- Is it worth calling the customer before blocking the card?

Almost all of those questions are about **relationships**. That's why we built on a graph.

---

## What FraudLens does

Give FraudLens an alert (a risk score, a customer complaint, or an analyst note) and it runs a full investigation:

1. **Confirms the alert makes sense.** Does the transaction exist, belong to that card, and does the card belong to that customer?
2. **Gathers evidence from the graph.** Transaction history, spending baseline, devices, regions, email domains, connected cards.
3. **Tests the known fraud patterns.** Card testing, account takeover, new-device online fraud, out-of-region use, and recurring charges that were disputed but are really legitimate.
4. **Looks for the innocent explanation.** This step is required, not optional.
5. **Retrieves similar past cases** from the bank's closed-case history.
6. **Estimates probability and uncertainty**, then makes an initial decision.
7. **Asks for more evidence only if the answer could change the decision.** For example, it can ask the customer to confirm the purchase. If no possible answer would change the recommended action, it skips the request.
8. **Makes a final decision**, filing a suspicious activity report (SAR) when policy requires one.
9. **Writes the whole case back to TigerGraph**, then reads it back to confirm the write actually happened.

---

## Architecture

```text
            Alert (risk score / complaint / analyst note)
                                │
                                ▼
                   ┌─────────────────────────┐
                   │ LangGraph investigator  │  plan → evidence → counter-evidence
                   │   (stateful workflow)   │  → memory → assess → need more?
                   └────────────┬────────────┘
           business tools only  │  (no raw database access)
                                ▼
                   ┌─────────────────────────┐
                   │ TigerGraph (Savanna)    │  schema, ~26 installed GSQL queries,
                   │ GSQL + graph algorithms │  ring discovery, case memory
                   └────────────┬────────────┘
                                ▼
    ┌──────────────────┐  ┌───────────────────┐  ┌──────────────────────┐
    │ Policy engine    │  │ Evidence simulator│  │ LLM (Gemini)         │
    │ R1–R10, routes   │  │ seeded responses  │  │ planning + prose only│
    │ auto / L1 / L2   │  └───────────────────┘  │ deterministic backup │
    └──────────────────┘                         └──────────────────────┘
                                │
                                ▼
          FastAPI  →  React analyst workbench  +  20 validated answer files
```

Each layer has one job, and a clear list of things it is **not** allowed to do:

| Layer | Owns | Never owns |
|---|---|---|
| TigerGraph + GSQL | Relationships, traversal, pattern evidence, case memory | Fraud verdicts |
| Policy engine | Rules R1–R10, approval routes, when a report is required | Reasoning or graph access |
| LangGraph agent | State, which evidence to gather, when to stop | Approving any action |
| LLM | Planning, summarising, explaining | Facts, policy, IDs, probability |

The split we care about most: **the LLM cannot approve anything.** It can recommend blocking a card. A deterministic policy engine decides whether that action is allowed and who has to approve it: `auto`, a level-1 analyst (`L1`), or a level-2 analyst (`L2`). The API checks this a second time, so a client calling the API directly can't execute an action that needs approval either.

---

## How we used TigerGraph

### The graph model

We didn't turn all 400+ columns in the dataset into vertices. Only the things investigations actually walk through became vertices. The rest stayed as transaction attributes.

- **Core entities:** `Customer`, `Card`, `Transaction`
- **Shared origins:** `DeviceProfile`, `EmailDomain`, `BillingRegion` (how separate cards turn out to be linked)
- **Case memory:** `FraudCase`, `Evidence`, `EvidenceRequest`, `ActionDecision`
- **Key edges:** `OWNS`, `MADE`, `FROM_DEVICE`, `BILLED_IN`, `INVOLVES`, `SIMILAR_TO`, `HAS_EVIDENCE`, `RECOMMENDS`

One detail we liked: a `NEXT` edge links each card's transactions in time order. Looking at "what happened around this transaction" then becomes a short walk along those edges, not a scan of the whole table.

**Data loaded:** 590,742 transactions, 13,553 customers, 14,317 cards, 9,702 device profiles, 576,425 `NEXT` edges, and 5,565 closed historical cases.

### GSQL does the graph work

We had one rule: **if a question is about relationships, TigerGraph answers it.** No Pandas joins, and no asking the LLM to guess whether two accounts are connected. We wrote about 26 installed queries, grouped like this:

- **Anchor and context:** `get_case_anchor`, `get_card_window`, `get_customer_baseline`
- **Pattern detection:** `detect_card_testing`, `detect_account_takeover`, `detect_region_anomaly`, `detect_cnp_burst`, `detect_recurring_charge`
- **Relationships:** `find_device_connections`, `get_shared_origin_ring`
- **Graph algorithms:** `connected_cards_component`, `find_high_fanout_origins`, `refresh_device_fanout`
- **Case memory:** `find_similar_cases`, `get_case_history`, `get_case_graph`
- **Write-back:** `upsert_case`, `add_case_evidence`, `add_action_decision`, `verify_case_bundle`

**Every read query takes a `cutoff` time.** A case opened on 5 December must not see anything from 6 December. We made the cutoff a required parameter rather than a convention, so it can't be forgotten, and it can be tested.

Here is part of `get_shared_origin_ring`, which finds other cards that used the same device, region, or email domain inside the time window:

```sql
RingTxnsByDevice = SELECT t FROM OriginMatch:o -(DEVICE_USED_BY>)- Transaction:t
                   WHERE datetime_diff(cutoff, t.ts) >= 0
                     AND datetime_diff(t.ts, window_start) >= 0;
RingTxnsByRegion = SELECT t FROM OriginMatch:o -(BILLING_REGION_OF>)- Transaction:t
                   WHERE datetime_diff(cutoff, t.ts) >= 0
                     AND datetime_diff(t.ts, window_start) >= 0;
RingTxnsAll = RingTxnsByDevice UNION RingTxnsByRegion UNION RingTxnsByEmail;

RingCards = SELECT c FROM RingTxns:t -(MADE_BY>)- Card:c
            WHERE c.card_id != exclude_card_id
            ACCUM @@connected_cards += c.card_id,
                  @@connected_customers += c.customer_id
            LIMIT max_cards;
```

### MCP: small tools, not a database connection

The agent reaches TigerGraph through tools named after what an investigator does: `find_connected_accounts`, `trace_money_flow`, `find_device_connections`, `find_similar_cases`, and so on. Our own MCP server exposes 12 of these tools, all read-only and all enforcing the cutoff. The official `tigergraph-mcp` server is also registered, restricted to read-only tools.

Writing is deliberately **not** a tool the model can call. A model that can write arbitrary graph data could create its own evidence. Case write-back goes through one checked persistence step instead.

### Evidence that can be checked

Every piece of evidence records its source and the exact query that produced it, for example `query:get_case_anchor(card_id=C12382-K1, customer_id=C12382, txn_id=3514030)`. An analyst can re-run the query and check the claim. Conclusions the agent draws are stored separately and never presented as facts.

### Case memory that has to be earned

When a case closes, FraudLens writes the case, its evidence, evidence requests, actions and links to similar past cases into the graph. Each case gets a fixed ID, so re-running a case overwrites it instead of creating a duplicate. Then `verify_case_bundle` reads it back and compares counts and a hash. The answer file only says `written_to_graph: true` if the two match.

Past bank cases and our agent's own cases are stored the same way, but each is tagged with a trust tier. That way, the agent's own conclusions are never cited as if they were the bank's confirmed outcomes.

---

## Results

We ran all 20 benchmark cases in time order against the live TigerGraph graph, so earlier cases became memory for later ones.

| | |
|---|---|
| Cases investigated | 20 of 20, all passing the answer validator |
| Written to graph and verified by read-back | 20 of 20 |
| Verdicts | 7 fraud, 12 legitimate, 1 uncertain |
| Suspicious activity reports | 6 |
| Graph queries per case | 21–34 |

The mostly-legitimate split is intended. The challenge warns that about half these alerts turn out to be legitimate, and an agent that blocks everything scores badly.

The evidence request made a visible difference. In one case the initial recommendation was to *monitor* the card, and after new evidence it changed to *block* (L1 approval). In another, an initial *block* became *close, no fraud* once the customer confirmed the purchase.

The system also keeps working if the LLM is down. When our free-tier model quota ran out, the explanations fell back to evidence-based template text, and every verdict, action and report stayed the same.

---

## What we learned

**Test data only finds the bugs you expect.** Our small test data passed everything. Real data and a live database found new problems:

- **Fake links.** The most "shared" device profiles were `unknown | unknown | unknown` (1,011 customers) and one very common Windows + Chrome setup (842 customers). Those are common settings, not real devices, but they linked unrelated people. That pushed our report rate to 70%. Requiring a profile to be specific before it can link anyone brought it down to 6 of 20.
- **GSQL surprises on a live instance.** `Case` and `count` are reserved words, so we renamed our vertex type to `FraudCase`. Boolean defaults didn't parse the way we expected. Loading files by column name failed on Savanna because the server can't see our local files, so we switched to column positions. In some query outputs, field names came back prefixed (`TheCase.bundle_hash` instead of `bundle_hash`). That silently broke our write-back check until we renamed every field explicitly.
- **Check the graph directly, not the logs.** Our first bulk load reported success but was missing about 14,000 transactions. Only comparing vertex counts against the source file caught it.

## What's next

- Calibrate the fraud probability against the bank's closed-case history, measured over time.
- Load the policy and regulatory documents into the graph as searchable chunks. The schema for this (`Document`, `DocumentChunk`, `CITES`) is already in place.
- Route the investigator's own tool calls over MCP. Today it calls the same tool functions directly.

---

Thanks to **@TigerGraphDB** and **@247pmstudio** for Goa Hackerhouse 2026. We came in knowing tables and left thinking in graphs. 🙌

*Team TrustMeBro: Yash, Manan, Priyank*
