"""Whether a device profile actually identifies anything.

A device profile is DeviceInfo + OS + browser + screen. Some of those
combinations name a specific device; most do not. In the official data the
most-shared profiles are:

    1011 customers   unknown | unknown | unknown | unknown
     842 customers   Windows | Windows 10 | chrome 63.0 | 1920x1080
     697 customers   unknown | unknown | mobile safari generic | unknown

Those are popular *configurations*, not shared devices. Half of all profiles
(50.6%) are used by exactly one customer and genuinely identify something; the
long tail at the top identifies nothing at all.

This distinction matters because it decides whether two cardholders are
"connected". Treating a Windows/Chrome/1920x1080 profile as a link would
connect hundreds of unrelated people, and under policy 3a that connection is
one of the predicates that triggers a regulatory filing. Without this guard
the system files reports on most of the benchmark, against a bank history
where 397 of 5,565 cases (7%) warranted one.

Guilt by association is the failure mode the whole design warns about. This is
where it would actually happen.
"""

from __future__ import annotations

from dataclasses import dataclass

# Components that carry no identifying information.
_EMPTY_COMPONENTS = {"", "unknown", "nan", "none", "null", "other"}

# Generic device descriptors: a platform name, not a device.
_GENERIC_DEVICE_INFO = {
    "windows",
    "macos",
    "ios device",
    "trident/7.0",
    "rv:11.0",
    "linux",
    "android",
    "other",
}

# A profile shared by more than this many customers is a common configuration
# rather than an identifying device. The observed distribution puts the 90th
# percentile at 10 customers and the 95th at 22, so a profile above this sits
# in the tail where profiles stop distinguishing people. A genuine fraud ring
# in this data spans a handful of cards, well inside the limit.
MAX_LINKING_CUSTOMER_FANOUT = 10

# A profile needs at least this many meaningful components to identify a
# device at all.
MIN_IDENTIFYING_COMPONENTS = 2


@dataclass(frozen=True)
class DeviceAssessment:
    """Whether a profile may be used to connect cardholders, and why not."""

    device_id: str
    readable: str
    customer_fanout: int
    identifying: bool
    reason: str


def _components(readable: str) -> list[str]:
    return [part.strip().lower() for part in readable.split("|")]


def known_component_count(readable: str) -> int:
    """How many of the four components carry real information."""
    return sum(1 for part in _components(readable) if part not in _EMPTY_COMPONENTS)


def is_generic_profile(readable: str) -> bool:
    """Whether the profile names only a platform rather than a device."""
    parts = _components(readable)
    if not parts:
        return True
    device_info = parts[0]
    if device_info in _EMPTY_COMPONENTS:
        return True
    return device_info in _GENERIC_DEVICE_INFO and known_component_count(readable) < 4


def assess_device(
    device_id: str,
    readable: str,
    customer_fanout: int,
    *,
    max_fanout: int = MAX_LINKING_CUSTOMER_FANOUT,
) -> DeviceAssessment:
    """Decide whether this profile may link one cardholder to another."""
    known = known_component_count(readable)

    if known < MIN_IDENTIFYING_COMPONENTS:
        return DeviceAssessment(
            device_id,
            readable,
            customer_fanout,
            False,
            f"the profile has only {known} identifiable component(s), so it does not "
            "describe a specific device",
        )

    if customer_fanout > max_fanout:
        return DeviceAssessment(
            device_id,
            readable,
            customer_fanout,
            False,
            f"the profile is shared by {customer_fanout} customers, which makes it a "
            "common configuration rather than an identifying device",
        )

    if is_generic_profile(readable) and customer_fanout > 2:
        return DeviceAssessment(
            device_id,
            readable,
            customer_fanout,
            False,
            "the profile names a platform rather than a specific device",
        )

    return DeviceAssessment(
        device_id,
        readable,
        customer_fanout,
        True,
        f"the profile is specific and appears on only {customer_fanout} customer(s)",
    )


def select_linking_device(rows: list[dict]) -> DeviceAssessment | None:
    """Pick the profile best able to connect this card to others.

    Chooses the widest-reaching profile that is still identifying. Choosing
    the widest profile outright would reliably select the most generic one,
    which is the opposite of what an investigation wants.
    """
    assessments = [
        assess_device(
            row.get("device_id", ""),
            row.get("readable", "") or row.get("device_id", ""),
            int(row.get("customer_fanout", 0) or 0),
        )
        for row in rows
    ]
    linking = [item for item in assessments if item.identifying and item.customer_fanout >= 2]
    if not linking:
        return None
    return max(linking, key=lambda item: item.customer_fanout)
