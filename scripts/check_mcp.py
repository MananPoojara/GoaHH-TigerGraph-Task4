#!/usr/bin/env python
"""Drive the FraudLens MCP server end to end as a real MCP client would.

Usage:
    python scripts/check_mcp.py                 # list tools, call two on HHG-001
    python scripts/check_mcp.py --case HHG-008

Starts `python -m fraudlens_graph.mcp_server` over stdio, performs the MCP
handshake, lists the exposed tools, and calls `get_case_anchor` and
`get_customer_baseline` for one benchmark trigger. The reported `backend`
says whether a live TigerGraph or the fixture backend answered.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from fraudlens_contracts import load_case_pack  # noqa: E402
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


async def check(case_id: str) -> int:
    entries = {e.case_id: e for e in load_case_pack(REPO_ROOT / "data" / "raw" / "case_pack.csv")}
    entry = entries.get(case_id)
    if entry is None:
        print(f"case {case_id!r} is not in the case pack")
        return 2
    cutoff = entry.opened_at.strftime(TIMESTAMP_FORMAT)

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "fraudlens_graph.mcp_server"],
        cwd=str(REPO_ROOT),
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()

        listed = await session.list_tools()
        print(f"{len(listed.tools)} tools exposed:")
        for tool in listed.tools:
            print(f"  - {tool.name}")

        calls = [
            (
                "get_case_anchor",
                {
                    "txn_id": entry.flagged_txn_id,
                    "card_id": entry.card_id,
                    "customer_id": entry.customer_id,
                    "cutoff": cutoff,
                },
            ),
            ("get_customer_baseline", {"customer_id": entry.customer_id, "cutoff": cutoff}),
        ]
        for name, arguments in calls:
            result = await session.call_tool(name, arguments)
            if result.isError:
                print(f"\n{name} FAILED: {result.content}")
                return 1
            payload = json.loads(result.content[0].text)
            print(f"\n{name} -> backend={payload['backend']} ref={payload['ref']}")
            print(json.dumps(payload["data"], default=str)[:400])

    print("\nMCP server OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", default="HHG-001", help="benchmark case to probe")
    args = parser.parse_args()
    return asyncio.run(check(args.case))


if __name__ == "__main__":
    raise SystemExit(main())
