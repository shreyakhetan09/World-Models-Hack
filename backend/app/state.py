"""Episode state + dead-reckoning pose.

Map coordinates (see contract): meters, origin = episode start, heading 0 = initial facing,
positive heading = turned right (clockwise). Forward at heading h is (sin h, cos h).
"""

from __future__ import annotations

import json
import math
import os
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .models import Action, AgentName, Mode, Pose, Scenario
from .audio_engine import AudioScene
from .safety import SafetyLayer
from .sound_memory import SoundMemory

# Calibrate these against Reactor (P3): how far one second of W moves, how fast "look" turns.
SPEED_MPS = float(os.getenv("SPEED_MPS", "1.0"))
TURN_DPS = float(os.getenv("TURN_DPS", "60"))

DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))


def integrate(pose: Pose, action: Action) -> Pose:
    """Advance the pose by one action (dead reckoning)."""
    dt = action.duration_ms / 1000
    heading = pose.heading_deg
    if action.look == "left":
        heading -= TURN_DPS * dt
    elif action.look == "right":
        heading += TURN_DPS * dt
    heading = (heading + 180) % 360 - 180

    h = math.radians(heading)
    fwd = (math.sin(h), math.cos(h))
    right = (math.cos(h), -math.sin(h))
    dist = SPEED_MPS * dt
    dx, dy = {
        "W": (fwd[0] * dist, fwd[1] * dist),
        "S": (-fwd[0] * dist, -fwd[1] * dist),
        "D": (right[0] * dist, right[1] * dist),
        "A": (-right[0] * dist, -right[1] * dist),
    }.get(action.move, (0.0, 0.0))
    return Pose(x=pose.x + dx, y=pose.y + dy, heading_deg=heading)


@dataclass
class Episode:
    scenario: Scenario
    mode: Mode
    agent: AgentName
    imagination: bool
    hearing: bool
    pair_id: Optional[str] = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at: float = field(default_factory=time.time)
    pose: Pose = field(default_factory=Pose)
    trail: list[tuple[float, float]] = field(default_factory=lambda: [(0.0, 0.0)])
    steps: int = 0
    outcome: Optional[str] = None
    log: list[dict[str, Any]] = field(default_factory=list)
    # mission memory for the live agent
    safety: SafetyLayer = field(default_factory=SafetyLayer)
    recent: deque = field(default_factory=lambda: deque(maxlen=5))
    survivors_found: list[str] = field(default_factory=list)
    playbook: list[str] = field(default_factory=list)
    events: list[tuple[float, str]] = field(default_factory=list)  # (time, clause) of world events
    audio: Optional[AudioScene] = None
    decisions_since_audio: int = 0
    # source_id -> what the model said it is (label, is_hazard, is_decoy_suspected, urgency)
    heard_labels: dict = field(default_factory=dict)
    memory: SoundMemory = field(default_factory=SoundMemory)
    # imagination
    imagining: bool = False
    allow_imagine: bool = True          # main.py turns this off if no client can run forks
    pending_imagination: Any = None
    imagined_targets: set = field(default_factory=set)
    plan: list = field(default_factory=list)
    plan_label: str = ""
    plan_total: int = 0
    outbox: list = field(default_factory=list)  # messages for the frontend (imagine_request, ...)
    last_jpeg: Optional[bytes] = None
    busy_until: float = 0.0  # don't decide again until the current plan step has finished
    classifying: bool = False

    def __post_init__(self) -> None:
        if self.audio is None:
            self.audio = AudioScene(sources=list(self.scenario.audio_sources), seed=hash(self.id) % 2**32)

    def apply(self, action: Action) -> None:
        self.pose = integrate(self.pose, action)
        self.trail.append((round(self.pose.x, 2), round(self.pose.y, 2)))
        self.steps += 1

    def record(self, kind: str, **data: Any) -> None:
        self.log.append({"t": round(time.time() - self.started_at, 3), "kind": kind, **data})

    def raw(self) -> dict[str, Any]:
        return {"episode_id": self.id, "scenario_id": self.scenario.id, "agent": self.agent,
                "mode": self.mode, "outcome": self.outcome, "pair_id": self.pair_id,
                "imagination": self.imagination, "hearing": self.hearing,
                "started_at": self.started_at, "trail": self.trail, "log": self.log}

    def summary(self) -> dict[str, Any]:
        from .episodes import summarize

        return summarize(self.raw(), self.scenario.title)

    def save(self) -> Path:
        DATA_DIR.joinpath("episodes").mkdir(parents=True, exist_ok=True)
        path = DATA_DIR / "episodes" / f"{self.id}.json"
        path.write_text(json.dumps({**self.summary(), **self.raw()}, indent=1))
        return path


class EpisodeStore:
    def __init__(self) -> None:
        self.episodes: dict[str, Episode] = {}

    def create(self, **kwargs: Any) -> Episode:
        ep = Episode(**kwargs)
        self.episodes[ep.id] = ep
        return ep

    def get(self, episode_id: str) -> Optional[Episode]:
        return self.episodes.get(episode_id)

    def load(self, episode_id: str) -> Optional[dict[str, Any]]:
        """Raw episode (live or saved) for summaries/timelines."""
        if episode_id in self.episodes:
            ep = self.episodes[episode_id]
            return {**ep.raw(), "scenario_title": ep.scenario.title}
        f = DATA_DIR / "episodes" / f"{episode_id}.json"
        return json.loads(f.read_text()) if f.exists() else None

    def list(self) -> list[dict[str, Any]]:
        """Summaries of all episodes, oldest first. Saved files are re-summarized so older
        episodes get the current fields too."""
        from .episodes import summarize

        out = {e.id: e.summary() for e in self.episodes.values()}
        saved_dir = DATA_DIR / "episodes"
        if saved_dir.exists():
            for f in saved_dir.glob("*.json"):
                if f.stem not in out:
                    try:
                        d = json.loads(f.read_text())
                    except json.JSONDecodeError:
                        continue
                    out[f.stem] = summarize(d, d.get("scenario_title", ""))
        return sorted(out.values(), key=lambda s: s.get("started_at") or 0)
