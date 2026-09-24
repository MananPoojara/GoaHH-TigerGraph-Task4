"""Deterministic identity derivation for Card and DeviceProfile vertices.

Two IDs the graph needs are not present in the source data and must be
reconstructed. Both rules are stable transforms, not investigation features:
they are computed once during loading and asserted against the supplied data
before a load is accepted.

Card IDs
--------
`transactions.csv` carries `customer_id` and `card1`-`card6` but not the
supplied `card_id` (`C01234-K1`). Profiling showed `card1` is customer-level
in this transformed dataset -- 13,553 distinct values for 13,553 customers --
so using it as the card key would merge a customer's separate cards into one.

The rule that reproduces the supplied IDs exactly:

  1. per customer, collect the distinct raw `card6` values;
  2. sort those raw strings lexically, keeping the empty string as a real
     category that sorts first;
  3. assign K1, K2, K3 in that order;
  4. card_id = f"{customer_id}-K{ordinal}".

First-seen ordering is explicitly forbidden: it fails 392 of the historical
mappings and nine of the twenty exam anchors. See
docs/decisions/0006-card-identity-derivation.md.

Device profile IDs
------------------
The README defines a device profile as DeviceInfo + OS + browser + screen. The
same physical profile must always land on the same vertex, so the ID is a hash
of those four fields after normalization, and the readable form is retained
for display and for the answer file's `connected_device_profiles`.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

# Sentinel for a missing card6 during staging. The empty category is real and
# sorts first; it must not be dropped or reordered by a null-handling step.
MISSING_CARD6 = ""

_WHITESPACE_RE = re.compile(r"\s+")

CARD_ID_RE = re.compile(r"^C\d{5}-K\d+$")


def normalize_card6(value: object) -> str:
    """Normalize a raw `card6` cell while preserving the empty category."""
    if value is None:
        return MISSING_CARD6
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null"}:
        return MISSING_CARD6
    return text


def card_ordinals_for_customer(raw_card6_values: Iterable[object]) -> dict[str, int]:
    """Map each distinct raw `card6` value to its K ordinal for one customer.

    Sorting is lexical over the raw strings with the empty value retained, so
    `"" < "charge card" < "credit" < "debit" < "debit or credit"`.
    """
    distinct = {normalize_card6(value) for value in raw_card6_values}
    return {value: index for index, value in enumerate(sorted(distinct), start=1)}


def build_card_id(customer_id: str, ordinal: int) -> str:
    if ordinal < 1:
        raise ValueError(f"card ordinal must be 1 or greater, got {ordinal}")
    return f"{customer_id}-K{ordinal}"


@dataclass
class CardMapping:
    """The complete `(customer_id, raw card6) -> card_id` table.

    Built once from the full source, then asserted against every supplied card
    ID before the load is accepted.
    """

    by_customer: dict[str, dict[str, int]] = field(default_factory=dict)

    def add_observation(self, customer_id: str, raw_card6: object) -> None:
        """Record that this customer was seen with this raw card6 value."""
        value = normalize_card6(raw_card6)
        self.by_customer.setdefault(customer_id, {})[value] = 0

    def finalize(self) -> None:
        """Assign ordinals once every observation has been collected.

        Ordinals cannot be assigned incrementally: the rule sorts the complete
        set of a customer's card6 values, so a value seen later can shift the
        ordinal of one seen earlier.
        """
        for customer_id, values in self.by_customer.items():
            ordered = card_ordinals_for_customer(values.keys())
            self.by_customer[customer_id] = ordered

    def card_id_for(self, customer_id: str, raw_card6: object) -> str:
        """Resolve a transaction row to its supplied-format card ID."""
        value = normalize_card6(raw_card6)
        ordinals = self.by_customer.get(customer_id)
        if ordinals is None:
            raise KeyError(f"customer {customer_id!r} was never observed during staging")
        ordinal = ordinals.get(value)
        if ordinal is None:
            raise KeyError(
                f"card6 {value!r} was never observed for customer {customer_id!r}; "
                "the mapping was built from an incomplete pass over the source"
            )
        return build_card_id(customer_id, ordinal)

    def all_card_ids(self) -> set[str]:
        return {
            build_card_id(customer_id, ordinal)
            for customer_id, ordinals in self.by_customer.items()
            for ordinal in ordinals.values()
        }

    @property
    def customer_count(self) -> int:
        return len(self.by_customer)

    @property
    def pair_count(self) -> int:
        return sum(len(values) for values in self.by_customer.values())


@dataclass
class MappingAssertion:
    """The result of checking derived card IDs against supplied ones."""

    checked: int = 0
    matched: int = 0
    mismatches: list[tuple[str, str, str]] = field(default_factory=list)
    unresolvable: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.mismatches and not self.unresolvable

    def summary(self) -> str:
        if self.ok:
            return f"card mapping verified: {self.matched}/{self.checked} supplied IDs reproduced"
        return (
            f"card mapping FAILED: {self.matched}/{self.checked} reproduced, "
            f"{len(self.mismatches)} mismatched, {len(self.unresolvable)} unresolvable"
        )


def assert_supplied_card_ids(
    mapping: CardMapping,
    supplied: Iterable[tuple[str, str]],
) -> MappingAssertion:
    """Check that every supplied `(customer_id, card_id)` pair is reproducible.

    A supplied card ID is reproducible when the derived ordinals for that
    customer include the ordinal the supplied ID names. This is the gate that
    proves the derivation rule before any transaction is loaded.
    """
    result = MappingAssertion()
    for customer_id, card_id in supplied:
        result.checked += 1
        if not CARD_ID_RE.match(card_id):
            result.unresolvable.append((customer_id, card_id))
            continue
        ordinals = mapping.by_customer.get(customer_id)
        if not ordinals:
            result.unresolvable.append((customer_id, card_id))
            continue
        derived = {build_card_id(customer_id, ordinal) for ordinal in ordinals.values()}
        if card_id in derived:
            result.matched += 1
        else:
            result.mismatches.append((customer_id, card_id, ",".join(sorted(derived))))
    return result


# ---------------------------------------------------------------------------
# Device profiles
# ---------------------------------------------------------------------------


def _normalize_component(value: object) -> str:
    """Lowercase, collapse whitespace, and blank out nulls."""
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return _WHITESPACE_RE.sub(" ", text).lower()


def device_profile_readable(
    device_info: object, os: object, browser: object, screen: object
) -> str:
    """The display form used in `connected_device_profiles`.

    Matches the shape the README example uses:
    `SAMSUNG SM-G892A Build/NRD90M | Android 7.0 | samsung browser 6.2 | 2220x1080`.
    Original casing is kept here; only the hashed key is normalized.
    """
    parts = []
    for value in (device_info, os, browser, screen):
        text = "" if value is None else str(value).strip()
        if text.lower() in {"nan", "none", "null"}:
            text = ""
        parts.append(text or "unknown")
    return " | ".join(parts)


def device_profile_id(device_info: object, os: object, browser: object, screen: object) -> str:
    """A stable 16-hex-character ID for one device profile.

    Hashing the normalized components keeps the ID stable across casing and
    whitespace differences in `DeviceInfo`, which is free text in the source.
    """
    normalized = "|".join(
        _normalize_component(value) for value in (device_info, os, browser, screen)
    )
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"D{digest[:16]}"


def device_profile_from_identity_row(row: Mapping[str, object]) -> tuple[str, str]:
    """Derive `(device_id, readable)` from one `identity.csv` row.

    Uses the README's named identity columns: `DeviceInfo`, `id_30` (OS),
    `id_31` (browser), and `id_33` (screen).
    """
    device_info = row.get("DeviceInfo")
    os = row.get("id_30")
    browser = row.get("id_31")
    screen = row.get("id_33")
    return (
        device_profile_id(device_info, os, browser, screen),
        device_profile_readable(device_info, os, browser, screen),
    )
