"""Synthetic source data with the real column structure.

Purpose: let the whole pipeline -- preprocessing, loading, queries, policy,
and the UI -- be exercised before the 708 MB official file is in place, and
keep a fast, deterministic fixture for tests afterwards.

The generated rows deliberately contain planted, known-answer scenarios so a
golden test can assert that the detectors find what is actually there:

  * FIXC01 - a clean legitimate customer
  * FIXC02 - a card-testing sequence (three sub-$5 online, then $259)
  * FIXC03 / FIXC04 - two customers sharing one device profile (an R6 ring)
  * FIXC05 - out-of-region in-person activity with home activity continuing

This is test data, never a substitute for the official dataset. It is written
under `data/fixtures/` and is never loaded into a graph used for scored runs.
"""

from __future__ import annotations

import csv
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

# The generator is seeded so the same fixture is produced on every machine.
FIXTURE_SEED = 20260923

# Matches the real file's span so cutoff logic behaves as it will in production.
FIXTURE_START = datetime(2016, 11, 1, 8, 0, 0)

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

# The subset of the 397 real columns the preprocessor reads. Writing exactly
# these keeps the fixture honest about the schema without reproducing 397
# columns of noise.
TRANSACTION_HEADER = [
    "TransactionID",
    "TransactionDT",
    "TransactionAmt",
    "ProductCD",
    "card1",
    "card2",
    "card3",
    "card4",
    "card5",
    "card6",
    "addr1",
    "addr2",
    "dist1",
    "P_emaildomain",
    "R_emaildomain",
    "C1",
    "C13",
    "C14",
    "D1",
    "D2",
    "D15",
    "M4",
    "customer_id",
    "ts",
    "channel",
    "risk_score",
]

IDENTITY_HEADER = [
    "TransactionID",
    "id_15",
    "id_23",
    "id_30",
    "id_31",
    "id_33",
    "id_34",
    "DeviceType",
    "DeviceInfo",
]


@dataclass
class _Txn:
    txn_id: str
    customer_id: str
    card6: str
    ts: datetime
    amount: float
    product_cd: str
    channel: str
    risk_score: float
    addr1: str
    device: tuple[str, str, str, str] | None = None
    device_status: str = "Found"
    proxy: str = ""


def _build_rows() -> list[_Txn]:
    rng = random.Random(FIXTURE_SEED)
    rows: list[_Txn] = []
    counter = 9_000_000

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return str(counter)

    android = ("SAMSUNG SM-G935F Build/NRD90M", "Android 7.0", "chrome 62.0", "1920x1080")
    iphone = ("iPhone", "iOS 11.1.2", "mobile safari 11.0", "1334x750")

    # --- FIXC01: an ordinary customer, steady in-person activity -----------
    for day in range(20):
        rows.append(
            _Txn(
                txn_id=next_id(),
                customer_id="FIXC01",
                card6="credit",
                ts=FIXTURE_START + timedelta(days=day, hours=rng.randint(0, 8)),
                amount=round(rng.uniform(20, 80), 2),
                product_cd="W",
                channel="in_person",
                risk_score=round(rng.uniform(0.01, 0.25), 2),
                addr1="204",
            )
        )

    # --- FIXC02: baseline, then a card-testing sequence -------------------
    for day in range(14):
        rows.append(
            _Txn(
                txn_id=next_id(),
                customer_id="FIXC02",
                card6="debit",
                ts=FIXTURE_START + timedelta(days=day, hours=10),
                amount=round(rng.uniform(30, 60), 2),
                product_cd="W",
                channel="in_person",
                risk_score=round(rng.uniform(0.02, 0.2), 2),
                addr1="330",
            )
        )
    # Three tiny online authorizations inside 40 minutes, then a large purchase.
    testing_start = FIXTURE_START + timedelta(days=15, hours=9, minutes=12)
    for offset, amount in ((0, 1.10), (18, 2.40), (40, 0.95)):
        rows.append(
            _Txn(
                txn_id=next_id(),
                customer_id="FIXC02",
                card6="debit",
                ts=testing_start + timedelta(minutes=offset),
                amount=amount,
                product_cd="C",
                channel="online",
                risk_score=0.44,
                addr1="330",
                device=android,
                device_status="New",
                proxy="anonymous",
            )
        )
    rows.append(
        _Txn(
            txn_id=next_id(),
            customer_id="FIXC02",
            card6="debit",
            ts=testing_start + timedelta(minutes=79),
            amount=259.98,
            product_cd="C",
            channel="online",
            risk_score=0.61,
            addr1="330",
            device=android,
            device_status="New",
            proxy="anonymous",
        )
    )

    # --- FIXC03 / FIXC04: one device profile across two customers (R6) ----
    ring_start = FIXTURE_START + timedelta(days=16, hours=14)
    # FIXC04 transacts first so that a case anchored on FIXC03 can actually
    # see the other card at its own decision time. Ordered the other way, the
    # cutoff correctly hides the ring and the scenario tests nothing.
    for index, customer in enumerate(("FIXC04", "FIXC03")):
        for day in range(10):
            rows.append(
                _Txn(
                    txn_id=next_id(),
                    customer_id=customer,
                    card6="credit",
                    ts=FIXTURE_START + timedelta(days=day, hours=12),
                    amount=round(rng.uniform(25, 90), 2),
                    product_cd="W",
                    channel="in_person",
                    risk_score=round(rng.uniform(0.02, 0.2), 2),
                    addr1="441",
                )
            )
        for burst in range(2):
            rows.append(
                _Txn(
                    txn_id=next_id(),
                    customer_id=customer,
                    card6="credit",
                    ts=ring_start + timedelta(hours=index * 3 + burst),
                    amount=round(rng.uniform(120, 340), 2),
                    product_cd="C",
                    channel="online",
                    risk_score=0.72,
                    addr1="441",
                    device=iphone,
                    device_status="New",
                    proxy="anonymous",
                )
            )

    # --- FIXC05: novel region while home activity continues ---------------
    for day in range(18):
        rows.append(
            _Txn(
                txn_id=next_id(),
                customer_id="FIXC05",
                card6="credit",
                ts=FIXTURE_START + timedelta(days=day, hours=9),
                amount=round(rng.uniform(15, 55), 2),
                product_cd="W",
                channel="in_person",
                risk_score=round(rng.uniform(0.02, 0.18), 2),
                addr1="512",
            )
        )
    # Same-day activity in a region never seen before, alongside home activity.
    away_day = FIXTURE_START + timedelta(days=17, hours=13)
    for offset in range(3):
        rows.append(
            _Txn(
                txn_id=next_id(),
                customer_id="FIXC05",
                card6="credit",
                ts=away_day + timedelta(hours=offset),
                amount=round(rng.uniform(80, 200), 2),
                product_cd="W",
                channel="in_person",
                risk_score=0.66,
                addr1="887",
            )
        )

    # A second card for FIXC05, so multi-card customers are represented and
    # the K1/K2 ordinal rule is exercised.
    for day in range(6):
        rows.append(
            _Txn(
                txn_id=next_id(),
                customer_id="FIXC05",
                card6="debit",
                ts=FIXTURE_START + timedelta(days=day * 2, hours=16),
                amount=round(rng.uniform(10, 40), 2),
                product_cd="W",
                channel="in_person",
                risk_score=round(rng.uniform(0.02, 0.15), 2),
                addr1="512",
            )
        )

    rows.sort(key=lambda row: (row.ts, row.txn_id))
    return rows


def write_fixture_dataset(out_dir: Path) -> dict[str, int]:
    """Write synthetic `transactions.csv`, `identity.csv`, and a case pack.

    Returns a count per generated file.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = _build_rows()

    with (out_dir / "transactions.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(TRANSACTION_HEADER)
        for row in rows:
            writer.writerow(
                [
                    row.txn_id,
                    int((row.ts - FIXTURE_START).total_seconds()),
                    f"{row.amount:.2f}",
                    row.product_cd,
                    # card1 is customer-level in the real data, so the fixture
                    # mirrors that: one value per customer.
                    f"{abs(hash(row.customer_id)) % 20000}",
                    "",
                    "",
                    "visa",
                    "",
                    row.card6,
                    row.addr1,
                    "87",
                    "",
                    "gmail.com",
                    "",
                    "1",
                    "1",
                    "1",
                    "0",
                    "0",
                    "0",
                    "M2",
                    row.customer_id,
                    row.ts.strftime(TIMESTAMP_FORMAT),
                    row.channel,
                    f"{row.risk_score:.2f}",
                ]
            )

    identity_count = 0
    with (out_dir / "identity.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(IDENTITY_HEADER)
        for row in rows:
            # Online transactions only, exactly as the real identity file.
            if row.channel != "online" or row.device is None:
                continue
            device_info, os_name, browser, screen = row.device
            writer.writerow(
                [
                    row.txn_id,
                    row.device_status,
                    row.proxy,
                    os_name,
                    browser,
                    screen,
                    "match_status:2",
                    "mobile" if device_info != "Windows" else "desktop",
                    device_info,
                ]
            )
            identity_count += 1

    # A case pack over the planted scenarios, in the official column shape.
    anchors = [
        ("FIX-001", "FIXC02", "card_testing anchor"),
        ("FIX-002", "FIXC03", "shared device ring anchor"),
        ("FIX-003", "FIXC05", "out of region anchor"),
        ("FIX-004", "FIXC01", "legitimate control"),
    ]
    with (out_dir / "case_pack.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "case_id",
                "opened_at",
                "trigger_type",
                "trigger_text",
                "flagged_txn_id",
                "card_id",
                "customer_id",
                "risk_score",
            ]
        )
        for case_id, customer_id, note in anchors:
            candidates = [row for row in rows if row.customer_id == customer_id]
            anchor = max(candidates, key=lambda row: (row.risk_score, row.ts))
            # The cutoff sits just after the anchor, as a real alert would.
            opened_at = anchor.ts + timedelta(minutes=5)
            writer.writerow(
                [
                    case_id,
                    opened_at.strftime(TIMESTAMP_FORMAT),
                    "risk_score",
                    f"Fixture trigger: {note}",
                    anchor.txn_id,
                    f"{customer_id}-K1",
                    customer_id,
                    f"{anchor.risk_score:.2f}",
                ]
            )

    return {
        "transactions.csv": len(rows),
        "identity.csv": identity_count,
        "case_pack.csv": len(anchors),
    }
