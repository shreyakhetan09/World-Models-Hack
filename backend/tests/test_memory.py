import time

from app.audio_engine import AudioScene
from app.imagination import candidate_maneuvers
from app.models import AudioSource, Play, Pose
from app.sound_memory import SoundMemory, _point, _triangulate, Observation

VOICE = "/static/audio/voices/help_im_stuck_weak.wav"


def test_utterance_is_captured_once_after_it_ends():
    scene = AudioScene([AudioSource(id="v", kind="voice", position=(-3.0, 3.0), clip_url=VOICE,
                                    plays=[Play(at_s=0.0)])], seed=3)
    scene.started_at = time.time() - 0.5          # utterance in progress
    scene.tick(Pose())
    assert scene.take_capture() is None           # not finished yet
    assert scene.hear(Pose()) == []               # play-once sounds are never "continuous"
    scene.started_at = time.time() - 30           # long over
    scene.tick(Pose())
    cap = scene.take_capture()
    assert cap is not None and cap.wav[:4] == b"RIFF"
    assert -90 < cap.bearing_deg < 0              # it came from the front-left (noisy estimate)
    scene.tick(Pose())
    assert scene.take_capture() is None           # only once


def test_unheard_if_robot_too_far_during_utterance():
    scene = AudioScene([AudioSource(id="v", kind="voice", position=(0.0, 300.0), clip_url=VOICE,
                                    plays=[Play(at_s=0.0)])])
    scene.started_at = time.time() - 0.5
    scene.tick(Pose())
    scene.started_at = time.time() - 30
    scene.tick(Pose())
    assert scene.take_capture() is None


def test_triangulation_recovers_position():
    target = (-4.0, 6.0)
    obs = []
    for origin in [(0.0, 0.0), (0.0, 3.0)]:
        import math
        dx, dy = target[0] - origin[0], target[1] - origin[1]
        obs.append(Observation(origin, math.degrees(math.atan2(dx, dy)), math.hypot(dx, dy) * 1.3, 0))
    p = _triangulate(*obs)
    assert p is not None and abs(p[0] - target[0]) < 0.1 and abs(p[1] - target[1]) < 0.1
    assert _point(obs[0]) != p  # single-ray estimate is off because distance was 30% too long


def test_memory_merges_two_hearings_and_targets_humans_not_dogs():
    m = SoundMemory()
    m.add(Pose(), -45, 5, "human_distress", "weak voice calling for help", 3, 0)
    m.add(Pose(x=0, y=2), -60, 4, "human_distress", "voice: 'I'm in here'", 3, 10)
    m.add(Pose(), 30, 10, "dog_or_animal", "dog barking", 1, 5)
    assert len(m.items) == 2
    t = m.target(Pose())
    assert t.sound_type == "human_distress" and len(t.observations) == 2
    b, d = t.relative_to(Pose())
    assert b < 0 and 2 < d < 8
    # reaching it marks it done
    assert m.target(Pose(x=t.position[0], y=t.position[1])) is None


def test_maneuvers_put_the_voice_side_first():
    mans = candidate_maneuvers(-50)
    assert mans[0].id == "turn_left" and mans[0].drive[0].look == "left"
    assert {m.id for m in mans} == {"turn_left", "forward", "turn_right"}
