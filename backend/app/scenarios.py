"""Preset scenarios. These are the reliable ones for the demo; generated ones come later (P9)."""

from __future__ import annotations

from .models import AudioSource, Play, Reveal, Scenario

PRESETS: list[Scenario] = [
    # Demo scenario: call-and-listen. The robot calls out, a trapped worker answers twice from the side
    # office on the left and then goes quiet; a dog barks once from the right (not the survivor).
    Scenario(
        id="office_trapped_worker",
        title="Earthquake: Trapped Worker",
        description="Office corridor after an earthquake. Someone may be trapped in one of the side "
        "offices. The corridor ahead is blocked by a collapsed ceiling with live, sparking cables. Call "
        "out, listen, locate them by sound, and reach them safely.",
        world_prompt=(
            "A dusty office corridor after an earthquake. The world contains EXACTLY ONE open office "
            "doorway on the left wall a few meters ahead at a fixed position AND EXACTLY ONE collapsed "
            "ceiling section hanging low across the middle of the corridor further ahead, with live electric "
            "cables dangling from it and throwing bright sparks, at a fixed position AND EXACTLY ONE green "
            "glowing exit sign at the far end beyond it at a fixed position. Through the doorway: a side "
            "office with desks and a toppled bookshelf. Grey dust, scattered papers. Gritty, realistic."
        ),
        reference_image_url="/static/scenarios/office_trapped_worker.jpg",
        audio_sources=[
            AudioSource(
                id="trapped_worker",
                kind="voice",
                position=(-4.0, 4.5),  # inside the side office, through the left doorway (~-42°, 6 m)
                clip_url="/static/audio/voices/help_im_stuck_weak.wav",
                # demo timing: answers right after the ~4.4 s call-out, again after the dog
                plays=[Play(at_s=5), Play(at_s=13, clip_url="/static/audio/voices/please_im_in_here.wav")],
                transcript="Help! I'm stuck under here! ... Please... I'm in here... I can't move my leg.",
                urgency=3,
                reveal=Reveal(
                    radius_m=2.5,
                    world_prompt="Inside the side office, a dust-covered office worker lies trapped under "
                    "the toppled bookshelf, raising one arm toward the camera.",
                    caption="Office worker trapped under a bookshelf",
                ),
            ),
            AudioSource(
                id="dog",
                kind="dog",
                position=(5.0, 9.0),
                clip_url="/static/audio/fx/dog_bark.wav",
                plays=[Play(at_s=9.5)],
            ),
        ],
    ),
    Scenario(
        id="earthquake_office",
        title="Earthquake: Office Floor",
        description="Third floor of an office after a strong earthquake. Dust, fallen ceiling "
        "tiles, overturned desks. A green exit sign glows at the far end of the corridor.",
        world_prompt=(
            "A dim office corridor on the third floor after a strong earthquake. The world contains "
            "EXACTLY ONE green glowing emergency exit sign at the far end of the corridor at a fixed "
            "position AND EXACTLY ONE overturned grey metal desk on the right at a fixed position AND "
            "EXACTLY ONE cracked fluorescent ceiling light overhead at a fixed position. Fallen ceiling "
            "tiles, hanging cables, scattered papers and grey dust cover the floor; cracked plaster walls. "
            "Gritty, realistic, cold flickering light."
        ),
        reference_image_url="/static/scenarios/earthquake_office.jpg",
        audio_sources=[
            AudioSource(
                id="office_caller",
                kind="voice",
                position=(-6.0, 4.0),
                clip_url="/static/audio/voices/help_im_stuck_weak.wav",
                muffled=True,
                transcript="Help! I'm stuck under here!",
                urgency=3,
                reveal=Reveal(
                    world_prompt="a person trapped under a collapsed desk, waving one arm, "
                    "covered in dust, looking at the camera",
                    caption="Survivor trapped under a desk",
                ),
            ),
            AudioSource(
                id="office_creak",
                kind="creak",
                position=(0.5, 9.0),
                clip_url="/static/audio/fx/creak.wav",
                is_hazard=True,
                severity=3,
                start_s=20,
            ),
        ],
    ),
    Scenario(
        id="flooded_street",
        title="Flood: Downtown Street",
        description="Street-level flooding after a storm. Murky water, floating debris, "
        "downed power lines. A raised pedestrian bridge leads to safety.",
        world_prompt=(
            "A downtown street flooded after a storm, knee-deep murky brown water. The world contains "
            "EXACTLY ONE leaning lamp post on the right with a sparking downed power line at a fixed "
            "position AND EXACTLY ONE half-submerged white car on the left at a fixed position AND "
            "EXACTLY ONE raised pedestrian bridge with a green exit sign far ahead at a fixed position. "
            "Floating debris, shuttered shops, heavy overcast sky. Gritty, realistic."
        ),
        reference_image_url="/static/scenarios/flooded_street.jpg",
        audio_sources=[
            AudioSource(
                id="street_water",
                kind="water",
                position=(4.0, 6.0),
                clip_url="/static/audio/fx/rushing_water.wav",
                is_hazard=True,
                severity=2,
            ),
            AudioSource(
                id="street_caller",
                kind="voice",
                position=(-8.0, 10.0),
                clip_url="/static/audio/voices/over_here_shout.wav",
                transcript="Over here! On the car roof!",
                urgency=2,
                reveal=Reveal(
                    world_prompt="a person standing on the roof of a half-submerged car, "
                    "waving both arms",
                    caption="Survivor on a car roof",
                ),
            ),
        ],
    ),
    Scenario(
        id="warehouse_fire",
        title="Fire: Warehouse",
        description="Smoke-filled warehouse with a fire spreading in the back aisles. "
        "Tall shelving, a forklift, and an exit door on the left wall.",
        world_prompt=(
            "A large warehouse filling with grey smoke. The world contains EXACTLY ONE orange fire "
            "burning in the back aisle straight ahead at a fixed position AND EXACTLY ONE yellow forklift "
            "on the right at a fixed position AND EXACTLY ONE door with a green exit sign above it on the "
            "left wall at a fixed position. Tall metal shelving aisles, stacked cardboard boxes, haze "
            "glowing orange. Gritty, realistic."
        ),
        reference_image_url="/static/scenarios/warehouse_fire.jpg",
        audio_sources=[
            AudioSource(
                id="warehouse_fire_crackle",
                kind="fire",
                position=(2.0, 14.0),
                clip_url="/static/audio/fx/fire_crackle.wav",
                is_hazard=True,
                severity=3,
            ),
            AudioSource(
                id="warehouse_gas",
                kind="gas_hiss",
                position=(3.0, 5.0),
                clip_url="/static/audio/fx/gas_hiss.wav",
                is_hazard=True,
                severity=3,
                start_s=15,
            ),
            AudioSource(
                id="warehouse_tapping",
                kind="tapping",
                position=(-5.0, 8.0),
                clip_url="/static/audio/fx/sos_knock.wav",
                muffled=True,
                urgency=3,
                reveal=Reveal(
                    world_prompt="a worker pinned behind fallen boxes, knocking on a metal "
                    "shelf with a wrench",
                    caption="Survivor found by tapping",
                ),
            ),
        ],
    ),
]


def get_scenarios() -> list[Scenario]:
    return list(PRESETS)


def get_scenario(scenario_id: str) -> Scenario | None:
    return next((s for s in PRESETS if s.id == scenario_id), None)
