"""Source verification, identity derivation, and load-file generation."""

from .fixtures import write_fixture_dataset
from .identity import (
    CardMapping,
    MappingAssertion,
    assert_supplied_card_ids,
    build_card_id,
    card_ordinals_for_customer,
    device_profile_from_identity_row,
    device_profile_id,
    device_profile_readable,
    normalize_card6,
)
from .preprocess import PreprocessReport, build_card_mapping, preprocess
from .verify import IntegrityReport, sha256_of, verify_sources

__all__ = [
    "CardMapping",
    "IntegrityReport",
    "MappingAssertion",
    "PreprocessReport",
    "assert_supplied_card_ids",
    "build_card_id",
    "build_card_mapping",
    "card_ordinals_for_customer",
    "device_profile_from_identity_row",
    "device_profile_id",
    "device_profile_readable",
    "normalize_card6",
    "preprocess",
    "sha256_of",
    "verify_sources",
    "write_fixture_dataset",
]
