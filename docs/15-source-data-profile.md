# Official source data profile

This profile was produced from the official shared Drive folder on 23 September 2026. Raw files remain under `data/raw/` and are ignored by Git. The committed [source manifest](../data/source-manifest.json) records Drive IDs, exact byte counts, and SHA-256 hashes.

## Integrity result

All five downloaded source artifacts match their advertised byte sizes. CSV parsing found no malformed rows. All transaction, identity, closed-case, and exam-case primary IDs are unique.

| File | Rows | Columns | Key result |
|---|---:|---:|---|
| `transactions.csv` | 590,742 | 397 | 590,742 unique transaction IDs; 13,553 customers; no nulls in the seven operational key fields |
| `identity.csv` | 144,432 | 41 | Every identity ID joins to exactly one transaction and every joined transaction is online |
| `closed_cases_history.csv` | 5,565 | 15 | 14,955 transaction references all resolve; `n_txns`, customer, and exposure checks reconcile |
| `case_pack.csv` | 20 | 8 | All anchors exist and match the supplied customer; 11 risk-score, 8 customer-report, and 1 analyst-request triggers |

Transaction time spans `2016-07-02 00:02:21` through `2016-12-31 23:58:54`. There are 439,670 in-person and 151,072 online transactions. Risk scores span 0.01–0.99.

Closed history contains 4,665 confirmed-fraud and 900 cleared cases. Pattern counts are:

| Pattern | Cases |
|---|---:|
| `card_not_present_fraud` | 1,404 |
| `account_takeover` | 1,205 |
| `card_not_present_new_device` | 1,076 |
| `out_of_region_use` | 955 |
| `none` | 900 |
| `card_testing` | 16 |
| `undocumented` | 9 |

Exactly 397 historical cases filed a report.

## Null profile

- `transactions.csv` has 23 complete columns and no fully null column. Only `dist2` (93.63%) and `D7` (93.41%) exceed 90% null.
- `identity.csv` has two complete columns and no fully null column. Nine sparse `id_*` fields exceed 90% null; `DeviceInfo` is absent in 17.71% of identity rows.
- `closed_cases_history.csv` has 13 complete columns. `first_fraud_txn_id` is blank for exactly the 900 cleared cases; `connected_card_ids` is populated in four cases.
- `case_pack.csv` has seven complete columns. `risk_score` is blank in the nine non-risk-score triggers, as specified.

The full per-column null report is generated locally at `data/processed/null-profile.json` and stays outside Git.

## Card identity discovery

`transactions.csv` does not contain the supplied `card_id`. It contains `customer_id` plus `card1`–`card6`. Profiling proves that `card1` is customer-level in this transformed dataset: there are exactly 13,553 `card1` values for 13,553 customers, so using `card1` as the Card vertex key would merge distinct cards.

The supplied card ID is reproduced exactly with this rule:

1. For each customer, collect distinct raw `card6` values across the source data.
2. Sort the raw strings lexically, preserving the empty string as a real category that sorts first.
3. Assign `K1`, `K2`, and `K3` in that order.
4. Form `card_id = customer_id + "-K" + ordinal`.

The source contains 14,317 customer/`card6` pairs: 12,793 customers have one card type, 756 have two, and four have three. Values are `""`, `charge card`, `credit`, `debit`, and `debit or credit`.

This rule matches all 1,913 distinct card mappings evidenced by the 14,955 historical transaction references and all 20 exam anchors with zero conflicts or mismatches. First-seen ordering fails 392 historical mappings and nine exam anchors, so it is explicitly forbidden.

The mapping is a stable identity transform, not an investigation feature. Card vertices may be prepared from the complete source, but `OWNS` visibility, activity, aggregates, and traversals must still respect each case's decision-time cutoff so future activity cannot leak.

## Loading consequences

- Build a deterministic card mapping table from `(customer_id, raw_card6)` to supplied `card_id` before loading transactions.
- Preserve an explicit token for missing `card6` during staging so the empty category is not dropped or reordered.
- Store `card1`–`card6` as source attributes, but use derived `card_id` for `Card` vertices and `MADE` edges.
- Assert all 1,913 historical mappings and all 20 case anchors during preprocessing and after TigerGraph loading.
- Reject a load if any source size/hash, row width, primary ID, reference, exposure, or card mapping check fails.

## Local generated evidence

The ignored files `data/processed/source-profile.json`, `data/processed/null-profile.json`, and `data/processed/card-id-analysis.json` contain the machine-readable profiling output. They can be regenerated when implementation begins; the committed manifest and this report establish the baseline that future transforms must match.
