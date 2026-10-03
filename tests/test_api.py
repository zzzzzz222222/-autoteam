"""AutoTeam Web API tests (v0.5.0 UI refactor).

Covers every HTTP endpoint plus an end-to-end run: create task -> team ->
events/SSE -> artifacts -> result. All runs use ``mode=offline`` so the suite
stays fully offline with no API key and no network — identical to the rest of
the test-suite contract.
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.api.main import app
from app.synthesis.models import SUPPORT_KINDS, SUPPORT_LEVELS

client = TestClient(app)


def _wait_done(task_id: str, timeout: float = 90) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        snap = client.get(f"/api/tasks/{task_id}").json()
        if snap["status"] == "running":
            time.sleep(0.5)
            continue
        return snap
    raise AssertionError("task did not finish in time")


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.6.0"


def test_create_task_returns_real_id():
    response = client.post(
        "/api/tasks",
        json={"task": "分析某市场", "mode": "offline"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["task_id"].startswith("task_")
    assert body["status"] == "created"


def test_create_task_requires_task():
    response = client.post("/api/tasks", json={"task": "", "mode": "offline"})
    assert response.status_code == 422


def test_unknown_task_is_404():
    assert client.get("/api/tasks/nope").status_code == 404
    assert client.get("/api/tasks/nope/team").status_code == 404
    assert client.get("/api/tasks/nope/artifacts").status_code == 404
    assert client.get("/api/tasks/nope/result").status_code == 404
    assert client.get("/api/tasks/nope/events").status_code == 404


def test_full_run_end_to_end():
    """Create -> run -> team -> events -> artifacts -> result."""
    created = client.post(
        "/api/tasks",
        json={"task": "分析当前 AI Agent 市场的发展情况", "mode": "offline"},
    ).json()
    task_id = created["task_id"]

    snapshot = _wait_done(task_id)
    assert snapshot["status"] == "success"
    assert snapshot["run_id"].startswith("run_")

    team = client.get(f"/api/tasks/{task_id}/team").json()
    assert team["task"] == "分析当前 AI Agent 市场的发展情况"
    assert isinstance(team["agents"], list)
    assert len(team["agents"]) >= 1
    for agent in team["agents"]:
        assert agent["id"]
        assert agent["name"]
        assert isinstance(agent["capabilities"], list)
    assert isinstance(team["edges"], list)
    assert isinstance(team["layers"], list)

    events = client.get(f"/api/tasks/{task_id}/events").json()
    assert events["done"] is True
    assert events["event_count"] >= 6
    types = {event["type"] for event in events["events"]}
    assert "TASK_STARTED" in types
    assert "TASK_COMPLETED" in types

    artifacts = client.get(f"/api/tasks/{task_id}/artifacts").json()
    assert isinstance(artifacts["artifacts"], list)
    assert len(artifacts["artifacts"]) >= 1

    result = client.get(f"/api/tasks/{task_id}/result").json()
    assert result["status"] == "success"
    assert result["markdown"]
    assert result["sources"]  # provenance recorded
    assert result["evidence"]
    # v0.6.0 synthesis payload is exposed (structured, not only inside markdown)
    assert isinstance(result["findings"], list)
    assert result["synthesis_status"] in {"completed", "degraded", "failed"}
    for finding in result["findings"]:
        assert finding["finding_id"]
        # v0.6.6: the vocabulary now separates agent agreement from independent
        # sources, so the assertion is against the schema constant (not a
        # hand-written subset that would silently accept a wrong value).
        assert finding["support_kind"] in SUPPORT_KINDS
        assert finding["support_level"] in SUPPORT_LEVELS
        assert finding["review_status"] != "verified"  # never auto-verified


def test_sse_stream_emits_events():
    created = client.post(
        "/api/tasks",
        json={"task": "分析某市场并设计产品方案", "mode": "offline"},
    ).json()
    task_id = created["task_id"]
    # Wait enough for at least the run to finish, then replay the stream.
    _wait_done(task_id)
    with client.stream("GET", f"/api/tasks/{task_id}/stream") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = b"".join(response.iter_bytes())
    text = body.decode("utf-8", errors="replace")
    assert "TASK_STARTED" in text or "task_started" in text
    assert "TASK_COMPLETED" in text or "task_completed" in text


def test_events_history_shape():
    created = client.post(
        "/api/tasks", json={"task": "整理一下思路", "mode": "offline"}
    ).json()
    _wait_done(created["task_id"])
    events = client.get(f"/api/tasks/{created['task_id']}/events").json()
    assert events["event_count"] == len(events["events"])
    for event in events["events"]:
        assert "event_id" in event
        assert "timestamp" in event
        assert "type" in event


def test_artifacts_contain_provenance():
    created = client.post(
        "/api/tasks",
        json={"task": "分析市场竞争与产品方向", "mode": "offline"},
    ).json()
    _wait_done(created["task_id"])
    artifacts = client.get(f"/api/tasks/{created['task_id']}/artifacts").json()["artifacts"]
    for artifact in artifacts:
        assert artifact["agent_id"]
        assert artifact["output_type"]
        # offline provenance: source_type offline_mock, empty urls
        for source in artifact["source_records"]:
            assert source["url"] == ""  # never fabricated
            assert source["source_type"] in ("offline_mock", "web")
        source_ids = {source["id"] for source in artifact["source_records"]}
        for evidence in artifact["evidence"]:
            if evidence["source_id"]:
                assert evidence["source_id"] in source_ids
                assert evidence.get("review_status") != "verified"
            else:
                assert evidence.get("review_status") == "unsupported"


def test_result_matches_final_artifact():
    created = client.post(
        "/api/tasks",
        json={"task": "设计一个 FastAPI 后端系统", "mode": "offline"},
    ).json()
    _wait_done(created["task_id"])
    result = client.get(f"/api/tasks/{created['task_id']}/result").json()
    assert result["title"]
    assert result["markdown"].startswith("# ")
    # sections mirror the core assembler output (each has agent_id + content)
    for section in result["sections"]:
        assert section["agent_id"]
        assert "content" in section
    assert isinstance(result["sources"], list)
    assert isinstance(result["evidence"], list)


def test_api_never_leaks_search_key():
    """Even when a (fake) search key is configured, no endpoint returns it."""
    import os

    os.environ["AUTOTEAM_WEB_SEARCH_API_KEY"] = "sk-super-secret-98765"
    try:
        created = client.post(
            "/api/tasks", json={"task": "分析市场", "mode": "offline"}
        ).json()
        _wait_done(created["task_id"])
        endpoints = [
            f"/api/tasks/{created['task_id']}",
            f"/api/tasks/{created['task_id']}/team",
            f"/api/tasks/{created['task_id']}/artifacts",
            f"/api/tasks/{created['task_id']}/result",
            f"/api/tasks/{created['task_id']}/events",
        ]
        for endpoint in endpoints:
            dumped = client.get(endpoint).text
            assert "sk-super-secret-98765" not in dumped
    finally:
        os.environ.pop("AUTOTEAM_WEB_SEARCH_API_KEY", None)