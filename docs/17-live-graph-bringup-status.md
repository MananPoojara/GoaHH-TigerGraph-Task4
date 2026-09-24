# Live TigerGraph bring-up: status and resume point

Session log for taking the project from "GSQL never run against a live
instance" (see [16-implementation-notes.md](16-implementation-notes.md), "What
is not done") to an actually-running end-to-end system on a Savanna
workspace. If this session is interrupted, resume from **"Next steps"** below
rather than re-deriving the above from scratch.

---

## Done and verified

### Environment / credentials
- `.env`: `TG_HOST` set to the Savanna workspace URL; `TG_USERNAME=temp` /
  `TG_PASSWORD` is a Database Secret that was granted the global `superuser`
  role via `GRANT ROLE superuser TO temp` (run manually in Savanna's Query
  Editor, logged in as the org admin — Database Secrets have no role picker
  at creation time, so this grant is what makes schema/graph creation work).
- `TG_API_TOKEN` cleared. It held a Savanna *management*-plane key (wrong
  format for GSQL's REST token), and `scripts/install_graph.py`'s `connect()`
  prefers `apiToken` over username/password when both are present, so a bad
  token silently broke every request with 401s. Leave it blank unless a real
  GSQL REST token (from `POST /requesttoken`) is generated later.
- `TG_SECRET` removed — unused, not read anywhere in the codebase.
- The workspace originally had a **different, pre-existing `FraudLens` graph**
  from a TigerGraph Marketplace starter template (vertex types like `Case_`,
  `Flagged_txn`, `Transactions` — nothing matching our schema). It was dropped
  with `DROP GRAPH FraudLens CASCADE` (had to be run as the graph's creator,
  `codeforyash@gmail.com`, in Query Editor — `temp` lacked `DROP_GRAPH`).

### GSQL bugs found and fixed (all in `graph/`)
These were genuine bugs, not environment issues — worth knowing about before
touching `graph/schema/` or `graph/queries/` again:

1. **`BOOL DEFAULT true/false` is invalid** on this GSQL parser version in a
   schema `ADD VERTEX` clause. Fixed to `DEFAULT 1` / `DEFAULT 0`
   ([01-schema.gsql](../graph/schema/01-schema.gsql)).
2. **`Case` is a reserved keyword.** The vertex type was renamed to
   `FraudCase` everywhere (schema, all four query files, the loading/derive
   job). Grep for bare `Case` before adding new GSQL — it will still fail.
3. **`count` is a reserved word** (aggregate function) — was used as a
   `FOREACH` loop variable in `detect_region_anomaly`; renamed to
   `region_count`.
4. **Multi-edge-type alternation `-((A|B|C)>)-` did not compile** when the
   source vertex set (`Origin`) was built by conditionally reassigning it to
   different vertex types across `IF`/`ELSE IF` branches. Fixed in
   `get_shared_origin_ring` by (a) seeding `Origin` once as a single
   heterogeneous set (`{DeviceProfile.*, BillingRegion.*, EmailDomain.*}`)
   filtered by `WHERE`, and (b) splitting each multi-edge traversal into
   separate single-edge `SELECT`s unioned together, rather than trying to
   fix the alternation syntax itself.
5. **`AS case`** — `case` is reserved even as an output column alias.
   Renamed the write-back/read-back key to `case_details` everywhere:
   the GSQL (`get_case_history`, `verify_case_bundle`), `fixture.py` (both
   `_q_get_case_history` and `_q_verify_case_bundle`), `persistence.py`
   (`verify_case`), and the golden test that asserted `stored[0]["case"]`.
6. **A hardcoded `TRUE` literal in `INSERT INTO ... VALUES`** failed type
   checking (`'1' is type int` was also rejected — the schema `DEFAULT`
   grammar and the `INSERT VALUES` grammar disagree). The `INSERT VALUES`
   context wants lowercase `true`/`false`; fixed in
   `add_evidence_request`.
7. **The loading job used header-name column refs (`$"col_name"`)** but
   Savanna's GSQL server cannot read a local sample file at job-creation
   time to learn header names (`DEFINE FILENAME f_x;` with no path), so
   every `$"col"` reference failed semantic check. Rewrote
   [01-loading-job.gsql](../graph/loading/01-loading-job.gsql) to use
   positional `$0, $1, ...` indices matching the exact column order written
   by `scripts/prepare_data.py` (documented in a comment above each `LOAD`
   block). This is the *portable* fix — it works identically on Savanna and
   local CE, unlike header-name refs.
8. **Bracket-projected `PRINT` statements without per-column aliases**
   return keys prefixed with the vertex alias, e.g. `PRINT
   TheCase[TheCase.bundle_hash] AS x` returns `{"TheCase.bundle_hash": ...}`,
   not `{"bundle_hash": ...}`. This silently broke read-back verification
   (`written_to_graph` was always `false`) *and* corrupted evidence text
   (`"Flagged transaction None for $0.00..."` — the anchor query's fields
   were all coming back as the wrong key name, so Python's `.get("txn_id")`
   found nothing). Fixed every bracket projection across
   `01-anchor-and-context.gsql`, `03-case-memory.gsql`, and
   `04-case-writeback.gsql` to alias each column explicitly (`Anchor.txn_id
   AS txn_id`, etc.). **If a new bracket-projected `PRINT` is added later,
   it must alias every column or this bug recurs.**
9. **`find_device_connections` never passed `max_devices`** — a required
   GSQL parameter with no default — from `tools.py`, causing `Parameter
   max_devices is NULL` at runtime for every card that has any device
   history. Added `max_devices: int = 50` to the tool wrapper (matches the
   `max_cards: int = 50` convention used by sibling tools).

### Client-side normalization (new, in `graph/client/fraudlens_graph/client.py`)
Added `_flatten_vertex_blocks` / `_flatten_vertex_row`: TigerGraph's REST API
returns vertex rows as `{"v_id":, "v_type":, "attributes": {...}}`, but every
consumer in this codebase (`FixtureGraphClient`, prompts, `persistence.py`)
is written against a **flat** attribute dict. `TigerGraphClient.run()` now
unwraps `attributes` automatically so both backends present the same shape.
This is why the `AS case_details` fix alone wasn't enough for
`verify_case_bundle` — both the alias prefix *and* the `attributes` nesting
had to be fixed.

### Schema, queries, and data — confirmed live
- `graph/schema/01-schema.gsql` applied cleanly: 13 vertex types, 15 edge
  type pairs.
- All 26 queries + 3 algorithms compiled and installed
  (`INSTALL QUERY ALL` → `succeeded: 26, skipped: 0, failed: 0`, run twice —
  once initially, once after the `PRINT`-alias fixes since those touched
  queries that had already been installed).
- Full data load completed via `python scripts/install_graph.py --load`,
  then **independently verified** by direct vertex/edge count queries
  (not by trusting the load script's own "rows posted" log, which uses a
  stats-parsing helper — `_load_stats` in `install_graph.py` — that reads
  the wrong JSON keys and always prints `valid=? rejected=0` regardless of
  what actually happened):

  | Vertex | Count | vs README |
  |---|---|---|
  | Customer | 13,554 | README says 13,553 (+1, unexplained, see below) |
  | Card | 14,318 | README says 14,317 (+1, unexplained) |
  | DeviceProfile | 9,702 | matches |
  | EmailDomain | 60 | — |
  | BillingRegion | 332 | — |
  | Transaction | 590,742 | matches exactly |
  | FraudCase | 5,566 | closed_cases.csv had 5,565 rows (+1) |

  | Edge | Count |
  |---|---|
  | NEXT | 576,425 (matches README exactly) |
  | MADE | 590,742 |
  | OWNS | 14,317 |
  | ABOUT_CUSTOMER / ON_CARD | 5,566 |
  | INVOLVES | 14,955 |

  `link_closed_case_devices` (the derive-links job) ran and wrote 8,404
  links.

  **Note:** the very first `--load` attempt under-counted Transaction
  (576,742) and NEXT (392,797) with no errors reported. Re-posting
  `transactions.csv` a second time (upsert by primary key, so harmless)
  brought both to the correct, README-matching numbers. Root cause not
  confirmed — plausibly a transient issue on Savanna's shared tier during a
  large batch, not a logic bug. If a future full reload shows a similar
  shortfall, re-posting the affected file is the known workaround; investigate
  further if it recurs.

### Application — confirmed working end-to-end
- `python -m uvicorn app.main:app --port 8000` starts cleanly.
  `GET /health` → `graph_backend: "tigergraph"`, `graph_live: true`,
  `llm_available: true`.
- `POST /investigations {"case_id": "HHG-001"}` completed the **full**
  workflow against the live graph: trigger → `get_case_anchor` →
  `get_customer_baseline` → `get_card_window` → pattern-detection queries →
  `find_device_connections` → `find_similar_cases` → assessment →
  evidence-sufficiency check → simulated evidence request → reassessment →
  policy decision → `upsert_case` / `add_case_evidence` / etc. →
  `verify_case_bundle` read-back. Result: `written_to_graph: true`,
  `graph_case_id: "CASE-2016-HHG-001"`, `errors: []`. Evidence claim text
  contains real figures (`"Flagged transaction 3514030 for $77.07 on
  2016-12-04 19:55:28..."`), not the `None`/`$0.00` placeholders seen before
  fix #8 above.
- `cd apps/web && npm run dev` starts cleanly on `:5173` (Vite, no build
  errors). **Not yet opened in a browser** — only the API JSON response has
  been checked, not the rendered UI.
- Gemini (`gemini-3.5-flash`, free tier) is live but rate-limited to 20
  requests/model/day; when the quota is hit mid-run the code falls back to
  deterministic explanation text and the decision is unaffected (by design —
  this is not a bug).

---

## In progress / not yet confirmed

A second full `python scripts/run_benchmark.py` run (all 20 cases) was
started after fixing the `max_devices` bug and is the last thing this session
was waiting on. **The first full run only got 1/20 cases (HHG-001) to
succeed** — HHG-002 through HHG-020 all failed on the same
`find_device_connections: Parameter max_devices is NULL` error, which is now
fixed. Whether the second run's other 19 cases succeed, and whether any
*different* error surfaces on cases that exercise code paths HHG-001 didn't
(e.g. cases that hit `find_high_fanout_origins`, `connected_cards_component`,
`get_correlated_case_triggers`, or `detect_recurring_charge`), was not known
as of this note.

## Next steps (resume here)

1. **Check the second benchmark run's result** (background task, was still
   running). Read `outputs/cases/HHG-*.json` — confirm all 20 files were
   (re)written and check the pass/fail summary table the script prints.
2. **If new per-case errors appear**, they are most likely another missing
   or mismatched tool parameter, the same class of bug as `max_devices`.
   Cross-check every `tools.py` function's parameter dict against its
   corresponding `CREATE OR REPLACE QUERY (...)` signature in
   `graph/queries/` and `graph/algorithms/` — don't wait for each one to
   fail individually.
3. **Open `http://localhost:5173` in an actual browser** and click through
   an investigation. Nothing in the UI has been visually verified yet —
   confirm it calls the running API (check `apps/web`'s API base URL /
   Vite proxy config) and that the panels described in `CLAUDE.md` §27
   (evidence, graph relationships, timeline, actions, approvals) render
   with real data, not placeholders.
4. **Run the test suite**: `python -m pytest tests -q` (174 tests
   documented in the README). The `Case` → `FraudCase` and `case` →
   `case_details` renames touched shared contracts; only the one golden
   test that already referenced `["case"]` was found and fixed — a full
   test run would catch anything missed.
5. **Run formatting/linting** on everything touched this session:
   `python -m ruff check .` and `python -m black --check .` — no formatter
   has been run yet on `tools.py`, `client.py`, `persistence.py`,
   `fixture.py`, or the `.gsql` files.
6. **Optional / low priority:** the +1 discrepancy on Customer/Card/FraudCase
   vertex counts vs. the README's documented numbers. Likely a phantom
   vertex auto-created by an edge in `closed_cases.csv` referencing a
   `customer_id`/`card_id` not present in `customers.csv`/`cards.csv` (GSQL
   auto-creates a bare vertex for an edge's missing endpoint unless told not
   to). Not investigated further — would need to diff `closed_cases.csv`'s
   `customer_id`/`card_id` columns against `customers.csv`/`cards.csv` to
   confirm and decide whether it's worth a `WHERE` guard on the loading job.
7. **Sanity-check the SAR/verdict distribution** across the full 20-case run
   against what the fixture backend previously produced (7 fraud / 12
   legitimate / 1 uncertain, 6 reports — see the root `README.md`'s
   "Status" table, written before any of this session's live-graph work). A
   large deviation on the real graph vs. the fixture would be worth
   understanding; some difference is expected since the live graph surfaces
   real relationships the fixture approximates.
8. **Update `docs/16-implementation-notes.md`**'s "What is not done"
   section — it currently says the GSQL "has not been executed against a
   live TigerGraph instance" and that the loading job "has not run on a live
   instance yet," both now false.
9. **Consider hardening `scripts/install_graph.py`**: `run_gsql_file`'s
   success/failure detection (naive `"error" in text.lower() or "failed" in
   text.lower()`) both (a) false-positived on benign GSQL warnings
   containing the word "margin", and (b) completely missed a real parser
   error (`"Encountered ... at line 70"` contains neither word) earlier this
   session — a schema apply was reported as `01-schema.gsql applied` when it
   had actually failed outright and created nothing. Don't trust this
   script's exit code alone; verify graph state directly (vertex counts,
   `SHOW QUERY <name>`) after any schema/query change.
