"""AGENT_MODE=live: Gemini Robotics ER 2 + mission memory + safety layer."""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import time

from .er2 import DecisionOut, decide_sync
from .models import Action, Decision, Hazard, Heard, PointLabel
from .safety import AudioHazard, hazard_ahead, timeout_action
from .state import Episode

log = logging.getLogger("rescuesim.autopilot")

# Typical: ~2 s without audio, 5-7 s with audio. A hung call freezes the robot until timeout.
MODEL_TIMEOUT_S = float(os.getenv("MODEL_TIMEOUT_S", "6"))
AUDIO_TIMEOUT_S = float(os.getenv("AUDIO_TIMEOUT_S", "9"))
# ER 2 takes ~2-3 s per decision; stretch safe forward moves to cover that gap so motion doesn't stall.
MAX_FORWARD_MS = int(os.getenv("MAX_FORWARD_MS", "1500"))
EVENT_ALERT_S = 20  # how long a world event stays in the agent's context
# Audio adds ~3-4 s per call, so only attach it on audio events or every Nth decision while audible.
AUDIO_EVERY_N = int(os.getenv("AUDIO_EVERY_N", "4"))
HAZARD_SOUNDS = {"gas_hiss": "gas hiss", "creak": "structural creaking", "fire": "fire crackling",
                 "water": "rushing water"}


def audio_hazards(heard) -> list[AudioHazard]:
    """Deterministic 'onboard sound classifier' for the safety layer. In this sim the class comes
    from the source kind; on a real robot it would be a small audio classifier (e.g. YAMNet)."""
    out = []
    for h in heard:
        s = h.source
        if s.kind in HAZARD_SOUNDS:
            out.append(AudioHazard(HAZARD_SOUNDS[s.kind], h.bearing_deg, h.distance_m))
        elif s.kind == "voice" and s.is_hazard:  # spoken warning, e.g. "don't come this way"
            out.append(AudioHazard("spoken warning", h.bearing_deg, h.distance_m, is_warning=True))
    return out


def _angle(a: float, b: float) -> float:
    return abs(((a - b) + 180) % 360 - 180)


def remember_heard(ep: Episode, heard_est, model_heard) -> None:
    """Associate each sound the model identified with the nearest-bearing source the engine tracks."""
    for mh in model_heard:
        if not heard_est:
            break
        best = min(heard_est, key=lambda e: _angle(e.bearing_deg, mh.bearing_deg))
        if _angle(best.bearing_deg, mh.bearing_deg) <= 45:
            ep.heard_labels[best.source.id] = (mh.label, mh.is_hazard, mh.is_decoy_suspected, mh.urgency)


def tracked_heard(ep: Episode, heard_est) -> list[Heard]:
    out = []
    for e in heard_est:
        if e.source.id in ep.heard_labels:
            label, hz, decoy, urg = ep.heard_labels[e.source.id]
            out.append(Heard(source_id=e.source.id, bearing_deg=e.bearing_deg, distance_m=e.distance_m,
                             label=label, is_hazard=hz, is_decoy_suspected=decoy, urgency=urg))
    return out


PURSUIT_CONE_DEG = 25
FINAL_APPROACH_M = 4.0
TURN_DPS = float(os.getenv("TURN_DPS", "60"))


def pursuit_target(tracked: list[Heard]) -> Heard | None:
    """The survivor sound to go to: highest urgency, then nearest. Hazards and decoys are skipped."""
    candidates = [h for h in tracked if not h.is_hazard and not h.is_decoy_suspected]
    return max(candidates, key=lambda h: (h.urgency, -h.distance_m), default=None)


def steer_toward(action: Action, target: Heard | None) -> tuple[Action, str | None]:
    """Low-level controller: the model chose WHAT to pursue; this keeps the heading on it.
    Only replaces a forward move that would leave the target off to the side."""
    if target is None or action.move != "W" or abs(target.bearing_deg) <= PURSUIT_CONE_DEG:
        return action, None
    turn_ms = int(min(1500, max(300, abs(target.bearing_deg) / TURN_DPS * 1000)))
    side = "left" if target.bearing_deg < 0 else "right"
    return (Action(look=side, duration_ms=turn_ms),
            f"turning {side} toward {target.label} ({target.bearing_deg:+.0f}°, ~{target.distance_m:.0f} m)")


def build_context(ep: Episode, tracked: list[Heard] | None = None) -> str:
    lines = [
        f"Scenario: {ep.scenario.title}. {ep.scenario.description}",
        f"Steps taken: {ep.steps}. Estimated pose: x={ep.pose.x:.1f} m, y={ep.pose.y:.1f} m, "
        f"heading {ep.pose.heading_deg:.0f}°.",
        f"Survivors found so far: {', '.join(ep.survivors_found) or 'none'}.",
    ]
    now = time.time()
    fresh = [clause for t, clause in ep.events if now - t < EVENT_ALERT_S]
    if fresh:
        lines.append("ALERT, this just happened in the world: " + " ".join(fresh)
                     + " Re-check the path: slow down, use short moves, and scan before advancing.")
    if tracked:
        lines.append("Sounds you identified earlier, at their current mic-array estimates "
                     "(no new audio this step): " + "; ".join(
                         f"{h.label} at bearing {h.bearing_deg:+.0f}°, ~{h.distance_m:.0f} m"
                         + (" (hazard)" if h.is_hazard else "") + (" (likely decoy)" if h.is_decoy_suspected else "")
                         for h in tracked))
    if ep.recent:
        lines.append("Your last decisions (oldest first) — avoid repeating moves that made no progress:")
        lines += [f"  - {r}" for r in ep.recent]
    if ep.playbook:
        lines.append("Lessons from earlier missions:")
        lines += [f"  - {lesson}" for lesson in ep.playbook]
    return "\n".join(lines)


def to_contract(out: DecisionOut) -> tuple[Action, list[PointLabel], list[Hazard], list[Heard]]:
    def pt(p: list[int]) -> tuple[int, int]:
        y, x = (list(p) + [500, 500])[:2]
        return (min(1000, max(0, int(y))), min(1000, max(0, int(x))))

    action = Action(move=out.action.move, look=out.action.look,
                    duration_ms=min(1500, max(300, out.action.duration_ms)))
    survivors = [PointLabel(point=pt(s.point), label=s.label) for s in out.survivors]
    hazards = [Hazard(point=pt(h.point), label=h.label, severity=h.severity) for h in out.hazards]
    heard = [Heard(bearing_deg=h.bearing_deg, distance_m=h.distance_m, label=h.label,
                   is_hazard=h.is_hazard, is_decoy_suspected=h.is_decoy_suspected, urgency=h.urgency)
             for h in out.heard]
    return action, survivors, hazards, heard


LISTEN_S = float(os.getenv("LISTEN_S", "14"))  # after the call-out, hold still this long listening


def _decision(ep: Episode, action: Action, reason: str, t0: float, **kw) -> Decision:
    return Decision(episode_id=ep.id, ts=time.time(), action=action, pose=ep.pose, reason=reason,
                    source="cloud", latency_ms=(time.perf_counter() - t0) * 1000,
                    heard=ep.memory.as_heard(ep.pose) if ep.hearing else [], **kw)


def capture_mic_text(ep: Episode, cap) -> tuple[str, float, float]:
    """Mic-array description of a finished utterance, re-expressed relative to the CURRENT pose."""
    from .audio_engine import clip_seconds, relative

    b, d = relative(ep.pose, cap.estimated_position())
    loud = "loud" if cap.gain > 0.35 else "moderate" if cap.gain > 0.12 else "faint"
    text = (f"RECORDING of a sound that has just ended ({clip_seconds(cap.clip_url):.1f} s); it may not repeat. "
            f"Mic-array estimate: bearing {b:+.0f}° from your current heading, ~{d:.0f} m, {loud}"
            + (", muffled" if cap.source.muffled else "") + ".")
    return text, b, d


async def live_decision(ep: Episode, jpeg_b64: str) -> Decision:
    jpeg = base64.b64decode(jpeg_b64)
    ep.last_jpeg = jpeg
    t0 = time.perf_counter()

    # 1) Executing a plan chosen by imagination: no model call, safety still applies.
    if ep.plan:
        step = ep.plan.pop(0)
        action, override = ep.safety.check(step, [], heading_deg=ep.pose.heading_deg)
        n = ep.plan_total - len(ep.plan)
        ep.busy_until = time.time() + action.duration_ms / 1000
        ep.apply(action)
        target = ep.memory.target(ep.pose)
        return _decision(ep, action, f"Executing imagined plan '{ep.plan_label}' (step {n}/{ep.plan_total}).",
                         t0, safety_override=override,
                         priority=f"reach {target.label}" if target else "explore")

    capture = None  # finished utterances are classified by classify_capture() as soon as they end
    heard = ep.audio.hear(ep.pose) if ep.audio else []  # continuous sources (hiss, creak, water...)

    # 2) Call-and-listen: right after the call-out, hold still until something answers.
    still_processing = ep.classifying or bool(ep.audio and ep.audio.captures)
    if (ep.hearing and not ep.memory.items
            and (time.time() - ep.started_at < LISTEN_S or still_processing)):
        action = Action(move="none", duration_ms=600)
        ep.apply(action)
        return _decision(ep, action, "Called out to survivors; holding still and listening for a response.",
                         t0, priority="listen")

    # 3) Model inputs: a finished utterance (sent once), or continuous sound every Nth step.
    audio_wav = mic_text = None
    cap_b = cap_d = 0.0
    if capture is not None:
        audio_wav = capture.wav
        mic_text, cap_b, cap_d = capture_mic_text(ep, capture)
        ep.record("audio_sent", audio="utterance", mic=mic_text)
    elif ep.hearing and heard:
        event = ep.audio.take_event()
        ep.decisions_since_audio += 1
        if event or ep.decisions_since_audio >= AUDIO_EVERY_N:
            ep.decisions_since_audio = 0
            audio_wav = ep.audio.mix(heard)
            mic_text = ep.audio.describe(heard)
            ep.record("audio_sent", audio="continuous", event=event, mic=mic_text)
    elif ep.audio:
        ep.audio.take_event()

    context = build_context(ep, None if audio_wav else (tracked_heard(ep, heard) if ep.hearing else None))
    if ep.hearing:
        mem = ep.memory.context(ep.pose, time.time())
        if mem:
            context += "\n" + mem
    try:
        out, _ = await asyncio.wait_for(
            asyncio.to_thread(decide_sync, jpeg, context, audio_wav, mic_text),
            timeout=AUDIO_TIMEOUT_S if audio_wav else MODEL_TIMEOUT_S)
    except Exception as e:
        log.warning("ER 2 call failed for %s: %s %s", ep.id, type(e).__name__, str(e)[:200])
        if capture is not None:
            ep.audio.captures.insert(0, capture)  # don't lose the only recording; retry next step
        action, reason = timeout_action()
        ep.apply(action)
        return _decision(ep, action, reason, t0)
    latency_ms = (time.perf_counter() - t0) * 1000

    action, survivors, hazards, model_heard = to_contract(out)

    # 4) Remember where the utterance came from (geometry from the mic array, meaning from ER 2).
    if capture is not None:
        typed = [(h, o) for h, o in zip(model_heard, out.heard)]
        if typed:
            h, o = min(typed, key=lambda ho: _angle(ho[0].bearing_deg, cap_b))
            r = ep.memory.add(capture.pose, capture.bearing_deg, capture.distance_m, o.sound_type,
                              h.label, h.urgency, time.time())
            ep.record("sound_remembered", type=o.sound_type, label=h.label, position=r.position,
                      observations=len(r.observations))
            log.info("remembered %s (%s) at %s from %d obs", h.label, o.sound_type,
                     tuple(round(v, 1) for v in r.position), len(r.observations))

    target = ep.memory.target(ep.pose) if ep.hearing else None

    # 5) First time we know where a survivor is: imagine the routes before committing.
    if target is not None and ep.imagination and id(target) not in ep.imagined_targets and ep.allow_imagine:
        from .imagination import build_request

        b, d = target.relative_to(ep.pose)
        req, pending = build_request(ep.id, target, b, d)
        ep.imagined_targets.add(id(target))
        ep.pending_imagination = pending
        ep.imagining = True
        ep.outbox.append(req)
        ep.record("imagine_request", options=[o.label for o in req.options])
        action = Action(move="none", duration_ms=600)
        ep.apply(action)
        return _decision(ep, action, f"Located {target.label} by sound (bearing {b:+.0f}°, ~{d:.0f} m). "
                         "Imagining possible routes before moving.", t0, hazards=hazards,
                         priority=f"reach {target.label}")

    # 6) Steer toward the remembered survivor position (or a live continuous sound).
    heard_out = (ep.memory.as_heard(ep.pose) + tracked_heard(ep, heard)) if ep.hearing else []
    goal = None
    if target is not None:
        b, d = target.relative_to(ep.pose)
        goal = Heard(bearing_deg=b, distance_m=d, label=target.label, urgency=min(3, max(1, target.urgency)))
    elif ep.hearing:
        goal = pursuit_target(tracked_heard(ep, heard))
    action, steering = steer_toward(action, goal)
    if target is not None and goal is not None and goal.distance_m <= FINAL_APPROACH_M:
        # Final approach: steer straight in on the located survivor (safety layer still applies).
        if abs(goal.bearing_deg) <= PURSUIT_CONE_DEG:
            action, steering = Action(move="W", duration_ms=1200), f"final approach to {goal.label} (~{goal.distance_m:.0f} m)"
        else:
            action, steering = steer_toward(Action(move="W", duration_ms=1200), goal)
    reason = out.reason + (f" Steering: {steering}." if steering else "")
    priority = (f"reach {goal.label} ({goal.bearing_deg:+.0f}°, ~{goal.distance_m:.0f} m)" if goal else out.priority)
    action, override = ep.safety.check(action, hazards,
                                       audio=audio_hazards(heard) if ep.hearing else None,
                                       heading_deg=ep.pose.heading_deg)
    alert = any(time.time() - t < EVENT_ALERT_S for t, _ in ep.events)
    if (override is None and not alert and action.move == "W" and action.look == "none"
            and hazard_ahead(hazards, min_severity=2) is None):
        action.duration_ms = min(MAX_FORWARD_MS, max(action.duration_ms, int(latency_ms * 0.9)))

    for s_ in survivors:
        if s_.label not in ep.survivors_found:
            ep.survivors_found.append(s_.label)
    ep.recent.append(f"{action.move}/{action.look} {action.duration_ms}ms: {reason}"
                     + (f" [SAFETY OVERRIDE: {override}]" if override else ""))
    ep.apply(action)

    return Decision(
        episode_id=ep.id, ts=time.time(), action=action, survivors=survivors, hazards=hazards,
        heard=heard_out, priority=priority, exit_seen=out.exit_seen, pose=ep.pose,
        reason=reason, safety_override=override, source="cloud", latency_ms=latency_ms,
    )


_BLANK_JPEG: bytes | None = None


def _blank_jpeg() -> bytes:
    global _BLANK_JPEG
    if _BLANK_JPEG is None:
        import io

        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (64, 36), (40, 40, 40)).save(buf, "JPEG")
        _BLANK_JPEG = buf.getvalue()
    return _BLANK_JPEG


TYPE_WORDS = {"human_distress": "a person calling for help", "child": "a child", "dog_or_animal": "an animal",
              "tapping": "tapping", "human_speech_warning": "a spoken warning", "tv_or_radio": "a TV or radio",
              "gas_hiss": "gas hissing", "structural_creak": "the structure creaking"}


def classify_capture(ep: Episode, cap):
    """Blocking: ER 2 classifies one finished utterance; it is remembered on the map.
    Returns a SoundEvent (or None if ER 2 heard nothing usable)."""
    from .models import SoundEvent

    mic_text, b, d = capture_mic_text(ep, cap)
    context = build_context(ep) + "\nThis step is ONLY about the recording: classify it and say where it came from."
    out, _ = decide_sync(ep.last_jpeg or _blank_jpeg(), context, cap.wav, mic_text)
    if not out.heard:
        return None
    o = min(out.heard, key=lambda h: _angle(h.bearing_deg, b))
    r = ep.memory.add(cap.pose, cap.bearing_deg, cap.distance_m, o.sound_type, o.label,
                      min(3, max(1, o.urgency)), time.time())
    ep.record("sound_remembered", type=o.sound_type, label=o.label, position=r.position,
              observations=len(r.observations))
    log.info("remembered %s (%s) at %s from %d obs", o.label, o.sound_type,
             tuple(round(v, 1) for v in r.position), len(r.observations))
    rb, rd = r.relative_to(ep.pose)
    what = TYPE_WORDS.get(o.sound_type, o.sound_type.replace("_", " "))
    if r.is_survivor and len(r.observations) >= 2:
        reason = f"Heard {what} again; triangulated them to ~{rd:.0f} m at {rb:+.0f}°."
    elif r.is_survivor:
        reason = f"Heard {what} at {rb:+.0f}°, ~{rd:.0f} m. Remembering where it came from."
    elif o.sound_type == "dog_or_animal":
        reason = f"Heard {what} at {rb:+.0f}°, ~{rd:.0f} m. Not a person; noting it for responders."
    elif o.sound_type == "tv_or_radio":
        reason = f"Heard {what} at {rb:+.0f}°. Likely a decoy; ignoring it."
    else:
        reason = f"Heard {what} at {rb:+.0f}°, ~{rd:.0f} m."
    return SoundEvent(episode_id=ep.id, ts=time.time(), label=o.label, sound_type=o.sound_type,
                      bearing_deg=round(rb), distance_m=round(rd, 1), observations=len(r.observations),
                      is_survivor=r.is_survivor, reason=reason, heard=ep.memory.as_heard(ep.pose))
