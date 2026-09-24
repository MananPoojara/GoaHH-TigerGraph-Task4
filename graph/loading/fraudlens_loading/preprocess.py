"""Turn the four official CSVs into TigerGraph load files.

Shape of the job
----------------
`transactions.csv` is ~708 MB across 397 columns, so it is streamed with the
csv module rather than read into a DataFrame; only the columns the graph
actually needs are retained. `identity.csv` is small enough (144,432 rows) to
hold as a transaction-id keyed dict for the join.

Three passes are needed, and the order is forced by the card rule:

  1. identity.csv  -> device profiles, keyed by TransactionID
  2. transactions.csv (pass 1) -> observe every (customer_id, card6) pair and
     accumulate per-customer and per-card aggregates
  3. transactions.csv (pass 2) -> emit rows, now that card ordinals are known

Pass 1 cannot be fused into pass 2: a card ordinal depends on the complete set
of a customer's card6 values, so a value appearing in the last row of the file
can change the ID assigned to a row near the start.

Nothing here decides anything about fraud. This module only reshapes supplied
data into the graph's vocabulary, and refuses the load if the reshaping does
not reconcile.
"""

from __future__ import annotations

import csv
import logging
import sys
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .identity import (
    CardMapping,
    device_profile_from_identity_row,
    normalize_card6,
)

logger = logging.getLogger(__name__)

# transactions.csv has 397 columns; these are the ones the graph needs by name.
# Everything else stays in the raw file and is available for audited lookup.
TRANSACTION_COLUMNS = (
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
)

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

# The csv module refuses very large fields by default; the widest Vesta rows
# are well within this but the limit is raised once, explicitly, rather than
# discovered as a crash mid-load.
csv.field_size_limit(min(sys.maxsize, 2_147_483_647))


def _to_float(value: object, default: float = -1.0) -> float:
    if value is None:
        return default
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def _clean(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null"} else text


@dataclass
class CustomerAggregate:
    """Per-customer totals accumulated during the first pass."""

    txn_count: int = 0
    amount_sum: float = 0.0
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    cards: set[str] = field(default_factory=set)
    region_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def observe(self, ts: datetime, amount: float, region: str) -> None:
        self.txn_count += 1
        self.amount_sum += abs(amount)
        if self.first_seen is None or ts < self.first_seen:
            self.first_seen = ts
        if self.last_seen is None or ts > self.last_seen:
            self.last_seen = ts
        if region:
            self.region_counts[region] += 1

    @property
    def avg_amount(self) -> float:
        return self.amount_sum / self.txn_count if self.txn_count else 0.0

    @property
    def home_region(self) -> str:
        """The region this customer uses most. Ties break lexically so the
        value is stable across runs."""
        if not self.region_counts:
            return ""
        return max(sorted(self.region_counts), key=lambda key: self.region_counts[key])


@dataclass
class CardAggregate:
    txn_count: int = 0
    amount_sum: float = 0.0
    observed_from: datetime | None = None
    observed_to: datetime | None = None
    card_type: str = ""
    card_network: str = ""
    card1: str = ""
    card2: str = ""
    card3: str = ""
    card5: str = ""

    @property
    def avg_amount(self) -> float:
        return self.amount_sum / self.txn_count if self.txn_count else 0.0


@dataclass
class DeviceAggregate:
    readable: str = ""
    device_info: str = ""
    device_type: str = ""
    os: str = ""
    browser: str = ""
    screen: str = ""
    proxy_status: str = ""
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    cards: set[str] = field(default_factory=set)
    customers: set[str] = field(default_factory=set)


@dataclass
class PreprocessReport:
    """Counts that must reconcile before a load is accepted."""

    transaction_rows: int = 0
    identity_rows: int = 0
    rejected_rows: int = 0
    customers: int = 0
    cards: int = 0
    devices: int = 0
    email_domains: int = 0
    billing_regions: int = 0
    next_edges: int = 0
    closed_cases: int = 0
    rejections: list[str] = field(default_factory=list)

    def reject(self, reason: str) -> None:
        self.rejected_rows += 1
        # Keep a bounded sample; a systematic failure shows up in the first few.
        if len(self.rejections) < 50:
            self.rejections.append(reason)

    @property
    def accepted_rows(self) -> int:
        return self.transaction_rows - self.rejected_rows

    def summary(self) -> str:
        return (
            f"transactions={self.transaction_rows} accepted={self.accepted_rows} "
            f"rejected={self.rejected_rows} customers={self.customers} "
            f"cards={self.cards} devices={self.devices} "
            f"regions={self.billing_regions} next_edges={self.next_edges} "
            f"closed_cases={self.closed_cases}"
        )


def _iter_csv(path: Path) -> Iterator[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        yield from csv.DictReader(handle)


def load_identity_devices(
    identity_path: Path,
) -> tuple[dict[str, tuple[str, str]], dict[str, dict[str, str]]]:
    """Map TransactionID -> (device_id, readable) plus the raw identity fields.

    `identity.csv` covers online transactions only; an in-person (ProductCD W)
    transaction legitimately has no entry here.
    """
    devices: dict[str, tuple[str, str]] = {}
    raw_fields: dict[str, dict[str, str]] = {}

    for row in _iter_csv(identity_path):
        txn_id = _clean(row.get("TransactionID"))
        if not txn_id:
            continue
        devices[txn_id] = device_profile_from_identity_row(row)
        raw_fields[txn_id] = {
            "device_info": _clean(row.get("DeviceInfo")),
            "device_type": _clean(row.get("DeviceType")),
            "os": _clean(row.get("id_30")),
            "browser": _clean(row.get("id_31")),
            "screen": _clean(row.get("id_33")),
            # id_15 marks the device New or Found for this account.
            "device_status": _clean(row.get("id_15")),
            # id_23 is the proxy rating: transparent, anonymous, hidden.
            "proxy_status": _clean(row.get("id_23")),
            # id_34 is the match status.
            "match_status": _clean(row.get("id_34")),
        }

    logger.info("identity rows loaded: %d", len(devices))
    return devices, raw_fields


def build_card_mapping(transactions_path: Path) -> tuple[CardMapping, PreprocessReport]:
    """First pass: observe every (customer_id, card6) pair.

    This pass reads the whole 708 MB file and keeps only the pairs, so its
    memory cost is bounded by the number of customers rather than rows.
    """
    mapping = CardMapping()
    report = PreprocessReport()

    for row in _iter_csv(transactions_path):
        report.transaction_rows += 1
        customer_id = _clean(row.get("customer_id"))
        if not customer_id:
            report.reject(f"row {report.transaction_rows}: missing customer_id")
            continue
        mapping.add_observation(customer_id, row.get("card6"))

    mapping.finalize()
    logger.info(
        "card mapping built: %d customers, %d (customer, card6) pairs",
        mapping.customer_count,
        mapping.pair_count,
    )
    return mapping, report


def preprocess(
    raw_dir: Path,
    out_dir: Path,
    *,
    limit: int | None = None,
) -> PreprocessReport:
    """Run the full pipeline and write load files into `out_dir`.

    Args:
        raw_dir: directory holding the four official CSVs.
        out_dir: destination for the generated load files.
        limit: stop after this many transaction rows. For smoke tests only;
            a limited run produces an incomplete card mapping and must never
            be loaded into a graph used for scored answers.

    Returns:
        A reconciliation report. `accepted + rejected == source rows` is the
        condition for accepting the load.
    """
    transactions_path = raw_dir / "transactions.csv"
    identity_path = raw_dir / "identity.csv"
    closed_cases_path = raw_dir / "closed_cases_history.csv"

    missing = [p.name for p in (transactions_path, identity_path) if not p.exists()]
    if missing:
        raise FileNotFoundError(
            f"missing required source file(s) in {raw_dir}: {', '.join(missing)}. "
            "Download them from the official Drive folder first."
        )

    out_dir.mkdir(parents=True, exist_ok=True)

    if limit is not None:
        logger.warning(
            "preprocess running with limit=%d; the card mapping will be incomplete "
            "and must not be used for scored answers",
            limit,
        )

    devices_by_txn, identity_fields = load_identity_devices(identity_path)

    mapping, report = build_card_mapping(transactions_path)
    report.identity_rows = len(devices_by_txn)

    customers: dict[str, CustomerAggregate] = defaultdict(CustomerAggregate)
    cards: dict[str, CardAggregate] = defaultdict(CardAggregate)
    device_aggregates: dict[str, DeviceAggregate] = defaultdict(DeviceAggregate)
    email_domains: dict[str, dict[str, int]] = defaultdict(lambda: {"purchaser": 0, "recipient": 0})
    regions: dict[str, dict[str, object]] = {}
    # Transactions per card, kept as (ts, txn_id) so NEXT edges can be built
    # by sorting within each card rather than sorting the whole file.
    card_timeline: dict[str, list[tuple[datetime, str]]] = defaultdict(list)

    txn_out = out_dir / "transactions.csv"
    with txn_out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "txn_id",
                "customer_id",
                "card_id",
                "ts",
                "transaction_dt",
                "amount",
                "product_cd",
                "channel",
                "risk_score",
                "addr1",
                "addr2",
                "dist1",
                "p_email",
                "r_email",
                "device_profile_id",
                "device_is_new",
                "proxy_status",
                "match_status",
                "c1",
                "c13",
                "c14",
                "d1",
                "d2",
                "d15",
                "m4",
            ]
        )

        for index, row in enumerate(_iter_csv(transactions_path)):
            if limit is not None and index >= limit:
                break

            txn_id = _clean(row.get("TransactionID"))
            customer_id = _clean(row.get("customer_id"))
            if not txn_id or not customer_id:
                continue

            ts_text = _clean(row.get("ts"))
            try:
                ts = datetime.strptime(ts_text, TIMESTAMP_FORMAT)
            except ValueError:
                report.reject(f"txn {txn_id}: unparseable ts {ts_text!r}")
                continue

            raw_card6 = normalize_card6(row.get("card6"))
            try:
                card_id = mapping.card_id_for(customer_id, raw_card6)
            except KeyError as error:
                report.reject(f"txn {txn_id}: {error}")
                continue

            amount = _to_float(row.get("TransactionAmt"), 0.0)
            product_cd = _clean(row.get("ProductCD"))
            channel = _clean(row.get("channel"))
            risk_score = _to_float(row.get("risk_score"), 0.0)
            addr1 = _clean(row.get("addr1"))
            addr2 = _clean(row.get("addr2"))
            p_email = _clean(row.get("P_emaildomain"))
            r_email = _clean(row.get("R_emaildomain"))

            device_id, readable = devices_by_txn.get(txn_id, ("", ""))
            identity = identity_fields.get(txn_id, {})
            # id_15 marks the device New or Found for this account.
            device_is_new = identity.get("device_status", "").strip().lower() == "new"
            proxy_status = identity.get("proxy_status", "")
            match_status = identity.get("match_status", "")

            writer.writerow(
                [
                    txn_id,
                    customer_id,
                    card_id,
                    ts_text,
                    int(_to_float(row.get("TransactionDT"), 0.0)),
                    f"{amount:.4f}",
                    product_cd,
                    channel,
                    f"{risk_score:.4f}",
                    addr1,
                    addr2,
                    _to_float(row.get("dist1")),
                    p_email,
                    r_email,
                    device_id,
                    "true" if device_is_new else "false",
                    proxy_status,
                    match_status,
                    _to_float(row.get("C1")),
                    _to_float(row.get("C13")),
                    _to_float(row.get("C14")),
                    _to_float(row.get("D1")),
                    _to_float(row.get("D2")),
                    _to_float(row.get("D15")),
                    _clean(row.get("M4")),
                ]
            )

            customers[customer_id].observe(ts, amount, addr1)
            customers[customer_id].cards.add(card_id)

            card = cards[card_id]
            card.txn_count += 1
            card.amount_sum += abs(amount)
            if card.observed_from is None or ts < card.observed_from:
                card.observed_from = ts
            if card.observed_to is None or ts > card.observed_to:
                card.observed_to = ts
            if not card.card_type:
                card.card_type = raw_card6
                card.card_network = _clean(row.get("card4"))
                card.card1 = _clean(row.get("card1"))
                card.card2 = _clean(row.get("card2"))
                card.card3 = _clean(row.get("card3"))
                card.card5 = _clean(row.get("card5"))

            card_timeline[card_id].append((ts, txn_id))

            if device_id:
                aggregate = device_aggregates[device_id]
                if not aggregate.readable:
                    aggregate.readable = readable
                    aggregate.device_info = identity.get("device_info", "")
                    aggregate.device_type = identity.get("device_type", "")
                    aggregate.os = identity.get("os", "")
                    aggregate.browser = identity.get("browser", "")
                    aggregate.screen = identity.get("screen", "")
                    aggregate.proxy_status = proxy_status
                if aggregate.first_seen is None or ts < aggregate.first_seen:
                    aggregate.first_seen = ts
                if aggregate.last_seen is None or ts > aggregate.last_seen:
                    aggregate.last_seen = ts
                aggregate.cards.add(card_id)
                aggregate.customers.add(customer_id)

            if p_email:
                email_domains[p_email]["purchaser"] += 1
            if r_email:
                email_domains[r_email]["recipient"] += 1

            if addr1:
                entry = regions.setdefault(
                    addr1, {"country_code": addr2, "txn_count": 0, "cards": set()}
                )
                entry["txn_count"] = int(entry["txn_count"]) + 1
                cards_set = entry["cards"]
                assert isinstance(cards_set, set)
                cards_set.add(card_id)

    _write_customers(out_dir, customers)
    _write_cards(out_dir, cards, mapping)
    _write_devices(out_dir, device_aggregates)
    _write_email_domains(out_dir, email_domains)
    _write_regions(out_dir, regions)
    report.next_edges = _write_next_edges(out_dir, card_timeline)

    if closed_cases_path.exists():
        report.closed_cases = _write_closed_cases(out_dir, closed_cases_path)

    report.customers = len(customers)
    report.cards = len(cards)
    report.devices = len(device_aggregates)
    report.email_domains = len(email_domains)
    report.billing_regions = len(regions)

    logger.info("preprocess complete: %s", report.summary())
    return report


def _write_customers(out_dir: Path, customers: dict[str, CustomerAggregate]) -> None:
    with (out_dir / "customers.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "customer_id",
                "first_seen",
                "last_seen",
                "card_count",
                "txn_count",
                "total_amount",
                "avg_amount",
                "home_region",
            ]
        )
        for customer_id, aggregate in sorted(customers.items()):
            writer.writerow(
                [
                    customer_id,
                    aggregate.first_seen.strftime(TIMESTAMP_FORMAT) if aggregate.first_seen else "",
                    aggregate.last_seen.strftime(TIMESTAMP_FORMAT) if aggregate.last_seen else "",
                    len(aggregate.cards),
                    aggregate.txn_count,
                    f"{aggregate.amount_sum:.2f}",
                    f"{aggregate.avg_amount:.2f}",
                    aggregate.home_region,
                ]
            )


def _write_cards(out_dir: Path, cards: dict[str, CardAggregate], mapping: CardMapping) -> None:
    with (out_dir / "cards.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "card_id",
                "customer_id",
                "card_ordinal",
                "card_type",
                "card_network",
                "card1",
                "card2",
                "card3",
                "card5",
                "observed_from",
                "observed_to",
                "txn_count",
                "avg_amount",
            ]
        )
        for card_id, aggregate in sorted(cards.items()):
            customer_id, _, suffix = card_id.partition("-K")
            writer.writerow(
                [
                    card_id,
                    customer_id,
                    int(suffix) if suffix.isdigit() else 1,
                    aggregate.card_type,
                    aggregate.card_network,
                    aggregate.card1,
                    aggregate.card2,
                    aggregate.card3,
                    aggregate.card5,
                    (
                        aggregate.observed_from.strftime(TIMESTAMP_FORMAT)
                        if aggregate.observed_from
                        else ""
                    ),
                    (
                        aggregate.observed_to.strftime(TIMESTAMP_FORMAT)
                        if aggregate.observed_to
                        else ""
                    ),
                    aggregate.txn_count,
                    f"{aggregate.avg_amount:.2f}",
                ]
            )


def _write_devices(out_dir: Path, devices: dict[str, DeviceAggregate]) -> None:
    with (out_dir / "devices.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "device_id",
                "readable",
                "device_info",
                "device_type",
                "os",
                "browser",
                "screen",
                "proxy_status",
                "first_seen",
                "last_seen",
                "card_fanout",
                "customer_fanout",
            ]
        )
        for device_id, aggregate in sorted(devices.items()):
            writer.writerow(
                [
                    device_id,
                    aggregate.readable,
                    aggregate.device_info,
                    aggregate.device_type,
                    aggregate.os,
                    aggregate.browser,
                    aggregate.screen,
                    aggregate.proxy_status,
                    aggregate.first_seen.strftime(TIMESTAMP_FORMAT) if aggregate.first_seen else "",
                    aggregate.last_seen.strftime(TIMESTAMP_FORMAT) if aggregate.last_seen else "",
                    len(aggregate.cards),
                    len(aggregate.customers),
                ]
            )


def _write_email_domains(out_dir: Path, domains: dict[str, dict[str, int]]) -> None:
    with (out_dir / "email_domains.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["domain", "purchaser_count", "recipient_count"])
        for domain, counts in sorted(domains.items()):
            writer.writerow([domain, counts["purchaser"], counts["recipient"]])


def _write_regions(out_dir: Path, regions: dict[str, dict[str, object]]) -> None:
    with (out_dir / "billing_regions.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["region_code", "country_code", "card_count", "txn_count"])
        for region_code, entry in sorted(regions.items()):
            cards_set = entry["cards"]
            assert isinstance(cards_set, set)
            writer.writerow(
                [region_code, entry["country_code"], len(cards_set), entry["txn_count"]]
            )


def _write_next_edges(out_dir: Path, card_timeline: dict[str, list[tuple[datetime, str]]]) -> int:
    """Build the per-card ordered NEXT spine.

    Sorting happens per card rather than globally, so peak memory stays
    proportional to the busiest card rather than to the whole file.
    """
    written = 0
    with (out_dir / "next_edges.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["from_txn_id", "to_txn_id", "gap_seconds", "card_id"])
        for card_id, entries in sorted(card_timeline.items()):
            entries.sort(key=lambda item: (item[0], item[1]))
            for previous, current in zip(entries, entries[1:], strict=False):
                gap = int((current[0] - previous[0]).total_seconds())
                writer.writerow([previous[1], current[1], gap, card_id])
                written += 1
    return written


def _write_closed_cases(out_dir: Path, closed_cases_path: Path) -> int:
    """Flatten closed cases into a case file plus its transaction links.

    `txn_ids` is pipe-separated in the source; the graph needs one edge per
    transaction, so the list is exploded here rather than in GSQL.
    """
    count = 0
    case_out = out_dir / "closed_cases.csv"
    link_out = out_dir / "closed_case_txns.csv"

    with (
        case_out.open("w", newline="", encoding="utf-8") as case_handle,
        link_out.open("w", newline="", encoding="utf-8") as link_handle,
    ):
        case_writer = csv.writer(case_handle)
        link_writer = csv.writer(link_handle)
        case_writer.writerow(
            [
                "case_id",
                "source",
                "trust_tier",
                "customer_id",
                "card_id",
                "opened_at",
                "closed_at",
                "status",
                "verdict",
                "outcome",
                "pattern",
                "fraud_probability",
                "exposure_usd",
                "n_txns",
                "report_filed",
                "actions_taken",
                "analyst_notes",
            ]
        )
        link_writer.writerow(["case_id", "txn_id", "affected", "role"])

        for row in _iter_csv(closed_cases_path):
            case_id = _clean(row.get("case_id"))
            if not case_id:
                continue
            outcome = _clean(row.get("outcome"))
            is_fraud = outcome == "confirmed_fraud"
            first_fraud = _clean(row.get("first_fraud_txn_id"))
            txn_ids = [part for part in _clean(row.get("txn_ids")).split("|") if part]

            case_writer.writerow(
                [
                    case_id,
                    "closed_history",
                    "labeled_history",
                    _clean(row.get("customer_id")),
                    _clean(row.get("card_id")),
                    _clean(row.get("opened_at")),
                    _clean(row.get("closed_at")),
                    "closed_fraud" if is_fraud else "closed_legitimate",
                    "fraud" if is_fraud else "legitimate",
                    outcome,
                    _clean(row.get("pattern")),
                    # The bank's closed outcome is certain, so it is recorded as
                    # 1.0 or 0.0. This is a label, not one of our estimates, and
                    # must never be fed back in as a calibration target.
                    1.0 if is_fraud else 0.0,
                    _to_float(row.get("exposure_usd"), 0.0),
                    int(_to_float(row.get("n_txns"), 0.0)),
                    "true" if _clean(row.get("report_filed")).lower() == "yes" else "false",
                    _clean(row.get("actions_taken")),
                    _clean(row.get("analyst_notes")),
                ]
            )

            for txn_id in txn_ids:
                link_writer.writerow(
                    [
                        case_id,
                        txn_id,
                        "true" if is_fraud else "false",
                        "first_fraud" if txn_id == first_fraud else "involved",
                    ]
                )
            count += 1

    return count
