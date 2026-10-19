"""Episode history (P10): summaries + timelines computed from the episode log.

The score is a transparent rule-based rubric until the P9 judge model exists:
  +50 first survivor found, +15 each extra (max +30)
  +20 speed bonus, scaled down linearly to 0 at 120 s to the first survivor
  -3 per safety override (max -15)
Clamped to 0-100.
"""

from __future__ import annotations

from typing import Any, Optional

SCORE_RUBRIC = ("+50 first survivor, +15 each extra (max +30), up to +20 for speed to first survivor "
                "(0 at 120 s), -3 per safety override (max -15)")

TIMELINE_KINDS = {"start", "audio_sent", "sound_remembered", "imagine_request", "imagine_verdict",
                  "reveal", "director", "audio_inject", "end"}


def _first(log: list[dict], kind: str) -> Optional[dict]:
    return next((e for e in log if e.get("kind") == kind), None)


def score(survivors: int, t_first: Optional[float], overrides: int) -> int:
    s = 0.0
    if survivors:
        s += 50 + min(30, 15 * (survivors - 1))
        if t_first is not None:
            s += 20 * max(0.0, 1 - t_first / 120)
    s -= min(15, 3 * overrides)
    return int(round(max(0, min(100, s))))


def summarize(d: dict[str, Any], title: str = "") -> dict[str, Any]:
    log = d.get("log", [])
    reveals = [e for e in log if e.get("kind") == "reveal"]
    decisions = [e for e in log if e.get("kind") == "decision"]
    overrides = sum(1 for e in decisions if (e.get("decision") or {}).get("safety_override"))
    t_first = reveals[0]["t"] if reveals else None
    end = _first(log, "end")
    duration = end["t"] if end else (log[-1]["t"] if log else 0.0)
    verdict = _first(log, "imagine_verdict")
    sounds = [{"type": e.get("type"), "label": e.get("label")} for e in log if e.get("kind") == "sound_remembered"]
    outcome = "rescued" if reveals else d.get("outcome")
    return {
        "episode_id": d.get("episode_id"),
        "scenario_id": d.get("scenario_id"),
        "scenario_title": title or d.get("scenario_id"),
        "agent": d.get("agent"),
        "mode": d.get("mode"),
        "hearing": d.get("hearing"),
        "imagination": d.get("imagination"),
        "started_at": d.get("started_at"),
        "duration_s": round(duration, 1),
        "outcome": outcome,
        "score": score(len(reveals), t_first, overrides),
        "survivors_found": [e.get("caption") for e in reveals],
        "time_to_first_survivor_s": None if t_first is None else round(t_first, 1),
        "sounds_heard": sounds,
        "imagination_choice": (verdict or {}).get("chosen"),
        "safety_overrides": overrides,
        "steps": len(decisions),
        "lessons_count": 0,
    }


def timeline(d: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for e in d.get("log", []):
        k = e.get("kind")
        if k not in TIMELINE_KINDS:
            continue
        text = {
            "start": f"Started ({e.get('mode')}, {e.get('agent')})",
            "audio_sent": "Sent a sound recording to ER 2" if e.get("audio") == "utterance"
                          else "Sent live audio to ER 2",
            "sound_remembered": f"Remembered: {e.get('label')} ({e.get('type')}), "
                                f"{e.get('observations', 1)} hearing(s)",
            "imagine_request": "Imagining: " + ", ".join(e.get("options") or []),
            "imagine_verdict": e.get("reason") or f"Chose {e.get('chosen')}",
            "reveal": f"Survivor located: {e.get('caption')}",
            "director": f"Disaster event: {str(e.get('event', ''))[:80]}",
            "audio_inject": f"Operator injected a sound ({(e.get('source') or {}).get('kind')})",
            "end": f"Ended: {e.get('outcome')}",
        }[k]
        out.append({"t": e.get("t"), "kind": k, "text": text})
    return out
