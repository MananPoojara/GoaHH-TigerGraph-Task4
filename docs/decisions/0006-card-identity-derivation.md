# ADR-0006: Derive card identity from customer and lexical card type

**Status:** Accepted — 23 September 2026

## Context

Exam and historical cases use IDs such as `C08623-K2`, but transactions provide only `customer_id` and `card1`–`card6`. Treating `card1` as the card key would merge cards: it is one-to-one with customer in this transformed dataset. Full card-field signatures are also unstable because fields such as `card2` and `card5` vary within a supplied card ID.

## Decision

For each customer, collect distinct raw `card6` strings, sort them lexically with the empty string preserved, and assign `K1` onward. Use `customer_id-Kn` as the Card vertex ID. Keep the raw fields as attributes and retain a versioned mapping table.

The rule was validated against 1,913 distinct historical card mappings and all 20 exam anchors with zero mismatches. First-seen ordering was rejected because it mismatched 392 historical mappings and nine exam anchors.

## Consequences

Transactions can be attached to the exact card IDs required by the challenge, including customers with two or three cards. Loading must preserve empty `card6` values and fail on mapping drift. Temporal queries still hide activity after the case cutoff even though the stable identity mapping is prepared from the full source.
