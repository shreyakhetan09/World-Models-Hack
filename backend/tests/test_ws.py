import json
import os
import tempfile

os.environ["AGENT_MODE"] = "mock"
os.environ["DECISION_MIN_INTERVAL_MS"] = "0"
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="rescuesim-test-")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.models import Action, Pose  # noqa: E402
from app.state import integrate  # noqa: E402

client = TestClient(app)


def recv(ws, type_):
    """Next message of the given type (audio_state ticks are interleaved)."""
    for _ in range(200):
        msg = json.loads(ws.receive_text())
        if msg["type"] == type_:
            return msg
    raise AssertionError(f"no {type_} message")

TINY_JPEG_B64 = "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEB"


def test_health_and_scenarios():
    assert client.get("/health").json()["ok"] is True
    scenarios = client.get("/scenarios").json()
    assert {s["id"] for s in scenarios} >= {"earthquake_office", "flooded_street", "warehouse_fire"}


def test_episode_frame_decision_end():
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "start_episode", "scenario_id": "earthquake_office",
                                 "mode": "autopilot", "agent": "cloud",
                                 "imagination": False, "hearing": False}))
        started = recv(ws, "episode_started")
        assert started["type"] == "episode_started"
        eid = started["episode_id"]

        ws.send_text(json.dumps({"type": "frame", "episode_id": eid, "ts": 0,
                                 "jpeg_b64": TINY_JPEG_B64}))
        decision = recv(ws, "decision")
        assert decision["type"] == "decision"
        assert decision["action"]["move"] in {"W", "A", "S", "D", "none"}
        assert set(decision["pose"]) == {"x", "y", "heading_deg"}

        assert recv(ws, "audio_state")["sources"]
        ws.send_text(json.dumps({"type": "end_episode", "episode_id": eid, "outcome": "timeout"}))
        summary = recv(ws, "episode_summary")
        assert summary["type"] == "episode_summary"


def test_invalid_message_returns_error():
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "nope"}))
        assert json.loads(ws.receive_text())["type"] == "error"
        ws.send_text(json.dumps({"type": "frame", "episode_id": "missing", "ts": 0,
                                 "jpeg_b64": ""}))
        assert json.loads(ws.receive_text())["type"] == "error"


def test_dead_reckoning():
    p = integrate(Pose(), Action(move="W", duration_ms=1000))
    assert abs(p.y - 1.0) < 1e-6 and abs(p.x) < 1e-6
    p = integrate(p, Action(look="right", duration_ms=1500))  # 90 degrees right
    assert abs(p.heading_deg - 90) < 1e-6
    p = integrate(p, Action(move="W", duration_ms=1000))
    assert abs(p.x - 1.0) < 1e-6 and abs(p.y - 1.0) < 1e-6


def test_episode_history_and_detail():
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"type": "start_episode", "scenario_id": "office_trapped_worker",
                                 "mode": "autopilot", "agent": "cloud", "imagination": False, "hearing": True}))
        eid = recv(ws, "episode_started")["episode_id"]
        ws.send_text(json.dumps({"type": "end_episode", "episode_id": eid, "outcome": "timeout"}))
        assert recv(ws, "episode_summary")["score"] == 0
    body = client.get("/episodes").json()
    assert "score_rubric" in body and any(e["episode_id"] == eid for e in body["episodes"])
    detail = client.get(f"/episodes/{eid}").json()
    assert detail["scenario_title"] == "Earthquake: Trapped Worker"
    assert [t["kind"] for t in detail["timeline"]][0] == "start" and detail["timeline"][-1]["kind"] == "end"
    assert client.get("/episodes/nope").status_code == 404


def test_score_rubric():
    from app.episodes import score
    assert score(0, None, 0) == 0
    assert score(1, 0, 0) == 70          # found immediately
    assert score(1, 120, 0) == 50        # found at the time limit
    assert score(1, 60, 2) == 54
    assert score(3, 0, 0) == 100
