"""Audio scene engine + simulated microphone array (P16).

Reactor renders video only, so sound lives here: sources sit at map positions, and from the
robot's dead-reckoned pose we compute what it hears. Two views of the same scene:
  - ground truth (true bearing/distance/gain) -> frontend speakers + operator radar
  - mic-array estimates (noisy bearing/distance, front/back confusion) -> the robot's brain
The model never sees source ids, kinds or transcripts.
"""

from __future__ import annotations

import io
import math
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

from . import audio_synth
from .models import AudioSource, AudioSourceState, Pose

SR = 16000
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
AUDIBLE_GAIN = 0.04          # below this the mic array doesn't pick the source up
BEARING_SIGMA_DEG = 12.0
FRONT_BACK_CONFUSION = 0.05
REVEAL_FACING_DEG = 60.0


def wrap_deg(a: float) -> float:
    return (a + 180) % 360 - 180


def relative(pose: Pose, pos: tuple[float, float]) -> tuple[float, float]:
    """(bearing_deg relative to heading, distance_m). Heading 0 faces +y, positive = clockwise."""
    dx, dy = pos[0] - pose.x, pos[1] - pose.y
    absolute = math.degrees(math.atan2(dx, dy))
    return wrap_deg(absolute - pose.heading_deg), math.hypot(dx, dy)


def position_from(pose: Pose, bearing_deg: float, distance_m: float) -> tuple[float, float]:
    a = math.radians(pose.heading_deg + bearing_deg)
    return (round(pose.x + math.sin(a) * distance_m, 2), round(pose.y + math.cos(a) * distance_m, 2))


@lru_cache(maxsize=64)
def load_clip(clip_url: str) -> np.ndarray:
    path = STATIC_DIR / clip_url.removeprefix("/static/")
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    if sr != SR:
        n = int(len(mono) * SR / sr)
        mono = np.interp(np.linspace(0, len(mono) - 1, n), np.arange(len(mono)), mono).astype(np.float32)
    return mono


def clip_seconds(clip_url: str) -> float:
    return len(load_clip(clip_url)) / SR


@dataclass
class Capture:
    """One finished utterance as the robot recorded it: what it heard and from where.
    Bearing is the mic-array estimate relative to the robot's heading AT CAPTURE TIME."""
    source: AudioSource
    clip_url: str
    pose: Pose
    bearing_deg: float
    distance_m: float
    gain: float
    wav: bytes
    at_s: float

    def estimated_position(self) -> tuple[float, float]:
        return position_from(self.pose, self.bearing_deg, self.distance_m)


@dataclass
class Estimate:
    """What the mic array reports for one audible source."""
    source: AudioSource
    bearing_deg: float
    distance_m: float
    true_bearing_deg: float
    true_distance_m: float
    gain: float


@dataclass
class AudioScene:
    sources: list[AudioSource]
    started_at: float = field(default_factory=time.time)
    seed: int = 0
    revealed: set[str] = field(default_factory=set)
    _was_audible: set[str] = field(default_factory=set)
    _pending_event: Optional[str] = None
    _open_plays: dict = field(default_factory=dict)   # (source_id, idx) -> pose at utterance start
    _done_plays: set = field(default_factory=set)
    captures: list = field(default_factory=list)      # finished utterances waiting for the brain

    def __post_init__(self) -> None:
        self.rng = np.random.default_rng(self.seed)

    # ----- time & activity -----
    def elapsed(self, now: Optional[float] = None) -> float:
        return (now or time.time()) - self.started_at

    def _windows(self, s: AudioSource) -> list[tuple[int, float, float, str]]:
        """(index, start, end, clip_url) for each play-once utterance."""
        out = []
        for i, p in enumerate(s.plays or []):
            url = p.clip_url or s.clip_url
            out.append((i, p.at_s, p.at_s + clip_seconds(url), url))
        return out

    def _current_play(self, s: AudioSource, t: float):
        return next((w for w in self._windows(s) if w[1] <= t < w[2]), None)

    def _active(self, s: AudioSource, t: float) -> bool:
        if s.plays is not None:
            return self._current_play(s, t) is not None
        return t >= s.start_s and (s.stop_s is None or t < s.stop_s)

    def gain(self, s: AudioSource, distance: float) -> float:
        g = 10 ** (s.gain_db / 20) / max(1.0, distance / 1.5)
        return float(g * (0.5 if s.muffled else 1.0))

    def inject(self, s: AudioSource) -> None:
        """Add a source that starts now (operator / compare view). Times are relative to now."""
        now = self.elapsed()
        update = {"start_s": now + s.start_s, "stop_s": None if s.stop_s is None else now + s.stop_s}
        if s.plays is not None:
            update["plays"] = [p.model_copy(update={"at_s": now + p.at_s}) for p in s.plays]
        s = s.model_copy(update=update)
        self.sources = [x for x in self.sources if x.id != s.id] + [s]

    # ----- ground truth for speakers / radar -----
    def states(self, pose: Pose) -> list[AudioSourceState]:
        t = self.elapsed()
        out = []
        for s in self.sources:
            bearing, dist = relative(pose, s.position)
            playing = self._active(s, t)
            play = self._current_play(s, t) if s.plays is not None else None
            out.append(AudioSourceState(
                id=s.id, kind=s.kind, clip_url=play[3] if play else s.clip_url, bearing_deg=round(bearing, 1),
                distance_m=round(dist, 2), gain=round(self.gain(s, dist) if playing else 0.0, 3),
                muffled=s.muffled, playing=playing, once=s.plays is not None,
                play_index=play[0] if play else -1))
        return out

    # ----- the robot's ears -----
    def hear(self, pose: Pose) -> list[Estimate]:
        """Mic-array estimates for every audible source; also updates audio-event detection."""
        t = self.elapsed()
        heard: list[Estimate] = []
        audible_now: set[str] = set()
        for s in self.sources:
            if s.plays is not None or not self._active(s, t):
                continue
            bearing, dist = relative(pose, s.position)
            g = self.gain(s, dist)
            if g < AUDIBLE_GAIN:
                continue
            audible_now.add(s.id)
            sigma = BEARING_SIGMA_DEG * (1.6 if s.muffled else 1.0) * (1.3 if dist > 10 else 1.0)
            est_b = bearing + float(self.rng.normal(0, sigma))
            if self.rng.random() < FRONT_BACK_CONFUSION:
                est_b = 180 - est_b  # classic mic-array front/back ambiguity
            est_d = dist * float(self.rng.uniform(0.7, 1.3))
            heard.append(Estimate(s, round(wrap_deg(est_b)), round(est_d, 1), bearing, dist, g))

        kinds = {x.id: x.kind for x in self.sources}
        started = audible_now - self._was_audible
        stopped = self._was_audible - audible_now
        if started:
            self._pending_event = "new sound: " + ", ".join(sorted(started))
        elif any(kinds.get(i) == "voice" for i in stopped):
            self._pending_event = "a voice went silent"
        self._was_audible = audible_now
        return heard

    def tick(self, pose: Pose) -> None:
        """Called ~4 Hz. Records each play-once utterance the robot can hear; when it ends, the
        recording (+ mic-array estimate from where the robot was) is queued for the brain."""
        t = self.elapsed()
        for s in self.sources:
            for i, start, end, url in self._windows(s):
                key = (s.id, i)
                if key in self._done_plays:
                    continue
                if start <= t < end and key not in self._open_plays:
                    self._open_plays[key] = Pose(**pose.model_dump())
                elif t >= end:
                    self._done_plays.add(key)
                    at = self._open_plays.pop(key, None)
                    if at is not None:
                        self._finish_capture(s, url, at, start)

    def _finish_capture(self, s: AudioSource, url: str, pose: Pose, at_s: float) -> None:
        bearing, dist = relative(pose, s.position)
        g = self.gain(s, dist)
        if g < AUDIBLE_GAIN:
            return  # too far away / too quiet: the robot never heard it
        sigma = BEARING_SIGMA_DEG * (1.6 if s.muffled else 1.0) * (1.3 if dist > 10 else 1.0)
        est_b = bearing + float(self.rng.normal(0, sigma))
        if self.rng.random() < FRONT_BACK_CONFUSION:
            est_b = 180 - est_b
        est_d = dist * float(self.rng.uniform(0.75, 1.25))
        clip = load_clip(url)
        if s.muffled:
            clip = audio_synth.muffle(clip)
        audio = clip * min(1.0, g * 1.5) + self.rng.normal(0, 0.003, len(clip)).astype(np.float32)
        buf = io.BytesIO()
        sf.write(buf, np.clip(audio, -1, 1), SR, format="WAV", subtype="PCM_16")
        self.captures.append(Capture(s, url, pose, round(wrap_deg(est_b)), round(est_d, 1), g,
                                     buf.getvalue(), at_s))
        self._pending_event = f"utterance finished: {s.id}"

    def take_capture(self) -> Optional[Capture]:
        return self.captures.pop(0) if self.captures else None

    def take_event(self) -> Optional[str]:
        ev, self._pending_event = self._pending_event, None
        return ev

    @staticmethod
    def describe(heard: list[Estimate]) -> str:
        """Text for the model: estimates only, no ids/kinds/ground truth."""
        parts = []
        for i, h in enumerate(sorted(heard, key=lambda e: -e.gain), 1):
            loud = "loud" if h.gain > 0.35 else "moderate" if h.gain > 0.12 else "faint"
            parts.append(f"src{i}: bearing {h.bearing_deg:+.0f}°, ~{h.distance_m:.0f} m, {loud}"
                         + (", muffled" if h.source.muffled else ""))
        return "; ".join(parts)

    def mix(self, heard: list[Estimate], seconds: float = 2.5) -> bytes:
        """Mono WAV of what the robot hears right now (sum of audible sources)."""
        n = int(seconds * SR)
        out = np.zeros(n, dtype=np.float32)
        t = self.elapsed()
        for h in heard:
            clip = load_clip(h.source.clip_url)
            if len(clip) == 0:
                continue
            start = int(max(0.0, t - h.source.start_s - seconds) * SR)
            if h.source.loop:
                idx = (np.arange(n) + start) % len(clip)
                seg = clip[idx]
            else:
                seg = np.zeros(n, dtype=np.float32)
                piece = clip[start:start + n]
                seg[:len(piece)] = piece
            if h.source.muffled:
                seg = audio_synth.muffle(seg)
            out += seg * min(1.0, h.gain * 1.5)
        peak = float(np.max(np.abs(out))) or 1.0
        if peak > 0.95:
            out *= 0.95 / peak
        out += self.rng.normal(0, 0.003, n).astype(np.float32)  # room noise floor
        buf = io.BytesIO()
        sf.write(buf, out, SR, format="WAV", subtype="PCM_16")
        return buf.getvalue()

    # ----- reveals -----
    def due_reveals(self, pose: Pose) -> list[AudioSource]:
        t = self.elapsed()
        due = []
        for s in self.sources:
            if s.reveal is None or s.id in self.revealed or s.start_s > t:
                continue
            bearing, dist = relative(pose, s.position)
            if dist <= s.reveal.radius_m and abs(bearing) <= REVEAL_FACING_DEG:
                self.revealed.add(s.id)
                due.append(s)
        return due
