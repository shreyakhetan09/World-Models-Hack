"""Deterministic safety layer. Runs AFTER every model decision (cloud, onboard, baseline) and can
override it. No model can bypass these rules."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from .models import Action, Hazard

# Region of the frame the robot is about to drive into ([y, x] normalized 0-1000).
AHEAD_Y_MIN = 600
AHEAD_X_MIN, AHEAD_X_MAX = 300, 700
OSCILLATION_WINDOW = 6
# Hearing rules (P16)
AUDIO_HAZARD_CONE_DEG = 30
AUDIO_HAZARD_RANGE_M = 6.0
WARNING_MEMORY_S = 60


def hazard_ahead(hazards: list[Hazard], min_severity: int = 3) -> Optional[Hazard]:
    for h in hazards:
        y, x = h.point
        if h.severity >= min_severity and y >= AHEAD_Y_MIN and AHEAD_X_MIN <= x <= AHEAD_X_MAX:
            return h
    return None


@dataclass
class AudioHazard:
    """A hazard the robot heard. `label` comes from the onboard sound classifier (in this sim: the
    source kind), bearing/distance from the mic array (noisy estimates)."""
    label: str
    bearing_deg: float
    distance_m: float
    is_warning: bool = False  # a spoken "don't come this way"


@dataclass
class SafetyLayer:
    recent_turns: deque = field(default_factory=lambda: deque(maxlen=OSCILLATION_WINDOW))
    # absolute headings someone warned us away from: (time, heading_deg)
    warned_headings: list = field(default_factory=list)

    def check(self, action: Action, hazards: list[Hazard], audio: Optional[list[AudioHazard]] = None,
              heading_deg: float = 0.0) -> tuple[Action, Optional[str]]:
        """Return (possibly replaced action, override reason or None)."""
        now = time.time()
        for a in audio or []:
            if a.is_warning:
                self.warned_headings.append((now, heading_deg + a.bearing_deg))
        self.warned_headings = [(t, h) for t, h in self.warned_headings if now - t < WARNING_MEMORY_S]

        if action.move == "W":
            # Rule A1: invisible hazard heard ahead (gas hiss, creaking structure) -> don't advance.
            for a in audio or []:
                if (not a.is_warning and abs(a.bearing_deg) <= AUDIO_HAZARD_CONE_DEG
                        and a.distance_m <= AUDIO_HAZARD_RANGE_M):
                    self.recent_turns.clear()
                    side = "right" if a.bearing_deg <= 0 else "left"
                    return (Action(look=side, duration_ms=900),
                            f"invisible hazard ahead (audio: {a.label})")
            # Rule A2: someone warned us away from this direction in the last minute.
            for _, h in self.warned_headings:
                if abs(((heading_deg - h) + 180) % 360 - 180) <= AUDIO_HAZARD_CONE_DEG:
                    self.recent_turns.clear()
                    return (Action(look="right", duration_ms=900),
                            "warned away from this direction (audio)")
        # Rule 1: never drive forward into a deadly hazard directly ahead.
        h = hazard_ahead(hazards)
        if h is not None and action.move == "W":
            self.recent_turns.clear()
            side = "right" if h.point[1] < 500 else "left"
            return (Action(move="S", look=side, duration_ms=600),
                    f"{h.label} directly ahead, backing off")

        # Rule 2: break left/right oscillation (the model flip-flopping between turns).
        if action.look in ("left", "right") and action.move == "none":
            self.recent_turns.append(action.look)
            turns = list(self.recent_turns)
            if len(turns) == OSCILLATION_WINDOW and all(a != b for a, b in zip(turns, turns[1:])):
                self.recent_turns.clear()
                if hazard_ahead(hazards, min_severity=2) is None:
                    return Action(move="W", duration_ms=800), "stuck turning back and forth, committing forward"
                return Action(look="right", duration_ms=1500), "stuck turning back and forth, turning 90°"
        else:
            self.recent_turns.clear()
        return action, None


def timeout_action() -> tuple[Action, str]:
    return Action(move="none", duration_ms=300), "re-assessing"
