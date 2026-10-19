# Phase 0 results (2026-10-08)

Raw tables: [P0A_er2_raw.md](P0A_er2_raw.md), [P0C_audio_trap_raw.md](P0C_audio_trap_raw.md). Reproduce with the commands in the README.

## P0-A: Gemini Robotics ER 2 on the 3 reference scenes

| Scene | Standard endpoint | Decision |
|---|---|---|
| Earthquake office | 3.2 s | Forward, toward the visible exit sign ✅ (but 0 hazards marked despite debris and wires ⚠️) |
| Flooded street | 3.3 s | Strafe left, away from sparking wires ✅ |
| Warehouse fire | 3.2 s | Turn left toward the exit door, away from the fire ✅ |

- **Use the standard endpoint** (`gemini-robotics-er-2-preview`) with an enforced JSON schema. The streaming endpoint is about 0.5 s faster, but with the frame sent as realtime video it misread scenes: it walked forward into the warehouse fire and called the street a corridor. It also returns its text in `output_transcription`, not `text`.
- **Latency is 2–3 s per decision with no audio.** The autopilot must decide every N frames and keep the previous move running in between (P3/P15).
- **Hazard recall is low on cluttered scenes.** Fix with example frames in the prompt and more emphasis on hazards (P3), then measure with the test set (P4.5).
- Gemini's schema format rejects integer enums (`Literal[1,2,3]`), so use `int` and clamp the value after parsing.

## P0-C: does hearing change the decision?

Same calm-corridor frame. Without audio, the agent moves **forward**. With audio, it got **7/7 right**:

| Sound (simulated direction) | Decision |
|---|---|
| Muffled "help" at −120° | Turn left toward the caller ✅ |
| "Don't come this way, the floor collapsed!" ahead | Don't advance; look for a side route ✅ |
| TV news voice at −60° | Flagged as a decoy and kept searching ✅ |
| Crying child at +100° | Turn right toward the child ✅ |
| Gas hiss ahead | Don't advance ✅ |
| Creaking overhead | Stop and look for another path ✅ |
| Muffled SOS knocking at +140° | Turn toward it ✅ |

- **Hearing works and is our clearest difference from a normal agent.** Lead the demo with it.
- **Audio raises latency to 5–7 s.** Only send audio when a sound is detected (P16). The fixed safety rules for gas, creaking and warnings must react instantly, without a model call.

## P0-C: does imagination change the choice at a trap?

The trap was smoke under the left door, with a clear stairwell on the right. **5/5 correct with or without imagined futures**: the smoke is visible, so ER 2 avoids it from the current frame alone. For imagination to make a difference, the traps need subtler cues (P9), for example a closed door with nothing visible and danger only behind it. Until a subtler trap shows a difference, don't lead the pitch with imagination.

## P0-B: Reactor (Lingbot-World-2)

- Status went connecting → waiting → **ready in about 3.6 s**, with the **first frame at about 9.6 s** (1664×960). Frame capture from the `<video>` works (no CORS or taint problems), moves sent from code steer the world, and Stop ends billing.
- **Token gotcha:** a session can only be operated by the token that created it. The JWT resolver must reuse one cached token, not mint a new one per request. Fixed in `frontend/lib/world.ts`.
- **Scene drift:** over about 20 s, the earthquake corridor drifted toward a clean, blue-lit hallway. Next step: re-assert the scenario with a prompt change every so often, or trigger a memory reset (`triggerKvCacheReset`).

## Quotas

Asset generation first hit the free tier's limit of **3 TTS requests/min**, and `with_quota_retry` waited it out. The project is now on **Tier 3** (confirmed with a burst of 5 TTS calls in 12 s). Its limits are ER 2 at 20K RPM, TTS at 1K RPM and images at 5K RPM, so quota isn't a constraint for the agent loop or data collection.

## P3 follow-up: live runs in Reactor

- **Thinking off** (`thinking_budget=0`) cut the median from 4.1 s to **1.8 s**, with the same decisions and hazards. In the live loop the median is **2.2 s**.
- **Drift:** layered prompts from Reactor's prompt guide (`frontend/lib/prompts.ts`) keep the robot's chassis and treads in frame and the scene more stable, but over about a minute the world still drifts. That's a limit of the model, not of our prompts, so keep demo runs short (under about 60 s per scenario) or restart the session.
- **World events:** the agent now gets an "ALERT" line in its context for 20 s after a disaster event, and it treats dense dust or smoke that hides the floor as a severity-2 hazard. Before this change, it drove straight into the dust cloud from an aftershock.
- **Forward moves are capped at 1.5 s.** At 2.5 s the robot acted on stale frames and walked into a wall.

## P16/P17: hearing, first live runs

- **Static world:** injected a muffled cry behind-left. The agent turned toward it within about 2 s, corrected its course as the estimates updated, and **located the survivor by sound at 33 s**.
- **Reactor world:** **located the scenario's trapped caller by sound at 61 s**, steering around a chair and hanging wires on the way.
- **Without a pursuit controller, the exit wins.** On the first try the agent turned toward the voice, then saw an open corridor with an exit and drove past the caller. Fix: the model decides *what* to pursue, and a small controller (`steer_toward`) keeps the heading on the tracked survivor sound whenever the model says "forward" but the sound is more than 25° off to the side. It never overrides the model's own turns, and the safety layer still runs after it.
- **Audio only when needed:** a clip goes to ER 2 on a sound event (a new sound, or a voice going silent) or every 4th decision. In between, the agent gets text with each identified sound's current mic-array estimate.
- **Stall risk:** one audio call hung for about 16 s. Timeouts are now 6 s for normal decisions and 9 s with audio.

## Call-and-listen scenario + imagination (office_trapped_worker)

The flow: the robot calls out "If you can hear me, call out!" → holds still and listens → the trapped worker answers **twice** (6 s, 17 s) and goes quiet; a **dog barks once** (11 s) from the other side → each finished sound is recorded **once** and classified by ER 2 → its position is **remembered on the map**, and two hearings are **triangulated** → the robot **imagines 3 routes** in forked worlds started from its current frame → ER 2 scores the imagined outcomes → the robot carries out the best one → reveal.

Static-world run (2026-10-08):

| t | event |
|---|---|
| 10 s | 1st call recorded → "human_distress", remembered at (−2.2, 4.6) |
| 15–25 s | imagined: turn left toward the voice / straight on / turn right → chose **turn left** (progress 5/10, risk 2/10) |
| 30–34 s | plan carried out in 3 steps of ~2 s |
| 38 s | dog recorded → **"dog_or_animal"**, remembered but **not pursued** |
| 41 s | 2nd call merged with the 1st → **triangulated** to (−2.9, 3.6); the true position is (−3.5, 3.5), so the error is about 0.7 m |
| 46 s | **survivor located by sound** |

Findings and fixes:
- **ER 2 classifies a brief recording correctly**: dog 3/3 (with a real recording; my synthesized bark was heard as an "alarm"), distress voices, TV, tapping.
- **TTS bug:** a prose style prefix ("Say this as a weak…: …") was **spoken aloud** in every voice clip. Fixed by using bracket audio tags (`[weak, exhausted] Help!`), retrying until a transcription contains only the line, and trimming silence. All clips were regenerated and checked.
- A field-name clash in the event log silently dropped the only recordings, so recordings now go back in the queue if a model call fails. `tests/test_live_flow.py` covers listen → record → remember → imagine.
- Plan steps wait for their move to finish (`busy_until`). The "turn toward the voice" maneuver turns by the remembered bearing, not a fixed 90°.

**Reactor run (real imagination forks), 2026-10-08:** at 10 s it heard "Help, I'm stuck under here" and remembered it at −50°, about 6 m. It then started 3 real Reactor forks from its current frame. ER 2 judged the imagined outcomes: **turn left = progress 9/10, risk 1/10** ("enters the room where the voice originated"); straight on = 3/10 ("a different, empty office further down the hallway"); turn right = 1/10. It carried out the left turn and **located the worker at 78 s**.
- **Imagination took 55 s with real forks** because Reactor was short on capacity (some sessions returned `429 no available capacity` before starting). The app now retries for up to about 1 minute. For the demo, start the scenario a little early, or pre-record a backup.
- Fork tiles keep the captured frames after each fork session ends; before this fix they went black.
