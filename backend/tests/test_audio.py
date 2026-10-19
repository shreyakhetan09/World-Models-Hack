import io

import numpy as np
import soundfile as sf

from app.audio_engine import AudioScene, position_from, relative
from app.autopilot import audio_hazards
from app.models import Action, AudioSource, Pose, Reveal
from app.safety import AudioHazard, SafetyLayer


def src(**kw):
    base = dict(id="s", kind="voice", position=(0.0, 5.0), clip_url="/static/audio/voices/help_im_stuck_weak.wav")
    return AudioSource(**{**base, **kw})


def test_relative_bearing_math():
    assert relative(Pose(), (0, 5)) == (0.0, 5.0)              # straight ahead
    b, _ = relative(Pose(), (5, 0)); assert round(b) == 90       # right
    b, _ = relative(Pose(), (-5, 0)); assert round(b) == -90     # left
    b, _ = relative(Pose(heading_deg=90), (5, 0)); assert round(b) == 0  # turned right to face it
    x, y = position_from(Pose(heading_deg=90), 0, 3)
    assert (round(x), round(y)) == (3, 0)


def test_mic_array_noise_is_bounded_and_hides_ground_truth():
    scene = AudioScene([src(position=(-6.0, 0.0))], seed=1)
    errs = []
    for _ in range(300):
        (e,) = scene.hear(Pose())
        d = abs(((e.bearing_deg - e.true_bearing_deg) + 180) % 360 - 180)
        if d < 90:  # ignore front/back confusions
            errs.append(d)
    assert 5 < np.mean(errs) < 25
    text = AudioScene.describe(scene.hear(Pose()))
    assert "voice" not in text and "help" not in text and "s:" not in text


def test_far_sources_are_inaudible_and_events_fire():
    scene = AudioScene([src(position=(0.0, 200.0))])
    assert scene.hear(Pose()) == []
    scene.inject(src(id="near", position=(1.0, 2.0)))
    assert scene.hear(Pose()) and scene.take_event().startswith("new sound")
    assert scene.take_event() is None


def test_mix_is_valid_wav():
    scene = AudioScene([src(), src(id="hiss", kind="gas_hiss", clip_url="/static/audio/fx/gas_hiss.wav", muffled=True)])
    data, sr = sf.read(io.BytesIO(scene.mix(scene.hear(Pose()))))
    assert sr == 16000 and len(data) == 40000 and np.abs(data).max() <= 1.0


def test_reveal_needs_proximity_and_facing():
    scene = AudioScene([src(position=(0.0, 2.0), reveal=Reveal(radius_m=2.5, world_prompt="p", caption="c"))])
    assert scene.due_reveals(Pose(heading_deg=180)) == []   # close but facing away
    assert [s.id for s in scene.due_reveals(Pose())] == ["s"]
    assert scene.due_reveals(Pose()) == []                  # only once


def test_safety_blocks_forward_into_heard_gas():
    s = SafetyLayer()
    action, why = s.check(Action(move="W"), [], audio=[AudioHazard("gas hiss", 10, 4)])
    assert action.move == "none" and "gas hiss" in why
    assert s.check(Action(move="W"), [], audio=[AudioHazard("gas hiss", 90, 4)])[1] is None   # off to the side
    assert s.check(Action(move="W"), [], audio=[AudioHazard("gas hiss", 0, 15)])[1] is None   # far away


def test_spoken_warning_blocks_that_heading_after_turning_back():
    s = SafetyLayer()
    s.check(Action(look="left"), [], audio=[AudioHazard("spoken warning", 0, 10, is_warning=True)], heading_deg=0)
    assert s.check(Action(move="W"), [], heading_deg=90)[1] is None      # facing elsewhere: fine
    assert "warned" in s.check(Action(move="W"), [], heading_deg=5)[1]   # back toward the warning


def test_audio_hazard_classifier():
    scene = AudioScene([src(id="g", kind="gas_hiss", clip_url="/static/audio/fx/gas_hiss.wav", position=(0, 3)),
                        src(id="w", kind="voice", is_hazard=True, position=(0, 4)),
                        src(id="v", position=(0, 5))])
    labels = sorted(a.label for a in audio_hazards(scene.hear(Pose())))
    assert labels == ["gas hiss", "spoken warning"]


def test_pursuit_turns_toward_caller_instead_of_driving_past():
    from app.autopilot import pursuit_target, steer_toward
    from app.models import Heard

    caller = Heard(bearing_deg=-80, distance_m=6, label="muffled voice", urgency=3)
    tv = Heard(bearing_deg=60, distance_m=3, label="tv", is_decoy_suspected=True, urgency=3)
    gas = Heard(bearing_deg=10, distance_m=3, label="hiss", is_hazard=True, urgency=3)
    target = pursuit_target([caller, tv, gas])
    assert target is caller
    action, why = steer_toward(Action(move="W", duration_ms=800), target)
    assert action.look == "left" and action.move == "none" and why
    # roughly ahead: let the model drive; model's own turns are never replaced
    assert steer_toward(Action(move="W"), Heard(bearing_deg=10, distance_m=4, label="v"))[1] is None
    assert steer_toward(Action(look="right"), target)[1] is None
