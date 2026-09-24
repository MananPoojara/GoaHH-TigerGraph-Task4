"""Card and device identity derivation tests.

The card rule is the one place a silent error would corrupt every downstream
ID in every answer file, so the forbidden alternative (first-seen ordering) is
tested explicitly as a counterexample rather than merely documented.
"""

from __future__ import annotations

import pytest
from fraudlens_loading.identity import (
    CardMapping,
    assert_supplied_card_ids,
    build_card_id,
    card_ordinals_for_customer,
    device_profile_id,
    device_profile_readable,
    normalize_card6,
)

# --------------------------------------------------------------------------
# card6 normalization
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("credit", "credit"),
        ("  debit  ", "debit"),
        ("", ""),
        (None, ""),
        ("nan", ""),
        ("NaN", ""),
    ],
)
def test_normalize_card6(raw: object, expected: str) -> None:
    assert normalize_card6(raw) == expected


def test_empty_card6_is_a_real_category_that_sorts_first() -> None:
    ordinals = card_ordinals_for_customer(["credit", "", "debit"])
    assert ordinals[""] == 1
    assert ordinals["credit"] == 2
    assert ordinals["debit"] == 3


def test_documented_card6_vocabulary_orders_lexically() -> None:
    """The five values the source profile found, in the order the rule assigns."""
    ordinals = card_ordinals_for_customer(["debit or credit", "credit", "charge card", "", "debit"])
    assert ordinals == {
        "": 1,
        "charge card": 2,
        "credit": 3,
        "debit": 4,
        "debit or credit": 5,
    }


def test_ordinals_are_independent_of_observation_order() -> None:
    """The rule sorts the complete set, so input order must not matter.

    This is the property that makes first-seen ordering wrong: it produces a
    different answer for the same customer depending on which row was read
    first.
    """
    forward = card_ordinals_for_customer(["credit", "debit"])
    reverse = card_ordinals_for_customer(["debit", "credit"])
    assert forward == reverse == {"credit": 1, "debit": 2}


def test_first_seen_ordering_would_disagree_and_is_not_what_we_do() -> None:
    mapping = CardMapping()
    # "debit" is observed first, but lexical ordering still puts credit at K1.
    mapping.add_observation("C00001", "debit")
    mapping.add_observation("C00001", "credit")
    mapping.finalize()
    assert mapping.card_id_for("C00001", "credit") == "C00001-K1"
    assert mapping.card_id_for("C00001", "debit") == "C00001-K2"


# --------------------------------------------------------------------------
# CardMapping
# --------------------------------------------------------------------------


def test_build_card_id_format() -> None:
    assert build_card_id("C12382", 1) == "C12382-K1"
    assert build_card_id("C08623", 2) == "C08623-K2"


def test_build_card_id_rejects_zero_ordinal() -> None:
    with pytest.raises(ValueError, match="1 or greater"):
        build_card_id("C00001", 0)


def test_mapping_resolves_multi_card_customers() -> None:
    mapping = CardMapping()
    for value in ("credit", "debit", ""):
        mapping.add_observation("C00877", value)
    mapping.add_observation("C00259", "credit")
    mapping.finalize()

    assert mapping.card_id_for("C00877", "") == "C00877-K1"
    assert mapping.card_id_for("C00877", "credit") == "C00877-K2"
    assert mapping.card_id_for("C00877", "debit") == "C00877-K3"
    assert mapping.card_id_for("C00259", "credit") == "C00259-K1"
    assert mapping.customer_count == 2
    assert mapping.pair_count == 4


def test_mapping_rejects_an_unobserved_customer() -> None:
    mapping = CardMapping()
    mapping.finalize()
    with pytest.raises(KeyError, match="never observed"):
        mapping.card_id_for("C99999", "credit")


def test_mapping_rejects_an_unobserved_card6_value() -> None:
    mapping = CardMapping()
    mapping.add_observation("C00001", "credit")
    mapping.finalize()
    with pytest.raises(KeyError, match="never observed"):
        mapping.card_id_for("C00001", "debit")


def test_assertion_passes_when_supplied_ids_are_reproduced() -> None:
    mapping = CardMapping()
    mapping.add_observation("C12382", "credit")
    mapping.add_observation("C08623", "credit")
    mapping.add_observation("C08623", "debit")
    mapping.finalize()

    result = assert_supplied_card_ids(mapping, [("C12382", "C12382-K1"), ("C08623", "C08623-K2")])
    assert result.ok, result.summary()
    assert result.matched == 2


def test_assertion_fails_when_a_supplied_ordinal_cannot_exist() -> None:
    mapping = CardMapping()
    mapping.add_observation("C12382", "credit")  # only K1 is possible
    mapping.finalize()

    result = assert_supplied_card_ids(mapping, [("C12382", "C12382-K2")])
    assert not result.ok
    assert result.mismatches


def test_assertion_flags_an_unknown_customer() -> None:
    mapping = CardMapping()
    mapping.finalize()
    result = assert_supplied_card_ids(mapping, [("C99999", "C99999-K1")])
    assert not result.ok
    assert result.unresolvable


# --------------------------------------------------------------------------
# Device profiles
# --------------------------------------------------------------------------


def test_device_id_is_stable_across_casing_and_whitespace() -> None:
    first = device_profile_id(
        "SAMSUNG SM-G892A Build/NRD90M", "Android 7.0", "chrome 62", "1920x1080"
    )
    second = device_profile_id(
        "samsung  sm-g892a build/nrd90m", "ANDROID 7.0", "Chrome 62", "1920x1080"
    )
    assert first == second


def test_different_profiles_get_different_ids() -> None:
    android = device_profile_id("SM-G892A", "Android 7.0", "chrome 62", "1920x1080")
    ios = device_profile_id("iPhone", "iOS 11.0", "safari 11", "1334x750")
    assert android != ios


def test_device_id_has_a_stable_prefix_and_length() -> None:
    value = device_profile_id("SM-G892A", "Android 7.0", "chrome 62", "1920x1080")
    assert value.startswith("D")
    assert len(value) == 17


def test_readable_form_matches_the_readme_shape() -> None:
    readable = device_profile_readable(
        "SAMSUNG SM-G892A Build/NRD90M", "Android 7.0", "samsung browser 6.2", "2220x1080"
    )
    assert readable == (
        "SAMSUNG SM-G892A Build/NRD90M | Android 7.0 | samsung browser 6.2 | 2220x1080"
    )


def test_missing_components_become_unknown_not_blank() -> None:
    readable = device_profile_readable("SM-G892A", None, "nan", "")
    assert readable == "SM-G892A | unknown | unknown | unknown"


def test_missing_device_info_still_yields_a_stable_id() -> None:
    """17.71% of identity rows have no DeviceInfo; they must still group."""
    first = device_profile_id(None, "Android 7.0", "chrome 62", "1920x1080")
    second = device_profile_id("", "Android 7.0", "chrome 62", "1920x1080")
    assert first == second
