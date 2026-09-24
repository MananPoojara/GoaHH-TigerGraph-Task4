#!/usr/bin/env python
"""Install the TigerGraph schema, queries, and algorithms, then load the data.

Usage:
    python scripts/install_graph.py --check       # connection preflight only
    python scripts/install_graph.py --schema      # create the schema
    python scripts/install_graph.py --queries     # install and compile queries
    python scripts/install_graph.py --load        # upload the processed files
    python scripts/install_graph.py --all

Requires TG_HOST and either TG_API_TOKEN or TG_PASSWORD in `.env`.

The GSQL under `graph/` is authoritative. This script only applies it, so the
files stay reviewable on their own and can also be pasted into GraphStudio.
"""

from __future__ import annotations

import argparse
import csv
import io
import itertools
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.core.config import get_settings  # noqa: E402

logger = logging.getLogger("install_graph")

SCHEMA_FILES = [REPO_ROOT / "graph" / "schema" / "01-schema.gsql"]
QUERY_FILES = sorted((REPO_ROOT / "graph" / "queries").glob("*.gsql"))
ALGORITHM_FILES = sorted((REPO_ROOT / "graph" / "algorithms").glob("*.gsql"))

LOADING_JOB_FILE = REPO_ROOT / "graph" / "loading" / "01-loading-job.gsql"
DERIVE_FILES = sorted((REPO_ROOT / "graph" / "loading").glob("0[2-9]-*.gsql"))
LOADING_JOB = "load_fraudlens"

# Processed file -> loading-job file tag. Order matters: vertices before the
# edge-only files, although the job would create missing endpoints anyway.
LOAD_PLAN = [
    ("customers.csv", "f_customers"),
    ("cards.csv", "f_cards"),
    ("devices.csv", "f_devices"),
    ("email_domains.csv", "f_email_domains"),
    ("billing_regions.csv", "f_billing_regions"),
    ("transactions.csv", "f_transactions"),
    ("next_edges.csv", "f_next_edges"),
    ("closed_cases.csv", "f_closed_cases"),
    ("closed_case_txns.csv", "f_closed_case_txns"),
]

# Rows per POST. Keeps each request well under the 128 MB REST++ limit and
# short enough not to time out on a slow link.
CHUNK_ROWS = 100_000


def connect(settings):
    """Open a TigerGraph connection, failing with a clear message."""
    try:
        import pyTigerGraph as tg
    except ImportError:
        logger.error("pyTigerGraph is not installed. Run: python -m pip install -e '.[graph]'")
        raise SystemExit(2) from None

    if not settings.tg_host:
        logger.error("TG_HOST is not set. Copy .env.example to .env and fill it in.")
        raise SystemExit(2)

    connection = tg.TigerGraphConnection(
        host=settings.tg_host,
        graphname=settings.tg_graphname,
        username=settings.tg_username,
        password=settings.tg_password.get_secret_value(),
        apiToken=settings.tg_api_token.get_secret_value() or None,
    )
    if not settings.tg_api_token.get_secret_value():
        try:
            connection.getToken(connection.createSecret())
        except Exception:
            logger.warning("could not mint a token; continuing with basic auth")
    return connection


def run_gsql_file(connection, path: Path) -> bool:
    """Apply one GSQL file. Returns whether it succeeded."""
    logger.info("applying %s", path.relative_to(REPO_ROOT))
    script = path.read_text(encoding="utf-8")
    try:
        result = connection.gsql(script)
    except Exception:
        logger.exception("failed to apply %s", path.name)
        return False

    text = str(result)
    # GSQL reports failures in its output rather than by raising.
    if "error" in text.lower() or "failed" in text.lower():
        logger.error("%s reported a problem:\n%s", path.name, text[:2000])
        return False
    logger.info("%s applied", path.name)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="connection preflight only")
    parser.add_argument("--schema", action="store_true")
    parser.add_argument("--queries", action="store_true")
    parser.add_argument("--load", action="store_true")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = get_settings()

    if not any([args.check, args.schema, args.queries, args.load, args.all]):
        parser.print_help()
        return 0

    connection = connect(settings)

    # Preflight: never assume the workspace is awake.
    try:
        echo = connection.echo()
        logger.info("connected to %s (%s)", settings.tg_host, echo)
    except Exception:
        logger.exception(
            "could not reach %s. On Savanna, check the workspace is started.",
            settings.tg_host,
        )
        return 3

    if args.check:
        print(f"TigerGraph reachable at {settings.tg_host}, graph {settings.tg_graphname}")
        return 0

    ok = True
    if args.schema or args.all:
        for path in SCHEMA_FILES:
            ok = run_gsql_file(connection, path) and ok

    if args.queries or args.all:
        for path in QUERY_FILES + ALGORITHM_FILES + DERIVE_FILES:
            ok = run_gsql_file(connection, path) and ok
        logger.info("installing queries (this compiles them and can take a few minutes)")
        try:
            print(connection.gsql(f"USE GRAPH {settings.tg_graphname}\nINSTALL QUERY ALL"))
        except Exception:
            logger.exception("INSTALL QUERY ALL failed")
            ok = False

    if args.load or args.all:
        ok = load_data(connection, settings) and ok

    if not ok:
        logger.error("one or more steps failed; see the messages above")
        return 4

    print("\nGraph is ready. Next: python scripts/run_benchmark.py")
    return 0


def load_data(connection, settings) -> bool:
    """Create the GSQL loading job, post every processed file to it, then derive links.

    The loading job in `graph/loading/01-loading-job.gsql` is authoritative:
    it loads every vertex and every edge. Files are posted in chunks (each
    with its header) so this works on Savanna, where the server cannot read
    local paths.
    """
    processed = settings.processed_data_dir
    if not (processed / "transactions.csv").exists():
        logger.error("no load files in %s. Run scripts/prepare_data.py first.", processed)
        return False

    # Recreate the job so edits to the .gsql file always take effect.
    connection.gsql(f"USE GRAPH {settings.tg_graphname}\nDROP JOB {LOADING_JOB}")
    if not run_gsql_file(connection, LOADING_JOB_FILE):
        return False

    ok = True
    for filename, file_tag in LOAD_PLAN:
        path = processed / filename
        if not path.exists():
            logger.error("missing load file %s", path)
            ok = False
            continue
        ok = post_file(connection, path, file_tag) and ok

    if ok:
        ok = derive_links(connection)
    return ok


def post_file(connection, path: Path, file_tag: str) -> bool:
    """Post one CSV to the loading job in header-carrying chunks."""
    logger.info("loading %s -> %s", path.name, file_tag)
    loaded = 0
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.reader(handle)
            header = next(reader)
            while True:
                rows = list(itertools.islice(reader, CHUNK_ROWS))
                if not rows:
                    break
                buffer = io.StringIO()
                writer = csv.writer(buffer, lineterminator="\n")
                writer.writerow(header)
                writer.writerows(rows)
                result = connection.runLoadingJobWithData(
                    buffer.getvalue(), file_tag, LOADING_JOB, sep=",", eol="\n", timeout=600_000
                )
                loaded += len(rows)
                logger.info("  %s: %d rows posted (%s)", file_tag, loaded, _load_stats(result))
    except Exception:
        logger.exception("loading %s failed after %d rows", path.name, loaded)
        return False
    return True


def _load_stats(result) -> str:
    """Summarise the accepted/rejected counts TigerGraph returns for a post."""
    try:
        stats = result[0]["statistics"] if isinstance(result, list) else result["statistics"]
        valid = stats.get("validLine", stats.get("validObject", "?"))
        invalid = stats.get("rejectLine", stats.get("rejectedLine", 0))
        return f"valid={valid} rejected={invalid}"
    except (KeyError, IndexError, TypeError):
        return str(result)[:200]


def derive_links(connection) -> bool:
    """Run the post-load derivation queries (installed with --queries)."""
    try:
        result = connection.runInstalledQuery("link_closed_case_devices", timeout=600_000)
    except Exception:
        logger.exception("link_closed_case_devices failed; was --queries run first?")
        return False
    logger.info("closed-case device links: %s", result)
    return True


if __name__ == "__main__":
    raise SystemExit(main())
