# RescueSim Shared Contract

Source of truth for frontend <-> backend messages. Keep in sync with BUILD_PROMPTS.md.

```
PROJECT: RescueSim. Autonomous disaster-rescue agent (vision + hearing) in a Reactor
world model.

REPO LAYOUT
  /backend   Python 3.11, FastAPI, uvicorn, google-genai SDK, numpy, soundfile
  /frontend  Next.js (App Router, TypeScript, Tailwind)
  /shared    contract.md (this file)
  /backend/static/audio   sound clips (TTS voices + CC0 effects)

ENV VARS
  GEMINI_API_KEY        (backend only)
  REACTOR_API_KEY       (frontend, via Next.js server route; never ship to client bundle)
  NEXT_PUBLIC_BACKEND_WS=ws://localhost:8000/ws

MODELS
  Agent perception/planning: gemini-robotics-er-2-streaming-preview (loop; image + audio in)
                             gemini-robotics-er-2-preview (imagination scoring, judge)
  Scenario text / judge:     latest Gemini Flash model (check AI Studio for ID)
  Survivor voices:           Gemini TTS model (check AI Studio for ID)
  Voice guide:               latest Gemini Live native-audio model (check AI Studio for ID)

COORDINATES
  Image points: [y, x] normalized 0–1000 (Gemini Robotics convention).
  Map: meters, x/y on the floor plane, origin = episode start, heading_deg 0 = initial
  facing direction, positive = turning right (clockwise).
  Bearing (relative to robot): degrees, 0 = straight ahead, +90 = right, -90 = left,
  ±180 = behind.

AGENTS (who makes the decisions)
  "cloud"    = Gemini ER 2 + lessons playbook (+ imagination if enabled, + hearing if enabled)
  "onboard"  = our distilled student model trained on MANY generated worlds (runs locally)
  "baseline" = same student architecture trained on ONE fixed scenario, vision only,
               reactive only, no imagination, no lessons ("conventional sim training")
  All agents pass through the same safety layer.

SCENARIO (GET /scenarios returns these)
  {id, title, description, world_prompt, reference_image_url, held_out:boolean,
   trap?:{description, cue, trigger:{near:[x,y], radius_m}, world_prompt, caption},
   audio_sources:[{
     id, kind:"voice"|"tapping"|"gas_hiss"|"creak"|"water"|"alarm"|"fire"|"tv_radio",
     position:[x,y], clip_url, loop:boolean, start_s:number, stop_s?:number,
     gain_db:number, muffled:boolean,           // behind wall / under rubble -> low-pass
     transcript?:string,                        // for voices (ground truth, NOT sent to model)
     is_hazard:boolean, severity?:1|2|3, is_decoy:boolean,  // decoy = TV/radio/echo
     urgency?:1|2|3,                            // for triage scoring
     reveal?:{radius_m, world_prompt, caption}  // what appears when the agent arrives
   }]}

WEBSOCKET  ws://localhost:8000/ws   (JSON messages, all have "type")

Frontend -> Backend
  {type:"start_episode", scenario_id:string, mode:"autopilot"|"survivor"|"collect",
     agent:"cloud"|"onboard"|"baseline", imagination:boolean, hearing:boolean,
     pair_id?:string}
  {type:"set_agent", episode_id, agent}           // e.g. switch to onboard mid-run
  {type:"network_sim", offline:boolean}           // simulate losing the cloud brain
  {type:"frame", episode_id:string, ts:number, jpeg_b64:string}
  {type:"imagine_results", episode_id, request_id:string,
     options:[{id:string, label:string, frames_b64:string[]}]}
  {type:"end_episode", episode_id, outcome:"escaped"|"rescued"|"failed"|"timeout"}

Backend -> Frontend
  {type:"episode_started", episode_id, scenario:<SCENARIO>}
  {type:"decision", episode_id, ts,
     action:{move:"W"|"A"|"S"|"D"|"none", look:"left"|"right"|"up"|"down"|"none", duration_ms:number},
     survivors:[{point:[y,x], label:string}],
     hazards:[{point:[y,x], label:string, severity:1|2|3}],
     heard:[{source_id?:string,                // filled by engine for HUD; model never sees ids
             bearing_deg:number, distance_m:number,
             label:string,                     // model's interpretation: "muffled voice calling for help"
             is_hazard:boolean, is_decoy_suspected:boolean, urgency:1|2|3}],
     priority:string,                          // current goal: "reach caller at -120°", "avoid gas"
     exit_seen:boolean,
     pose:{x:number, y:number, heading_deg:number},
     reason:string,                    // one short sentence, shown on HUD
     safety_override:string|null,      // set if the safety layer changed the action
     source:"cloud"|"onboard"|"baseline",
     latency_ms:number}
  {type:"audio_state", episode_id, ts,         // ~4 Hz, drives speakers + radar
     pose:{x,y,heading_deg},
     sources:[{id, kind, clip_url, bearing_deg, distance_m, gain:number(0-1), muffled:boolean, playing:boolean}]}
  {type:"imagine_request", episode_id, request_id,
     options:[{id, label, world_prompt:string, drive:{move,look,duration_ms}[]}]}
  {type:"imagine_verdict", episode_id, request_id,
     scores:[{id, risk:0-10, progress:0-10, summary:string}], chosen_id:string, reason:string}
  {type:"director_event", episode_id, kind:"director"|"trap"|"reveal",
     world_prompt:string, clause?:string,       // clause = sentence to append to the base prompt
     caption:string, source_id?:string}
  {type:"episode_summary", episode_id, score:number, outcome, lessons:string[]}
  {type:"error", message:string}               // invalid message / unknown episode

HTTP
  GET  /scenarios                -> [<SCENARIO>]
  POST /scenarios/generate       {seed} -> <SCENARIO>
  GET  /episodes                 -> [{episode_id, scenario_id, agent, score, outcome, lessons_count}]
  POST /live/token               -> {token, model, expires_at}   // Gemini Live ephemeral token
  POST /director/trigger         {episode_ids:string[], event?:string}  // same event to all
  POST /audio/trigger            {episode_ids:string[], source:<audio source>,
                                  bearing_deg?, distance_m?}  // inject now; optional placement relative to robot
  GET  /models                   -> [{name, trained_on_scenarios, n_frames, created_at}]
  GET  /experiments/results      -> ablation table + chart data (see P13)
  GET  /health
```
