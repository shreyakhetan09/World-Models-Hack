"""Thin wrappers around google-genai. Model IDs come from env so they can be updated without
code changes (run scripts/list_models.py to see what your key can access)."""

from __future__ import annotations

import io
import os
import wave
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

ER2_MODEL = os.getenv("ER2_MODEL", "gemini-robotics-er-2-preview")
ER2_STREAMING_MODEL = os.getenv("ER2_STREAMING_MODEL", "gemini-robotics-er-2-streaming-preview")
FLASH_MODEL = os.getenv("GEMINI_FLASH_MODEL", "gemini-flash-latest")
IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image")
TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-3.8-flash-tts")


@lru_cache(maxsize=1)
def client():
    from google import genai

    if not os.getenv("GEMINI_API_KEY"):
        raise SystemExit("GEMINI_API_KEY is not set. Put it in backend/.env (see .env.example).")
    return genai.Client()


def with_quota_retry(fn, *args, attempts: int = 6, **kwargs):
    """Call fn, sleeping through 429 RESOURCE_EXHAUSTED using the server's suggested delay."""
    import re
    import time

    from google.genai import errors

    for i in range(attempts):
        try:
            return fn(*args, **kwargs)
        except errors.ClientError as e:
            if e.code != 429 or i == attempts - 1:
                raise
            m = re.search(r"retry in ([\d.]+)s", str(e))
            delay = float(m.group(1)) + 1 if m else 20.0
            print(f"  quota hit, waiting {delay:.0f}s ...", flush=True)
            time.sleep(delay)


def pcm_to_wav(pcm: bytes, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def tts(text: str, style: str, voice: str = "Kore") -> bytes:
    """Speak `text` in `style`, given as short comma-separated audio tags (e.g. 'weak, exhausted').
    Tags in [brackets] steer delivery without being read aloud; a prose prefix like "Say this as ..."
    gets spoken verbatim by this model. Returns WAV bytes."""
    from google.genai import types

    resp = with_quota_retry(
        client().models.generate_content,
        model=TTS_MODEL,
        contents=f"[{style}] {text}" if style else text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                )
            ),
        ),
    )
    part = resp.candidates[0].content.parts[0]
    mime = part.inline_data.mime_type or ""
    rate = int(mime.split("rate=")[1].split(";")[0]) if "rate=" in mime else 24000
    return pcm_to_wav(part.inline_data.data, rate)


def transcribe(wav: bytes) -> str:
    from google.genai import types

    r = with_quota_retry(client().models.generate_content, model=FLASH_MODEL, contents=[
        types.Part.from_bytes(data=wav, mime_type="audio/wav"),
        "Transcribe exactly every word spoken. Output only the transcript."])
    return (r.text or "").strip()


def generate_image(prompt: str) -> bytes:
    """Returns image bytes (PNG/JPEG as produced by the model)."""
    from google.genai import types

    resp = with_quota_retry(
        client().models.generate_content,
        model=IMAGE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio="16:9"),
        ),
    )
    for part in resp.candidates[0].content.parts:
        if part.inline_data and part.inline_data.data:
            return part.inline_data.data
    raise RuntimeError("image model returned no image")
