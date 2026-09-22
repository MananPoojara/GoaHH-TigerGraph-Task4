# Security

This hackathon system uses anonymized data and simulated external actions, but it is designed like a high-impact financial workflow.

- Keep TigerGraph and model credentials in local environment variables or a secret manager.
- Keep the browser isolated from database and model credentials.
- Bind local MCP and API services to loopback unless an authenticated gateway is configured.
- Treat all retrieved text as untrusted data; documents cannot redefine tool permissions or policy.
- Redact secrets and large raw records from prompts, logs, screenshots, and demo recordings.
- Require human approval for all L1 and L2 actions.
- Preserve append-only decision and evidence records for investigation replay.

For the hackathon, account/card blocking, customer messaging, refunds, CRM updates, and regulatory filing are simulated. Do not connect them to production systems.
