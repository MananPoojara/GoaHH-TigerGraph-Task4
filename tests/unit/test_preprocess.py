"""Preprocessing tests against the synthetic fixture dataset.

The fixture has the real column structure and planted scenarios, so these
tests check the reshaping contract -- reconciliation, ordering, joins, and the
online-only identity rule -- without needing the 708 MB official file.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from fraudlens_loading import preprocess, write_fixture_dataset


@pytest.fixture(scope="module")
def processed(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    root = tmp_path_factory.mktemp("fraudlens")
    raw, out = root / "raw", root / "processed"
    write_fixture_dataset(raw)
    preprocess(raw, out)
    return raw, out


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_every_source_row_is_accepted_or_rejected(tmp_path: Path) -> None:
    """Counts must reconcile: accepted + rejected == source rows."""
    raw, out = tmp_path / "raw", tmp_path / "processed"
    counts = write_fixture_dataset(raw)
    report = preprocess(raw, out)
    assert report.transaction_rows == counts["transactions.csv"]
    assert report.accepted_rows + report.rejected_rows == report.transaction_rows
    assert report.rejected_rows == 0, report.rejections


def test_missing_source_file_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="transactions.csv"):
        preprocess(tmp_path / "empty", tmp_path / "out")


def test_multi_card_customer_gets_lexical_ordinals(processed: tuple[Path, Path]) -> None:
    """FIXC05 holds a credit and a debit card; credit sorts first."""
    _, out = processed
    cards = {row["card_id"]: row for row in read_rows(out / "cards.csv")}
    assert cards["FIXC05-K1"]["card_type"] == "credit"
    assert cards["FIXC05-K2"]["card_type"] == "debit"


def test_every_transaction_resolves_to_a_known_card(processed: tuple[Path, Path]) -> None:
    _, out = processed
    card_ids = {row["card_id"] for row in read_rows(out / "cards.csv")}
    for row in read_rows(out / "transactions.csv"):
        assert row["card_id"] in card_ids


def test_card_counts_sum_to_the_transaction_count(processed: tuple[Path, Path]) -> None:
    _, out = processed
    txn_count = len(read_rows(out / "transactions.csv"))
    card_total = sum(int(row["txn_count"]) for row in read_rows(out / "cards.csv"))
    assert card_total == txn_count


def test_next_edges_form_one_chain_per_card(processed: tuple[Path, Path]) -> None:
    """A card with n transactions yields exactly n-1 NEXT edges."""
    _, out = processed
    cards = read_rows(out / "cards.csv")
    expected = sum(int(row["txn_count"]) - 1 for row in cards)
    assert len(read_rows(out / "next_edges.csv")) == expected


def test_next_edges_never_go_backwards(processed: tuple[Path, Path]) -> None:
    _, out = processed
    timestamps = {row["txn_id"]: row["ts"] for row in read_rows(out / "transactions.csv")}
    for edge in read_rows(out / "next_edges.csv"):
        assert timestamps[edge["from_txn_id"]] <= timestamps[edge["to_txn_id"]]
        assert int(edge["gap_seconds"]) >= 0


def test_next_edges_stay_within_one_card(processed: tuple[Path, Path]) -> None:
    _, out = processed
    card_of = {row["txn_id"]: row["card_id"] for row in read_rows(out / "transactions.csv")}
    for edge in read_rows(out / "next_edges.csv"):
        assert card_of[edge["from_txn_id"]] == card_of[edge["to_txn_id"]] == edge["card_id"]


def test_only_online_transactions_carry_a_device(processed: tuple[Path, Path]) -> None:
    """ProductCD W is in-person and has no identity record, per the README."""
    _, out = processed
    for row in read_rows(out / "transactions.csv"):
        if row["channel"] == "in_person":
            assert row["device_profile_id"] == "", row["txn_id"]


def test_the_planted_card_testing_sequence_survives_preprocessing(
    processed: tuple[Path, Path],
) -> None:
    _, out = processed
    rows = [
        row
        for row in read_rows(out / "transactions.csv")
        if row["card_id"] == "FIXC02-K1" and row["channel"] == "online"
    ]
    small = [row for row in rows if abs(float(row["amount"])) <= 5.0]
    large = [row for row in rows if abs(float(row["amount"])) > 100.0]
    assert len(small) == 3, "three sub-$5 authorizations were planted"
    assert len(large) == 1, "one larger purchase was planted"
    assert all(row["device_is_new"] == "true" for row in rows)


def test_the_planted_device_ring_spans_two_customers(processed: tuple[Path, Path]) -> None:
    _, out = processed
    devices = {row["device_id"]: row for row in read_rows(out / "devices.csv")}
    shared = [row for row in devices.values() if int(row["customer_fanout"]) >= 2]
    assert shared, "a device profile shared across two customers was planted"
    assert any("iPhone" in row["readable"] for row in shared)


def test_the_planted_novel_region_is_present(processed: tuple[Path, Path]) -> None:
    _, out = processed
    regions = {
        row["addr1"]
        for row in read_rows(out / "transactions.csv")
        if row["customer_id"] == "FIXC05"
    }
    assert {"512", "887"} <= regions, "home and away regions were planted"


def test_device_profiles_are_deduplicated_by_content(processed: tuple[Path, Path]) -> None:
    """Two distinct profiles were planted; identical ones must collapse."""
    _, out = processed
    devices = read_rows(out / "devices.csv")
    assert len(devices) == 2
    assert len({row["device_id"] for row in devices}) == 2


def test_amounts_are_preserved_exactly(processed: tuple[Path, Path]) -> None:
    raw, out = processed
    source = {
        row["TransactionID"]: float(row["TransactionAmt"])
        for row in read_rows(raw / "transactions.csv")
    }
    for row in read_rows(out / "transactions.csv"):
        assert float(row["amount"]) == pytest.approx(source[row["txn_id"]], abs=1e-4)


def test_transaction_ids_stay_strings_and_are_unique(processed: tuple[Path, Path]) -> None:
    _, out = processed
    ids = [row["txn_id"] for row in read_rows(out / "transactions.csv")]
    assert len(ids) == len(set(ids))
    assert all(isinstance(value, str) and value for value in ids)
