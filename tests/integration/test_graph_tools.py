"""Graph tool semantics against the fixture backend.

These assert the contract every backend must honour: planted scenarios are
found, cutoffs are obeyed, and results carry a replayable receipt. The same
assertions are the basis for the TigerGraph integration suite once a live
workspace exists, which is how backend drift gets caught.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from fraudlens_graph import FixtureGraphClient, GraphError, tools
from fraudlens_loading import preprocess, write_fixture_dataset

# The fixture generator starts at 2016-11-01 08:00 and plants scenarios at
# known offsets; these are the instants just after each planted event.
AFTER_CARD_TESTING = datetime(2016, 11, 16, 19, 0, 0)
BEFORE_CARD_TESTING = datetime(2016, 11, 16, 17, 0, 0)
AFTER_RING = datetime(2016, 11, 18, 23, 0, 0)
AFTER_AWAY_REGION = datetime(2016, 11, 19, 6, 0, 0)


@pytest.fixture(scope="module")
def graph(tmp_path_factory: pytest.TempPathFactory) -> FixtureGraphClient:
    root = tmp_path_factory.mktemp("graph")
    raw, out = root / "raw", root / "processed"
    write_fixture_dataset(raw)
    preprocess(raw, out)
    return FixtureGraphClient(out)


# --------------------------------------------------------------------------
# Anchor integrity
# --------------------------------------------------------------------------


def test_anchor_confirms_a_consistent_trigger(graph: FixtureGraphClient) -> None:
    testing = tools.detect_card_testing(
        graph, card_id="FIXC02-K1", cutoff=AFTER_CARD_TESTING, window_hours=6
    )
    txn_id = testing.data["larger_txn_ids"][0]

    result = tools.get_case_anchor(
        graph,
        txn_id=txn_id,
        card_id="FIXC02-K1",
        customer_id="FIXC02",
        cutoff=AFTER_CARD_TESTING,
    )
    assert result.data["integrity_errors"] == []
    assert result.data["anchor"][0]["txn_id"] == txn_id


def test_anchor_rejects_a_mismatched_card(graph: FixtureGraphClient) -> None:
    """A trigger naming the wrong card must fail at intake, not be investigated."""
    testing = tools.detect_card_testing(
        graph, card_id="FIXC02-K1", cutoff=AFTER_CARD_TESTING, window_hours=6
    )
    txn_id = testing.data["larger_txn_ids"][0]

    result = tools.get_case_anchor(
        graph,
        txn_id=txn_id,
        card_id="FIXC01-K1",
        customer_id="FIXC01",
        cutoff=AFTER_CARD_TESTING,
    )
    assert result.data["integrity_errors"], "a mismatched card must be reported"


def test_anchor_reports_a_missing_transaction(graph: FixtureGraphClient) -> None:
    result = tools.get_case_anchor(
        graph,
        txn_id="does-not-exist",
        card_id="FIXC01-K1",
        customer_id="FIXC01",
        cutoff=AFTER_CARD_TESTING,
    )
    assert "flagged transaction not found" in result.data["integrity_errors"]


# --------------------------------------------------------------------------
# Planted scenarios
# --------------------------------------------------------------------------


def test_card_testing_sequence_is_found(graph: FixtureGraphClient) -> None:
    result = tools.detect_card_testing(
        graph, card_id="FIXC02-K1", cutoff=AFTER_CARD_TESTING, window_hours=6
    )
    assert result.data["small_online_count"] == 3
    assert len(result.data["larger_txn_ids"]) == 1


def test_shared_device_links_two_customers(graph: FixtureGraphClient) -> None:
    devices = tools.find_device_connections(graph, card_id="FIXC03-K1", cutoff=AFTER_RING)
    assert devices.data["devices"], "the planted ring device must be found"
    device_id = devices.data["devices"][0]["device_id"]

    ring = tools.find_connected_accounts(
        graph,
        origin_kind="device",
        origin_id=device_id,
        cutoff=AFTER_RING,
        exclude_card_id="FIXC03-K1",
    )
    assert "FIXC04-K1" in ring.data["connected_cards"]
    assert "FIXC04" in ring.data["connected_customers"]


def test_novel_region_is_found_with_home_activity_continuing(
    graph: FixtureGraphClient,
) -> None:
    result = tools.detect_region_anomaly(
        graph, customer_id="FIXC05", cutoff=AFTER_AWAY_REGION, window_hours=24
    )
    assert "887" in result.data["novel_regions"]


def test_money_flow_expands_to_the_connected_card(graph: FixtureGraphClient) -> None:
    result = tools.trace_money_flow(
        graph,
        seed_card_id="FIXC03-K1",
        window_start=datetime(2016, 11, 1, 0, 0, 0),
        window_end=AFTER_RING,
    )
    assert "FIXC04-K1" in result.data["component_cards"]
    assert result.data["component_size"] >= 2


def test_legitimate_control_customer_shows_no_ring(graph: FixtureGraphClient) -> None:
    result = tools.find_device_connections(graph, card_id="FIXC01-K1", cutoff=AFTER_RING)
    assert result.data["devices"] == [], "the control customer transacts in person only"


# --------------------------------------------------------------------------
# Temporal integrity
# --------------------------------------------------------------------------


def test_cutoff_hides_activity_that_has_not_happened_yet(
    graph: FixtureGraphClient,
) -> None:
    before = tools.detect_card_testing(
        graph, card_id="FIXC02-K1", cutoff=BEFORE_CARD_TESTING, window_hours=6
    )
    assert before.data["small_online_count"] == 0

    after = tools.detect_card_testing(
        graph, card_id="FIXC02-K1", cutoff=AFTER_CARD_TESTING, window_hours=6
    )
    assert after.data["small_online_count"] == 3


def test_window_is_clamped_to_the_cutoff(graph: FixtureGraphClient) -> None:
    """hours_after must never reveal activity past the decision time."""
    result = tools.get_transaction_history(
        graph,
        card_id="FIXC02-K1",
        anchor_ts=BEFORE_CARD_TESTING,
        cutoff=BEFORE_CARD_TESTING,
        hours_after=720,
    )
    assert result.data["window_end"] <= BEFORE_CARD_TESTING.strftime("%Y-%m-%d %H:%M:%S")
    for entry in result.data["window"]:
        assert entry["ts"] <= result.data["window_end"]


def test_baseline_excludes_the_cutoff_instant(graph: FixtureGraphClient) -> None:
    """A baseline must not include the transaction it is compared against."""
    result = tools.get_customer_baseline(graph, customer_id="FIXC02", cutoff=BEFORE_CARD_TESTING)
    assert result.data["cutoff"] == BEFORE_CARD_TESTING.strftime("%Y-%m-%d %H:%M:%S")
    assert result.data["txn_count"] > 0


# --------------------------------------------------------------------------
# Provenance and safety
# --------------------------------------------------------------------------


def test_every_result_carries_a_replayable_receipt(graph: FixtureGraphClient) -> None:
    result = tools.detect_card_testing(
        graph, card_id="FIXC02-K1", cutoff=AFTER_CARD_TESTING, window_hours=6
    )
    receipt = result.receipt
    assert receipt is not None
    assert receipt.query == "detect_card_testing"
    assert receipt.cutoff == AFTER_CARD_TESTING.strftime("%Y-%m-%d %H:%M:%S")
    assert receipt.result_hash
    assert result.ref.startswith("query:detect_card_testing(")


def test_identical_calls_hash_identically(graph: FixtureGraphClient) -> None:
    first = tools.detect_card_testing(
        graph, card_id="FIXC02-K1", cutoff=AFTER_CARD_TESTING, window_hours=6
    )
    second = tools.detect_card_testing(
        graph, card_id="FIXC02-K1", cutoff=AFTER_CARD_TESTING, window_hours=6
    )
    assert first.receipt.result_hash == second.receipt.result_hash


def test_a_query_outside_the_allow_list_is_refused(graph: FixtureGraphClient) -> None:
    with pytest.raises(GraphError, match="allow-list"):
        graph.run("DROP ALL", {})


def test_unsupported_origin_kind_is_rejected(graph: FixtureGraphClient) -> None:
    with pytest.raises(ValueError, match="unsupported origin kind"):
        tools.find_connected_accounts(graph, origin_kind="ssn", origin_id="x", cutoff=AFTER_RING)


def test_call_log_counts_graph_calls(tmp_path: Path) -> None:
    """`tool_calls` in the answer file comes from this counter."""
    raw, out = tmp_path / "raw", tmp_path / "processed"
    write_fixture_dataset(raw)
    preprocess(raw, out)
    client = FixtureGraphClient(out)

    assert client.call_log.count == 0
    tools.get_customer_baseline(client, customer_id="FIXC01", cutoff=AFTER_RING)
    tools.detect_card_testing(client, card_id="FIXC01-K1", cutoff=AFTER_RING)
    assert client.call_log.count == 2
