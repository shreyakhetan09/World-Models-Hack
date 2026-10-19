"""Live decision flow with ER 2 stubbed out: listen -> utterance captured -> remembered -> imagine."""
import asyncio
import base64
import time

import app.autopilot as ap
from app.er2 import ActionOut, DecisionOut, HeardOut
from app.models import ImagineRequest
from app.scenarios import get_scenario
from app.state import Episode

JPEG = base64.b64encode(b"\xff\xd8fake").decode()


def fake_decide(jpeg, context, audio_wav=None, mic_array=None, **_):
    heard = []
    if audio_wav:
        heard = [HeardOut(bearing_deg=-45, distance_m=5, label="weak voice calling for help",
                          sound_type="human_distress", is_hazard=False, is_decoy_suspected=False, urgency=3)]
    return DecisionOut(survivors=[], hazards=[], heard=heard, exit_seen=False, priority="search",
                       action=ActionOut(move="W", look="none", duration_ms=800), reason="test"), 5.0


def test_listen_then_remember_then_imagine(monkeypatch):
    monkeypatch.setattr(ap, "decide_sync", fake_decide)
    ep = Episode(scenario=get_scenario("office_trapped_worker"), mode="autopilot", agent="cloud",
                 imagination=True, hearing=True)

    d = asyncio.run(ap.live_decision(ep, JPEG))
    assert d.priority == "listen" and d.action.move == "none"

    # fast-forward past the first utterance, as the 4 Hz ticker would
    ep.audio.started_at = time.time() - 6.5
    ep.audio.tick(ep.pose)
    ep.audio.started_at = time.time() - 20
    ep.audio.tick(ep.pose)
    assert ep.audio.captures, "the utterance should have been recorded"

    ev = ap.classify_capture(ep, ep.audio.take_capture())
    assert ev is not None and ev.is_survivor and "Remembering" in ev.reason
    d = asyncio.run(ap.live_decision(ep, JPEG))
    assert ep.memory.items and ep.memory.items[0].sound_type == "human_distress"
    assert ep.imagining and isinstance(ep.outbox[0], ImagineRequest)
    assert "Imagining" in d.reason
