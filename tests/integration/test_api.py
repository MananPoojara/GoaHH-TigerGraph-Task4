"""API tests, with the authorization boundary as the centrepiece.

The rule these protect: a client calling the API directly must not be able to
execute an action that policy says needs a human. Enforcing it only inside the
policy engine would leave the HTTP surface as a way around it.
"""

from __future__ import annotations

import pytest
from app.core.config import Settings
from app.main import app
from app.services.registry import Runtime, get_runtime
from fastapi.testclient import TestClient
from fraudlens_loading import preprocess, write_fixture_dataset


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    """An API bound to a fixture dataset rather than a live graph."""
    root = tmp_path_factory.mktemp("api")
    raw, processed = root / "raw", root / "processed"
    write_fixture_dataset(raw)
    preprocess(raw, processed)

    settings = Settings(APP_ENV="test", TG_HOST="", LLM_PROVIDER="none", LLM_API_KEY="")
    settings.repo_root = root  # type: ignore[assignment]
    # The fixture case pack lives beside the generated raw data.
    (root / "data").mkdir(exist_ok=True)

    runtime = Runtime(settings)
    runtime._graph = None  # type: ignore[attr-defined]
    from fraudlens_graph import FixtureGraphClient

    runtime._graph = FixtureGraphClient(processed)  # type: ignore[attr-defined]
    from fraudlens_contracts import load_case_pack

    runtime._case_pack = load_case_pack(raw / "case_pack.csv")  # type: ignore[attr-defined]

    app.dependency_overrides[get_runtime] = lambda: runtime
    yield TestClient(app)
    app.dependency_overrides.clear()


def _investigate_first(client: TestClient) -> str:
    """Run the card-testing fixture case, which produces L1 actions."""
    case_id = "FIX-001"
    response = client.post("/investigations", json={"case_id": case_id})
    assert response.status_code == 201, response.text
    return case_id


# --------------------------------------------------------------------------
# Basics
# --------------------------------------------------------------------------


def test_health_reports_backend_without_leaking_secrets(client: TestClient) -> None:
    payload = client.get("/health").json()
    assert payload["status"] == "ok"
    assert payload["graph_backend"] in {"fixture", "tigergraph"}
    # Secrets are reported as presence booleans only.
    assert "tg_api_token" not in payload
    assert "llm_api_key" not in payload
    assert isinstance(payload["llm_key_present"], bool)


def test_queue_lists_every_case_pack_entry(client: TestClient) -> None:
    rows = client.get("/cases").json()
    assert len(rows) == 4
    assert {row["case_id"] for row in rows} == {"FIX-001", "FIX-002", "FIX-003", "FIX-004"}


def test_unknown_case_is_rejected(client: TestClient) -> None:
    response = client.post("/investigations", json={"case_id": "NOPE-999"})
    assert response.status_code == 404


def test_uninvestigated_case_is_not_found(client: TestClient) -> None:
    assert client.get("/cases/FIX-003/evidence").status_code == 404


# --------------------------------------------------------------------------
# Investigation lifecycle
# --------------------------------------------------------------------------


def test_investigation_returns_a_complete_case(client: TestClient) -> None:
    case_id = _investigate_first(client)
    payload = client.get(f"/cases/{case_id}").json()

    assert payload["case_id"] == case_id
    assert payload["assessment"]["verdict"] in {"fraud", "legitimate", "uncertain"}
    assert 0.0 <= payload["assessment"]["fraud_probability"] <= 1.0
    assert payload["evidence_count"] > 0
    assert payload["summary"]
    assert payload["stop_reason"]
    assert payload["telemetry"]["tool_calls"] > 0


def test_evidence_ledger_is_served_with_provenance(client: TestClient) -> None:
    case_id = _investigate_first(client)
    items = client.get(f"/cases/{case_id}/evidence").json()
    assert items
    for item in items:
        assert item["claim"]
        assert item["ref"]
        assert item["source"] in {"graph", "document", "customer", "external"}
        assert item["direction"] in {"supports_fraud", "supports_legitimate", "context"}


def test_timeline_exposes_investigation_progress(client: TestClient) -> None:
    case_id = _investigate_first(client)
    events = client.get(f"/cases/{case_id}/timeline").json()
    assert events
    nodes = {event["node"] for event in events}
    assert {"intake", "collect_evidence", "seek_counter_evidence"} <= nodes
    steps = [event["step"] for event in events]
    assert steps == sorted(steps), "timeline must be ordered"


def test_answer_endpoint_returns_the_submission_contract(client: TestClient) -> None:
    from fraudlens_contracts import CaseAnswer

    case_id = _investigate_first(client)
    payload = client.get(f"/cases/{case_id}/answer").json()
    # Re-validating proves the served JSON satisfies the official contract.
    CaseAnswer.model_validate(payload)


def test_case_graph_is_bounded_and_connected(client: TestClient) -> None:
    case_id = _investigate_first(client)
    payload = client.get(f"/cases/{case_id}/graph").json()
    assert payload["nodes"]
    node_ids = {node["id"] for node in payload["nodes"]}
    for edge in payload["edges"]:
        assert edge["source"] in node_ids
        assert edge["target"] in node_ids


# --------------------------------------------------------------------------
# The authorization boundary
# --------------------------------------------------------------------------


def test_auto_actions_may_be_executed_directly(client: TestClient) -> None:
    case_id = _investigate_first(client)
    actions = client.get(f"/cases/{case_id}/actions").json()
    auto = next(item for item in actions["final"] if item["route"] == "auto")

    response = client.post(f"/cases/{case_id}/execute", json={"action": auto["action"]})
    assert response.status_code == 200
    body = response.json()
    assert body["executed"] is True
    assert body["simulated"] is True


def test_l1_action_cannot_be_executed_without_approval(client: TestClient) -> None:
    """The boundary that matters: HTTP must not be a way around policy."""
    case_id = _investigate_first(client)
    actions = client.get(f"/cases/{case_id}/actions").json()
    gated = [item for item in actions["final"] if item["route"] != "auto"]
    assert gated, "the card-testing fixture must produce at least one gated action"

    response = client.post(f"/cases/{case_id}/execute", json={"action": gated[0]["action"]})
    assert response.status_code == 403
    assert "approval" in response.json()["detail"]


def test_approved_action_becomes_executable(client: TestClient) -> None:
    case_id = _investigate_first(client)
    actions = client.get(f"/cases/{case_id}/actions").json()
    gated = next(item for item in actions["final"] if item["route"] != "auto")

    approval = client.post(
        f"/cases/{case_id}/approve",
        json={
            "action": gated["action"],
            "decision": "approved",
            "analyst": "demo.analyst",
            "rationale": "Evidence reviewed; containment is warranted.",
        },
    )
    assert approval.status_code == 200
    assert approval.json()["approvals"][-1]["decided_by"] == "demo.analyst"

    execution = client.post(f"/cases/{case_id}/execute", json={"action": gated["action"]})
    assert execution.status_code == 200
    assert execution.json()["executed"] is True


def test_rejected_action_stays_blocked(client: TestClient) -> None:
    client.post("/investigations", json={"case_id": "FIX-002"})
    actions = client.get("/cases/FIX-002/actions").json()
    gated = [item for item in actions["final"] if item["route"] != "auto"]
    if not gated:
        pytest.skip("this fixture case produced no gated action")

    client.post(
        "/cases/FIX-002/approve",
        json={
            "action": gated[0]["action"],
            "decision": "rejected",
            "analyst": "demo.analyst",
            "rationale": "Insufficient evidence to justify customer impact.",
        },
    )
    response = client.post("/cases/FIX-002/execute", json={"action": gated[0]["action"]})
    assert response.status_code == 403


def test_approval_requires_the_action_to_be_recommended(client: TestClient) -> None:
    case_id = _investigate_first(client)
    response = client.post(
        f"/cases/{case_id}/approve",
        json={
            "action": "BLOCK_ALL_CARDS",
            "decision": "approved",
            "analyst": "demo.analyst",
            "rationale": "Attempting to approve something never recommended.",
        },
    )
    assert response.status_code == 400


def test_approving_an_auto_action_is_rejected(client: TestClient) -> None:
    case_id = _investigate_first(client)
    actions = client.get(f"/cases/{case_id}/actions").json()
    auto = next(item for item in actions["final"] if item["route"] == "auto")
    response = client.post(
        f"/cases/{case_id}/approve",
        json={
            "action": auto["action"],
            "decision": "approved",
            "analyst": "demo.analyst",
            "rationale": "Not needed.",
        },
    )
    assert response.status_code == 400


def test_approval_appends_rather_than_rewriting_the_recommendation(
    client: TestClient,
) -> None:
    """An override must not edit what the agent recommended."""
    case_id = _investigate_first(client)
    before = client.get(f"/cases/{case_id}/actions").json()
    gated = next(item for item in before["final"] if item["route"] != "auto")

    client.post(
        f"/cases/{case_id}/approve",
        json={
            "action": gated["action"],
            "decision": "rejected",
            "analyst": "second.analyst",
            "rationale": "Disagree with the recommendation.",
        },
    )
    after = client.get(f"/cases/{case_id}/actions").json()

    recommended_before = [(i["action"], i["route"], i["reason"]) for i in before["final"]]
    recommended_after = [(i["action"], i["route"], i["reason"]) for i in after["final"]]
    assert recommended_before == recommended_after
    assert len(after["approvals"]) > len(before["approvals"])
