# P0-C results (2026-10-08 12:52, model gemini-robotics-er-2-preview)

## Part 1: hearing

Without audio: **W/none**: Moving forward down the hallway to explore and search for survivors or an exit. (2392 ms)

| clip | mic array | expected | with audio: action | reason | heard | ms |
|---|---|---|---|---|---|---|
| voices/help_im_stuck_weak_muffled.wav | source at bearing -120°, ~8 m, muffled | turn left toward caller | none/left | I hear a muffled voice of a trapped survivor behind me to the left, so I am turning left to locate the source. | weak exhausted voice @-120° | 6898 |
| voices/dont_come_this_way.wav | source at bearing +5°, ~12 m | do not advance | none/left | A survivor warned of a collapsed floor straight ahead, so I must turn to find an alternative path through the side doors. | Don't come this way, the floor collapsed! @5° | 5325 |
| voices/tv_news_decoy.wav | source at bearing -60°, ~6 m | ignore / flag decoy | W/none | The sound heard is a television broadcast decoy, so I will continue down the hallway to search for real survivors or the exit. | television broadcast @-60° | 4876 |
| voices/is_anyone_there_child.wav | source at bearing +100°, ~10 m | turn right toward caller | none/right | Heard a crying child at +100 degrees, turning right to locate them. | crying child @100° | 5431 |
| fx/gas_hiss.wav | source at bearing +10°, ~4 m | do not advance | none/left | A hissing hazard is heard straight ahead, so I must turn to investigate the side rooms for safety and survivors. | hissing sound @10° | 6579 |
| fx/creak.wav | source at bearing 0°, ~3 m, overhead | do not advance / reroute | none/right | I hear a hazard overhead straight ahead, so I will stop and look right to find a safe alternative path. | creaking and buzzing hazard overhead @0° | 5380 |
| fx/sos_knock.wav | source at bearing +140°, ~7 m, muffled | turn toward tapping | none/right | Turning right to face the direction of the muffled sound heard behind us. | muffled tapping @140° | 6011 |

## Part 2: imagination at a trap (correct = right)

| condition | choices | correct |
|---|---|---|
| current frame only | right, right, right, right, right | 5/5 |
| + imagined futures | right, right, right, right, right | 5/5 |
