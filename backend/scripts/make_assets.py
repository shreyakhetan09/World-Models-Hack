"""Generate demo assets: scenario reference images (Gemini image model), survivor voices
(Gemini TTS) and procedural sound effects. Skips files that already exist.

Usage:
  .venv/bin/python -m scripts.make_assets            # everything
  .venv/bin/python -m scripts.make_assets fx         # only sound effects (no API key needed)
  .venv/bin/python -m scripts.make_assets images voices
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

from app import audio_synth
from app.scenarios import PRESETS

STATIC = Path(__file__).resolve().parent.parent / "static"

# (filename, text, style, voice). Filenames match AudioSource.clip_url in scenarios.py.
VOICES = [
    ("help_im_stuck_weak", "Help! I'm stuck under here!", "weak, exhausted, frightened, calling out", "Kore"),
    ("help_im_stuck_panicked", "Help! Somebody help me, I'm stuck!", "panicked, shouting", "Fenrir"),
    ("is_anyone_there_child", "Is anyone there? I'm scared.", "child, crying, frightened", "Leda"),
    ("dont_come_this_way", "Don't come this way, the floor collapsed!", "urgent, shouting", "Charon"),
    ("leg_trapped", "My leg is trapped, please hurry.", "in pain, breathing hard", "Puck"),
    ("over_here_shout", "Over here! On the car roof!", "loud, shouting", "Zephyr"),
    ("by_the_stairs", "Over here, by the stairs!", "tired, calling out", "Aoede"),
    ("ayuda_spanish", "¡Ayuda! ¡Estoy atrapada aquí!", "frightened, shouting", "Kore"),
    ("bachao_hindi", "Bachao! Koi hai? Main yahan phansa hoon!", "frightened, shouting", "Puck"),
    ("please_im_in_here", "Please... I'm in here... I can't move my leg.", "weak, hoarse, exhausted, frightened", "Kore"),
    ("robot_callout", "This is a rescue robot. If you can hear me, call out!", "", "Charon"),
    ("tv_news_decoy", "Good evening. In tonight's top story, emergency crews continue their work across the city.",
     "calm news anchor", "Charon"),
]


def make_fx() -> None:
    out = STATIC / "audio" / "fx"
    out.mkdir(parents=True, exist_ok=True)
    names = {"dog_bark": "dog_bark", "rushing_water": "rushing_water", "creak": "creak", "sos_knock": "sos_knock",
             "fire_crackle": "fire_crackle", "fire_alarm": "fire_alarm", "gas_hiss": "gas_hiss"}
    for key, fn in audio_synth.EFFECTS.items():
        path = out / f"{names[key]}.wav"
        if path.exists():
            continue
        sf.write(path, fn(), audio_synth.SR, subtype="PCM_16")
        print("fx   ", path.relative_to(STATIC))


def spoke_only_the_line(heard: str, text: str, style: str) -> bool:
    import re

    words = lambda t: re.findall(r"[\w']+", t.lower())  # noqa: E731
    h, line = words(heard), set(words(text))
    tags = {w for w in words(style) if w not in line}
    return not (set(h[:4]) & tags) and len(h) <= len(words(text)) + 1


def trim_file(path: Path) -> None:
    data, sr = sf.read(path, dtype="float32")
    sf.write(path, audio_synth.trim_silence(np.asarray(data), sr), sr, subtype="PCM_16")


def make_voices() -> None:
    from app.genai_client import transcribe, tts

    out = STATIC / "audio" / "voices"
    out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name, text, style, voice in VOICES:
        path = out / f"{name}.wav"
        manifest.append({"file": path.name, "text": text, "style": style, "voice": voice})
        if path.exists():
            continue
        for attempt in range(5):  # the TTS model occasionally speaks its style tags; retry until clean
            path.write_bytes(tts(text, style, voice))
            trim_file(path)
            heard = transcribe(path.read_bytes())
            if spoke_only_the_line(heard, text, style):
                break
        print("voice", path.relative_to(STATIC), f"OK (attempt {attempt + 1})"
              if spoke_only_the_line(heard, text, style) else "STILL SPEAKS TAGS", "->", heard[:90])
        # muffled variant for "behind a wall / under rubble"
        data, sr = sf.read(path, dtype="float32")
        sf.write(out / f"{name}_muffled.wav", audio_synth.muffle(np.asarray(data)), sr, subtype="PCM_16")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False))


def make_images() -> None:
    from app.genai_client import generate_image

    out = STATIC / "scenarios"
    out.mkdir(parents=True, exist_ok=True)
    for s in PRESETS:
        path = out / Path(s.reference_image_url).name
        if path.exists():
            continue
        data = generate_image(
            "Photorealistic first-person view at eye level, wide angle, as seen by a rescue robot's "
            f"camera: {s.world_prompt}. No text, no people in the foreground."
        )
        path.write_bytes(data)
        print("image", path.relative_to(STATIC))


if __name__ == "__main__":
    which = set(sys.argv[1:]) or {"fx", "voices", "images"}
    if "trim" in which:  # one-off: trim silence from existing voice clips (and rebuild muffled ones)
        for f in sorted((STATIC / "audio" / "voices").glob("*.wav")):
            if f.stem.endswith("_muffled"):
                continue
            trim_file(f)
            data, sr = sf.read(f, dtype="float32")
            sf.write(f.with_name(f.stem + "_muffled.wav"), audio_synth.muffle(np.asarray(data)), sr, subtype="PCM_16")
            print("trimmed", f.name, f"{len(data) / sr:.1f}s")
    if "fx" in which:
        make_fx()
    if "voices" in which:
        make_voices()
    if "images" in which:
        make_images()
