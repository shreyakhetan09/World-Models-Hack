"""Imagination (P5): before committing to a route, the robot forks the world model from its current
frame, runs each candidate maneuver in its own Reactor session, and lets ER 2 judge the imagined
outcomes. The best one is then executed in the real world."""

from __future__ import annotations

import base64
import json
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel

from .genai_client import ER2_MODEL, client
from .models import Action, ImagineOption, ImagineRequest, ImagineResults, ImagineScore, ImagineVerdict
from .sound_memory import Remembered

import os

RISK_WEIGHT = 1.5
TURN_90_MS = 1500
TURN_DPS = float(os.getenv("TURN_DPS", "60"))


@dataclass
class Maneuver:
    id: str
    label: str
    clause: str  # appended to the scenario's base prompt in the forked world
    drive: list[Action]


def _forward(n: int = 3) -> list[Action]:
    return [Action(move="W", duration_ms=1500) for _ in range(n)]


def candidate_maneuvers(target_bearing: float, target_distance: float = 6.0) -> list[Maneuver]:
    """Three options: toward the remembered sound, straight on, and away from it.
    The 'toward' option drives far enough to reach the remembered spot (1.5 m per step, max 4)."""
    toward = "left" if target_bearing < 0 else "right"
    away = "right" if toward == "left" else "left"
    # turn just far enough to face the remembered sound (not a fixed 90°)
    turn_ms = int(min(2500, max(300, abs(target_bearing) / TURN_DPS * 1000)))
    return [
        Maneuver(f"turn_{toward}", f"Turn {toward} toward the voice",
                 f"The robot turns {toward} and rolls through the opening on the {toward} into the next room.",
                 [Action(look=toward, duration_ms=turn_ms),
                  *_forward(int(min(4, max(1, round((target_distance - 1.5) / 1.5)))))]),
        Maneuver("forward", "Continue straight ahead",
                 "The robot keeps rolling straight ahead down the corridor, closer and closer to whatever lies ahead.",
                 _forward(2)),
        Maneuver(f"turn_{away}", f"Turn {away}, away from the voice",
                 f"The robot turns {away} and rolls forward toward the {away}-hand side.",
                 [Action(look=away, duration_ms=TURN_90_MS), *_forward(2)]),
    ]


@dataclass
class PendingImagination:
    request_id: str
    target_label: str
    target_bearing: float
    target_distance: float
    maneuvers: dict[str, Maneuver]
    started: float


def build_request(episode_id: str, target: Remembered, bearing: float, distance: float
                  ) -> tuple[ImagineRequest, PendingImagination]:
    mans = candidate_maneuvers(bearing, distance)
    rid = uuid.uuid4().hex[:8]
    req = ImagineRequest(episode_id=episode_id, request_id=rid, options=[
        ImagineOption(id=m.id, label=m.label, world_prompt=m.clause, drive=m.drive) for m in mans])
    return req, PendingImagination(rid, target.label, bearing, distance, {m.id: m for m in mans}, time.time())


class _Score(BaseModel):
    id: str
    risk: float
    progress: float
    summary: str


class _Scores(BaseModel):
    scores: list[_Score]


def score(pending: PendingImagination, results: ImagineResults, current_jpeg: Optional[bytes]
          ) -> ImagineVerdict:
    """One ER 2 call over all imagined futures."""
    from google.genai import types

    parts: list = []
    if current_jpeg:
        parts += ["CURRENT VIEW (before acting):", types.Part.from_bytes(data=current_jpeg, mime_type="image/jpeg")]
    for opt in results.options:
        parts.append(f"OPTION {opt.id}: {opt.label}. Imagined frames after executing it, in order:")
        parts += [types.Part.from_bytes(data=base64.b64decode(f), mime_type="image/jpeg") for f in opt.frames_b64]
    parts.append(
        f"You are a rescue robot. You heard {pending.target_label} at bearing {pending.target_bearing:+.0f}° "
        f"(negative = left), about {pending.target_distance:.0f} m away; the sound has stopped. "
        "Each option above was simulated in a world model from the current view. For EACH option rate: "
        "risk 0-10 (hazards entered, blocked or collapsing paths, fire, water, falling debris; 10 = deadly), "
        "progress 0-10 (how much closer it brings you to reaching the person, e.g. entering the room the voice "
        "came from; 10 = reached them). One-sentence summary of what happened in the imagined future.")
    resp = client().models.generate_content(
        model=ER2_MODEL, contents=parts,
        config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=_Scores,
                                           temperature=0.2,
                                           thinking_config=types.ThinkingConfig(thinking_budget=0)))
    parsed = resp.parsed if isinstance(resp.parsed, _Scores) else _Scores.model_validate(json.loads(resp.text))
    known = {o.id for o in results.options}
    scores = [ImagineScore(id=s.id, risk=max(0, min(10, s.risk)), progress=max(0, min(10, s.progress)),
                           summary=s.summary) for s in parsed.scores if s.id in known]
    if not scores:
        raise ValueError("no usable scores")
    best = max(scores, key=lambda s: (s.progress - RISK_WEIGHT * s.risk, -s.risk))
    reason = (f"Imagined {len(scores)} futures; chose '{pending.maneuvers[best.id].label}' "
              f"(progress {best.progress:.0f}/10, risk {best.risk:.0f}/10): {best.summary}")
    return ImagineVerdict(episode_id=results.episode_id, request_id=results.request_id, scores=scores,
                          chosen_id=best.id, reason=reason)


def fallback_verdict(pending: PendingImagination, episode_id: str, why: str) -> ImagineVerdict:
    """No imagined futures (timeout/error): take the maneuver toward the sound."""
    first = next(iter(pending.maneuvers.values()))
    return ImagineVerdict(episode_id=episode_id, request_id=pending.request_id, scores=[],
                          chosen_id=first.id, reason=f"Imagination unavailable ({why}); heading toward the sound.")
