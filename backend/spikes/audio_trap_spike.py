"""P0-C: does hearing change ER 2's decision? Does "imagining" change its choice at a trap?

Part 1 sends the SAME calm-corridor frame with and without each audio clip (+ a mic-array line)
and compares the decisions. Part 2 asks ER 2 to choose at a two-door trap with only the current
frame vs. with imagined frames per option (made by the Gemini image model as a stand-in for
Reactor forks), 5 times each.

Prereq: .venv/bin/python -m scripts.make_assets   (fx + voices + images)
Usage:  .venv/bin/python -m spikes.audio_trap_spike [part1|part2]
Writes spikes/out_p0c/RESULTS_P0C.md
"""

from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

from PIL import Image

from app.er2 import decide_sync
from app.genai_client import ER2_MODEL, client, generate_image

ROOT = Path(__file__).resolve().parent.parent
AUDIO = ROOT / "static" / "audio"
OUT = Path(__file__).resolve().parent / "out_p0c"

CASES = [  # (clip, mic-array line, what a correct agent should do)
    ("voices/help_im_stuck_weak_muffled.wav", "source at bearing -120°, ~8 m, muffled", "turn left toward caller"),
    ("voices/dont_come_this_way.wav", "source at bearing +5°, ~12 m", "do not advance"),
    ("voices/tv_news_decoy.wav", "source at bearing -60°, ~6 m", "ignore / flag decoy"),
    ("voices/is_anyone_there_child.wav", "source at bearing +100°, ~10 m", "turn right toward caller"),
    ("fx/gas_hiss.wav", "source at bearing +10°, ~4 m", "do not advance"),
    ("fx/creak.wav", "source at bearing 0°, ~3 m, overhead", "do not advance / reroute"),
    ("fx/sos_knock.wav", "source at bearing +140°, ~7 m, muffled", "turn toward tapping"),
]

CORRIDOR_PROMPT = ("Photorealistic first-person view of a calm, empty, dimly lit office corridor after an "
                   "earthquake, some dust, clear floor ahead, closed doors on both sides. No people, no text.")
TRAP_PROMPT = ("Photorealistic first-person view standing in a dusty corridor facing two exits: a closed door "
               "on the LEFT with faint grey smoke seeping from under it, and an open stairwell on the RIGHT "
               "going down. No people, no text.")
IMAGINED = {
    "left": "Photorealistic first-person view just through a door into a corridor where the ceiling is "
            "collapsing, thick smoke, fire glow, debris falling. No people, no text.",
    "right": "Photorealistic first-person view going down a concrete stairwell, dusty but clear, a green "
             "exit sign at the bottom. No people, no text.",
}


def jpeg_of(data: bytes) -> bytes:
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((1024, 1024))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def cached_image(name: str, prompt: str) -> bytes:
    path = OUT / f"{name}.jpg"
    if not path.exists():
        path.write_bytes(jpeg_of(generate_image(prompt)))
    return path.read_bytes()


def part1() -> list[str]:
    frame = cached_image("calm_corridor", CORRIDOR_PROMPT)
    base, base_ms = decide_sync(frame)
    rows = ["## Part 1: hearing", "",
            f"Without audio: **{base.action.move}/{base.action.look}**: {base.reason} ({base_ms:.0f} ms)", "",
            "| clip | mic array | expected | with audio: action | reason | heard | ms |", "|---|---|---|---|---|---|---|"]
    for clip, mic, expected in CASES:
        path = AUDIO / clip
        if not path.exists():
            rows.append(f"| {clip} | missing, run make_assets |  |  |  |  |  |")
            continue
        d, ms = decide_sync(frame, audio_wav=path.read_bytes(), mic_array=mic)
        heard = "; ".join(f"{h.label} @{h.bearing_deg:.0f}°" for h in d.heard)
        rows.append(f"| {clip} | {mic} | {expected} | {d.action.move}/{d.action.look} | {d.reason} | {heard} | {ms:.0f} |")
        print(rows[-1])
    return rows


def choose(contents: list) -> str:
    from google.genai import types

    resp = client().models.generate_content(
        model=ER2_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema={"type": "object", "properties": {
                "choice": {"type": "string", "enum": ["left", "right"]}, "reason": {"type": "string"}},
                "required": ["choice", "reason"]},
            temperature=1.0,
        ),
    )
    return json.loads(resp.text)["choice"]


def part2(n: int = 5) -> list[str]:
    from google.genai import types

    now = cached_image("trap_now", TRAP_PROMPT)
    left = cached_image("imagined_left", IMAGINED["left"])
    right = cached_image("imagined_right", IMAGINED["right"])
    q = "You are a rescue robot. Which exit do you take to reach safety: left door or right stairwell?"
    img = lambda b: types.Part.from_bytes(data=b, mime_type="image/jpeg")  # noqa: E731

    without = [choose([img(now), q]) for _ in range(n)]
    with_imag = [choose([img(now), "Current view.", img(left), "Imagined future if you take the LEFT door.",
                         img(right), "Imagined future if you take the RIGHT stairwell.", q]) for _ in range(n)]
    rows = ["", "## Part 2: imagination at a trap (correct = right)", "",
            "| condition | choices | correct |", "|---|---|---|",
            f"| current frame only | {', '.join(without)} | {without.count('right')}/{n} |",
            f"| + imagined futures | {', '.join(with_imag)} | {with_imag.count('right')}/{n} |"]
    print("\n".join(rows))
    return rows


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    which = set(sys.argv[1:]) or {"part1", "part2"}
    rows = [f"# P0-C results ({time.strftime('%Y-%m-%d %H:%M')}, model {ER2_MODEL})", ""]
    if "part1" in which:
        rows += part1()
    if "part2" in which:
        rows += part2()
    (OUT / "RESULTS_P0C.md").write_text("\n".join(rows) + "\n")
    print(f"\nWrote {OUT / 'RESULTS_P0C.md'}")
