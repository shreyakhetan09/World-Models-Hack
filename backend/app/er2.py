"""Gemini Robotics ER 2 calls: the robot's perception + decision step.

The model never sees ground truth (source ids, kinds, transcripts). It gets a frame, optionally
an audio clip + mic-array bearing estimates, and the mission context.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

import os

from .genai_client import ER2_MODEL, ER2_STREAMING_MODEL, client

# Thinking off cut median latency 4.1 s -> 1.8 s on our scenes with the same decisions (2026-10-08).
THINKING_BUDGET = int(os.getenv("ER2_THINKING_BUDGET", "0"))

SYSTEM_PROMPT = """You are the onboard brain of an autonomous search-and-rescue robot inside a disaster zone.
You see through a forward-facing camera and may also hear through a microphone array.
Goals, in priority order:
 1. Never move into hazards (fire, smoke, deep or dark water, live wires, collapsing structure, gas).
 2. Find and reach survivors, including ones you can only HEAR (voices, crying, tapping).
 3. Find the exit.
Rules for sound: voices may be survivors even when nothing is visible; muffled = behind a wall or
under debris; a voice that goes silent raises urgency; spoken warnings ("don't come this way") are
hazard information for that direction; hissing, creaking or rushing water are hazards you may not
see; TV/radio-like or repeating broadcast voices may be decoys. Animals (e.g. a dog barking) are not
the human survivor you are searching for: note them, but go to humans first.
Sounds are often brief: a person may call out only once or twice and then go quiet. When you get a
recording, classify it carefully (sound_type) and estimate where it came from; you will NOT hear it
again, so commit to the remembered position. When survivors compete, prioritize by
urgency, then whether they can be reached safely, then distance.
A survivor you can hear outranks the exit: go to them first, even if the exit is visible and the
voice comes from the side or behind you. Turn toward the sound before moving.
Image points are [y, x] normalized to 0-1000. Bearings: 0 = straight ahead, +90 = right, -90 = left.
Controls: move W=forward, S=back, A=strafe left, D=strafe right; look left/right turns the camera.
Pick ONE action per step with duration_ms 300-1500. Keep "reason" to one short sentence.
Mark EVERY visible hazard, even partial ones: debris piles, fallen ceiling panels, exposed or hanging
wires, broken glass, holes or cracks in the floor, smoke, fire, water, unstable furniture or shelving.
Dense dust or smoke clouds that hide the floor ahead are severity 2: never drive blind into them.
Severity: 1 = slows you down, 2 = could damage you, 3 = would destroy you (fire, deep water, live
wires, collapse). Point at where the hazard touches the floor or is closest to you.
Prefer forward progress when the floor ahead is clear; turn only with a reason."""


class PointOut(BaseModel):
    point: list[int] = Field(description="[y, x] normalized 0-1000")
    label: str


class HazardOut(PointOut):
    severity: int = Field(description="1 = minor, 2 = serious, 3 = deadly")

    @field_validator("severity")
    @classmethod
    def _clamp(cls, v: int) -> int:
        return min(3, max(1, v))


SOUND_TYPES = ["human_distress", "child", "human_speech_warning", "dog_or_animal", "tapping", "gas_hiss",
               "structural_creak", "water", "fire", "alarm", "tv_or_radio", "unknown"]


class HeardOut(BaseModel):
    bearing_deg: float
    distance_m: float
    label: str
    sound_type: str = Field(description="one of: " + ", ".join(SOUND_TYPES))
    is_hazard: bool
    is_decoy_suspected: bool
    urgency: int = Field(description="1 = low, 2 = medium, 3 = critical")

    @field_validator("urgency")
    @classmethod
    def _clamp(cls, v: int) -> int:
        return min(3, max(1, v))


class ActionOut(BaseModel):
    move: Literal["W", "A", "S", "D", "none"]
    look: Literal["left", "right", "up", "down", "none"]
    duration_ms: int


class DecisionPointOption(BaseModel):
    label: str
    description: str


class DecisionOut(BaseModel):
    survivors: list[PointOut]
    hazards: list[HazardOut]
    heard: list[HeardOut]
    exit_seen: bool
    priority: str
    action: ActionOut
    reason: str
    decision_point: Optional[list[DecisionPointOption]] = Field(
        default=None, description="Only when the path forks: 2-3 options worth imagining first")


def build_user_text(context: str = "", mic_array: Optional[str] = None) -> str:
    parts = ["Decide the next action from the current camera frame."]
    if mic_array:
        parts.append(f"MIC ARRAY (estimates, ±15°): {mic_array}")
        parts.append("The attached audio is what the microphones hear right now.")
    else:
        parts.append("No audio this step; heard = [].")
    if context:
        parts.append(f"Mission context:\n{context}")
    return "\n".join(parts)


def decide_sync(jpeg: bytes, context: str = "", audio_wav: Optional[bytes] = None,
                mic_array: Optional[str] = None, model: str = ER2_MODEL) -> tuple[DecisionOut, float]:
    """Standard (non-streaming) endpoint with enforced JSON schema. Returns (decision, latency_ms).

    This is the endpoint the agent loop uses: in P0-A it was ~0.5 s slower than the streaming
    endpoint but its decisions were correct in all 3 scenes, while the streaming endpoint (frame
    sent as realtime video input) misread scenes and walked toward fire."""
    from google.genai import types

    contents: list = [types.Part.from_bytes(data=jpeg, mime_type="image/jpeg")]
    if audio_wav:
        contents.append(types.Part.from_bytes(data=audio_wav, mime_type="audio/wav"))
    contents.append(build_user_text(context, mic_array if audio_wav else None))

    t0 = time.perf_counter()
    resp = client().models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=DecisionOut,
            temperature=0.2,
            thinking_config=types.ThinkingConfig(thinking_budget=THINKING_BUDGET),
        ),
    )
    latency = (time.perf_counter() - t0) * 1000
    parsed = resp.parsed if isinstance(resp.parsed, DecisionOut) else DecisionOut.model_validate_json(resp.text)
    return parsed, latency


_JSON_RE = re.compile(r"\{.*\}", re.S)


async def decide_streaming(jpeg: bytes, context: str = "",
                           model: str = ER2_STREAMING_MODEL) -> tuple[Optional[DecisionOut], float, str]:
    """One step over the Live (streaming) endpoint. Schema is requested in the prompt, not enforced.
    Returns (decision or None if unparseable, latency_ms, raw_text)."""
    from google.genai import types

    schema = json.dumps(DecisionOut.model_json_schema())
    config = types.LiveConnectConfig(
        response_modalities=["TEXT"],
        system_instruction=SYSTEM_PROMPT + "\nReply with ONLY a JSON object matching this schema:\n" + schema,
    )
    async with client().aio.live.connect(model=model, config=config) as session:
        t0 = time.perf_counter()
        await session.send_realtime_input(video=types.Blob(data=jpeg, mime_type="image/jpeg"))
        await session.send_realtime_input(text=build_user_text(context))
        text = ""
        async for msg in session.receive():
            sc = msg.server_content
            if msg.text:
                text += msg.text
            # this endpoint delivers its text reply as output_transcription
            elif sc and sc.output_transcription and sc.output_transcription.text:
                text += sc.output_transcription.text
            if sc and sc.turn_complete:
                break
        latency = (time.perf_counter() - t0) * 1000
    m = _JSON_RE.search(text)
    try:
        return (DecisionOut.model_validate_json(m.group(0)) if m else None), latency, text
    except Exception:
        return None, latency, text


def run_streaming(jpeg: bytes, context: str = ""):
    return asyncio.run(decide_streaming(jpeg, context))
