# Setup checklist for implementation day

## Accounts and tools

- [ ] TigerGraph Savanna account and active workspace
- [ ] TigerGraph version 4.2+ selected where available (4.1 is the current MCP minimum)
- [ ] LLM provider key with sufficient quota
- [ ] Git installed locally
- [ ] GitHub repository created and remote URL recorded
- [ ] Python 3.12+ and Node.js 22+
- [ ] At least 2 GB free for raw/processed data, environments, and graph-loading artifacts

## Dataset

- [ ] Download `transactions.csv`, `identity.csv`, `closed_cases_history.csv`, and `case_pack.csv` from the official Drive folder
- [ ] Place them in `data/raw/`
- [ ] Record SHA-256 hashes and sizes
- [ ] Confirm expected row counts and UTF-8 headers
- [ ] Never download or join public IEEE-CIS labels

## Configuration

- [ ] Copy `.env.example` to `.env`
- [ ] Configure TigerGraph host, graph, and token
- [ ] Enable MCP tool-call logging and restrict the exposed tool set to required reads plus validated case persistence
- [ ] Select LLM and embedding models
- [ ] Keep `ALLOW_NON_AUTO_ACTION_EXECUTION=false`
- [ ] Confirm raw data, `.env`, outputs, and traces are ignored by Git

## First vertical slice

1. Load a small fixture and verify graph/MCP access.
2. Load official transaction core and verify an anchor case manually.
3. Run one query per evidence family.
4. Produce one answer through the deterministic policy engine.
5. Validate, write to graph, read back, and display in the UI.

Only then scale to all 20 cases.
