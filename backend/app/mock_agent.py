"""AGENT_MODE=mock: plausible random decisions so the frontend can be built without Gemini."""

from __future__ import annotations

import random
import time

from .models import Action, Decision, Hazard, PointLabel
from .state import Episode

_REASONS_FORWARD = [
    "Corridor ahead looks clear, advancing.",
    "Moving toward the exit sign.",
    "Path is open, continuing forward.",
]
_REASONS_LOOK = [
    "Scanning {side} for survivors.",
    "Checking the {side} side for hazards.",
]
_HAZARDS = ["fallen ceiling tile", "broken glass", "exposed wiring", "debris pile", "smoke"]


def mock_decision(ep: Episode) -> Decision:
    t0 = time.perf_counter()
    r = random.random()
    if r < 0.7:
        action = Action(move="W", duration_ms=600)
        reason = random.choice(_REASONS_FORWARD)
    elif r < 0.9:
        side = random.choice(["left", "right"])
        action = Action(look=side, duration_ms=400)
        reason = random.choice(_REASONS_LOOK).format(side=side)
    else:
        action = Action(move="none", duration_ms=300)
        reason = "Re-assessing the scene."

    hazards: list[Hazard] = []
    if random.random() < 0.35:
        hazards.append(
            Hazard(
                point=(random.randint(450, 900), random.randint(150, 850)),
                label=random.choice(_HAZARDS),
                severity=random.choice([1, 2, 2, 3]),
            )
        )
    survivors: list[PointLabel] = []
    if random.random() < 0.05:
        survivors.append(PointLabel(point=(random.randint(400, 800), random.randint(200, 800)),
                                    label="person waving"))

    ep.apply(action)
    return Decision(
        episode_id=ep.id,
        ts=time.time(),
        action=action,
        hazards=hazards,
        survivors=survivors,
        exit_seen=random.random() < 0.1,
        pose=ep.pose,
        reason=reason,
        priority="explore toward exit",
        source=ep.agent,
        latency_ms=round((time.perf_counter() - t0) * 1000, 2),
    )
