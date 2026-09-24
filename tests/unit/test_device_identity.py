"""Device-profile specificity tests.

The values below are taken from the official data, where the most-shared
profiles are generic configurations rather than devices. Getting this wrong
connects unrelated cardholders, and under policy 3a a connection is one of the
predicates that triggers a regulatory filing — so an error here shows up as
the system filing reports it should not.
"""

from __future__ import annotations

import pytest
from fraudlens_investigator.device_identity import (
    MAX_LINKING_CUSTOMER_FANOUT,
    assess_device,
    is_generic_profile,
    known_component_count,
    select_linking_device,
)

# Real profiles from the official dataset, with their true customer fan-out.
ALL_UNKNOWN = "unknown | unknown | unknown | unknown"
WINDOWS_CHROME = "Windows | Windows 10 | chrome 63.0 | 1920x1080"
MOBILE_SAFARI_GENERIC = "unknown | unknown | mobile safari generic | unknown"
SPECIFIC_SAMSUNG = "SAMSUNG SM-G892A Build/NRD90M | Android 7.0 | samsung browser 6.2 | 2220x1080"


def test_component_counting_ignores_unknowns() -> None:
    assert known_component_count(ALL_UNKNOWN) == 0
    assert known_component_count(MOBILE_SAFARI_GENERIC) == 1
    assert known_component_count(WINDOWS_CHROME) == 4
    assert known_component_count(SPECIFIC_SAMSUNG) == 4


def test_an_all_unknown_profile_never_links() -> None:
    """1,011 customers share this profile in the official data."""
    result = assess_device("D1", ALL_UNKNOWN, 1011)
    assert not result.identifying
    assert "identifiable component" in result.reason


def test_a_popular_configuration_never_links() -> None:
    """842 customers share Windows 10 / Chrome 63 / 1920x1080."""
    result = assess_device("D2", WINDOWS_CHROME, 842)
    assert not result.identifying
    assert "common configuration" in result.reason


def test_a_specific_profile_on_a_few_cards_does_link() -> None:
    result = assess_device("D3", SPECIFIC_SAMSUNG, 3)
    assert result.identifying
    assert "specific" in result.reason


@pytest.mark.parametrize(
    ("fanout", "expected"),
    [
        (MAX_LINKING_CUSTOMER_FANOUT, True),
        (MAX_LINKING_CUSTOMER_FANOUT + 1, False),
    ],
)
def test_fanout_ceiling_is_inclusive(fanout: int, expected: bool) -> None:
    assert assess_device("D4", SPECIFIC_SAMSUNG, fanout).identifying is expected


def test_generic_platform_names_are_recognised() -> None:
    assert is_generic_profile(ALL_UNKNOWN)
    assert is_generic_profile("Windows | unknown | chrome 63.0 | unknown")
    assert not is_generic_profile(SPECIFIC_SAMSUNG)


def test_selection_prefers_reach_but_only_among_identifying_profiles() -> None:
    """The widest profile outright would be the most generic one."""
    rows = [
        {"device_id": "D1", "readable": ALL_UNKNOWN, "customer_fanout": 1011},
        {"device_id": "D2", "readable": WINDOWS_CHROME, "customer_fanout": 842},
        {"device_id": "D3", "readable": SPECIFIC_SAMSUNG, "customer_fanout": 4},
        {
            "device_id": "D4",
            "readable": "iPhone | iOS 11.1.2 | safari 11.0 | 1334x750",
            "customer_fanout": 2,
        },
    ]
    selected = select_linking_device(rows)
    assert selected is not None
    assert selected.device_id == "D3", "the widest *identifying* profile wins"


def test_selection_returns_nothing_when_only_generic_profiles_exist() -> None:
    rows = [
        {"device_id": "D1", "readable": ALL_UNKNOWN, "customer_fanout": 1011},
        {"device_id": "D2", "readable": WINDOWS_CHROME, "customer_fanout": 842},
    ]
    assert select_linking_device(rows) is None


def test_a_profile_on_one_customer_links_nothing() -> None:
    """Half of all profiles are used by exactly one customer; they identify a
    device but connect no one."""
    rows = [{"device_id": "D3", "readable": SPECIFIC_SAMSUNG, "customer_fanout": 1}]
    assert select_linking_device(rows) is None
