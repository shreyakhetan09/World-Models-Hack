"""Where did that sound come from? The robot may hear a survivor only once or twice, so each
utterance becomes an observation (a ray from where the robot stood) and sounds are remembered as
estimated map positions. Two observations from different spots are triangulated."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from .audio_engine import relative
from .models import Heard, Pose

MERGE_RADIUS_M = 6.0
ARRIVED_M = 2.0

# sound types the model can report (ER 2 schema enum is a string; see er2.SOUND_TYPES)
SURVIVOR_TYPES = {"human_distress", "child", "tapping"}
HAZARD_TYPES = {"gas_hiss", "structural_creak", "fire", "water", "human_speech_warning"}
IGNORE_TYPES = {"tv_or_radio"}


@dataclass
class Observation:
    origin: tuple[float, float]
    abs_bearing_deg: float  # map frame: 0 = +y, clockwise
    distance_m: float
    t: float


@dataclass
class Remembered:
    sound_type: str
    label: str
    urgency: int
    observations: list[Observation] = field(default_factory=list)
    reached: bool = False

    @property
    def is_survivor(self) -> bool:
        return self.sound_type in SURVIVOR_TYPES

    @property
    def is_hazard(self) -> bool:
        return self.sound_type in HAZARD_TYPES

    @property
    def position(self) -> tuple[float, float]:
        obs = self.observations
        if len(obs) >= 2:
            p = _triangulate(obs[-2], obs[-1])
            if p is not None:
                return p
        # fall back: average of each observation's (bearing, distance) point
        pts = [_point(o) for o in obs]
        return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))

    def relative_to(self, pose: Pose) -> tuple[float, float]:
        return relative(pose, self.position)

    def describe(self, pose: Pose, now: float) -> str:
        b, d = self.relative_to(pose)
        ago = now - self.observations[-1].t
        how = "triangulated from 2 hearings" if len(self.observations) >= 2 else "heard once"
        return f"{self.label} ({self.sound_type}): bearing {b:+.0f}°, ~{d:.0f} m from you now, {how}, last heard {ago:.0f} s ago"


def _point(o: Observation) -> tuple[float, float]:
    a = math.radians(o.abs_bearing_deg)
    return (o.origin[0] + math.sin(a) * o.distance_m, o.origin[1] + math.cos(a) * o.distance_m)


def _triangulate(a: Observation, b: Observation) -> Optional[tuple[float, float]]:
    """Intersect two bearing rays. None if the robot barely moved or the rays are near-parallel."""
    if math.dist(a.origin, b.origin) < 1.0:
        return None
    da = (math.sin(math.radians(a.abs_bearing_deg)), math.cos(math.radians(a.abs_bearing_deg)))
    db = (math.sin(math.radians(b.abs_bearing_deg)), math.cos(math.radians(b.abs_bearing_deg)))
    denom = da[0] * db[1] - da[1] * db[0]
    if abs(denom) < math.sin(math.radians(12)):
        return None
    dx, dy = b.origin[0] - a.origin[0], b.origin[1] - a.origin[1]
    t = (dx * db[1] - dy * db[0]) / denom
    u = (dx * da[1] - dy * da[0]) / denom
    if t <= 0 or u <= 0:
        return None  # intersection behind one of the robots: inconsistent estimate
    p = (a.origin[0] + da[0] * t, a.origin[1] + da[1] * t)
    # sanity: keep it near what the distance estimates said
    if any(math.dist(p, _point(o)) > 8 for o in (a, b)):
        return None
    return p


@dataclass
class SoundMemory:
    items: list[Remembered] = field(default_factory=list)

    def add(self, pose: Pose, bearing_deg: float, distance_m: float, sound_type: str, label: str,
            urgency: int, t: float) -> Remembered:
        """bearing_deg is relative to `pose` (the robot's pose when it heard the sound)."""
        obs = Observation((pose.x, pose.y), pose.heading_deg + bearing_deg, distance_m, t)
        point = _point(obs)
        for r in self.items:
            if r.sound_type == sound_type and math.dist(r.position, point) <= MERGE_RADIUS_M:
                r.observations.append(obs)
                r.urgency = max(r.urgency, urgency)
                r.label = label or r.label
                return r
        r = Remembered(sound_type, label, urgency, [obs])
        self.items.append(r)
        return r

    def target(self, pose: Pose) -> Optional[Remembered]:
        """Survivor to go to: highest urgency, then nearest. Marks arrival."""
        live = [r for r in self.items if r.is_survivor and not r.reached]
        for r in live:
            if r.relative_to(pose)[1] <= ARRIVED_M:
                r.reached = True
        live = [r for r in live if not r.reached]
        return max(live, key=lambda r: (r.urgency, -r.relative_to(pose)[1]), default=None)

    def as_heard(self, pose: Pose) -> list[Heard]:
        out = []
        for r in self.items:
            b, d = r.relative_to(pose)
            out.append(Heard(bearing_deg=round(b), distance_m=round(d, 1), label=r.label,
                             is_hazard=r.is_hazard, is_decoy_suspected=r.sound_type in IGNORE_TYPES,
                             urgency=min(3, max(1, r.urgency))))
        return out

    def context(self, pose: Pose, now: float) -> str:
        if not self.items:
            return ""
        return ("Sounds you heard earlier (they have stopped; positions are remembered estimates):\n"
                + "\n".join(f"  - {r.describe(pose, now)}" + (" [reached]" if r.reached else "")
                            for r in self.items))
