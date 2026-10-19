// TypeScript mirror of shared/contract.md. Keep in sync with backend/app/models.py.

import type { AudioSourceState } from "./audioScene";

export type Move = "W" | "A" | "S" | "D" | "none";
export type Look = "left" | "right" | "up" | "down" | "none";
export type AgentName = "cloud" | "onboard" | "baseline";
export type Mode = "autopilot" | "survivor" | "collect";
export type Outcome = "escaped" | "rescued" | "failed" | "timeout";
export type Point = [number, number]; // [y, x] normalized 0-1000

export interface Action {
  move: Move;
  look: Look;
  duration_ms: number;
}

export interface Pose {
  x: number;
  y: number;
  heading_deg: number;
}

export interface AudioSource {
  id: string;
  kind: "voice" | "tapping" | "gas_hiss" | "creak" | "water" | "alarm" | "fire" | "tv_radio";
  position: [number, number];
  clip_url: string;
  loop: boolean;
  start_s: number;
  stop_s?: number | null;
  gain_db: number;
  muffled: boolean;
  transcript?: string | null;
  is_hazard: boolean;
  severity?: 1 | 2 | 3 | null;
  is_decoy: boolean;
  urgency?: 1 | 2 | 3 | null;
  reveal?: { radius_m: number; world_prompt: string; caption: string } | null;
}

export interface Scenario {
  id: string;
  title: string;
  description: string;
  world_prompt: string;
  reference_image_url: string;
  held_out: boolean;
  audio_sources: AudioSource[];
}

export interface Heard {
  source_id?: string | null;
  bearing_deg: number;
  distance_m: number;
  label: string;
  is_hazard: boolean;
  is_decoy_suspected: boolean;
  urgency: 1 | 2 | 3;
}

export interface Decision {
  type: "decision";
  episode_id: string;
  ts: number;
  action: Action;
  survivors: { point: Point; label: string }[];
  hazards: { point: Point; label: string; severity: 1 | 2 | 3 }[];
  heard: Heard[];
  priority: string;
  exit_seen: boolean;
  pose: Pose;
  reason: string;
  safety_override: string | null;
  source: AgentName;
  latency_ms: number;
}

export type ServerMessage =
  | { type: "episode_started"; episode_id: string; scenario: Scenario }
  | Decision
  | { type: "director_event"; episode_id: string; kind: "director" | "trap" | "reveal"; world_prompt: string; clause?: string; caption: string; source_id?: string | null }
  | { type: "episode_summary"; episode_id: string; score: number; outcome: Outcome; lessons: string[] }
  | { type: "audio_state"; episode_id: string; ts: number; pose: Pose; sources: AudioSourceState[] }
  | { type: "imagine_request"; episode_id: string; request_id: string; options: { id: string; label: string; world_prompt: string; drive: Action[] }[] }
  | { type: "imagine_verdict"; episode_id: string; request_id: string; scores: { id: string; risk: number; progress: number; summary: string }[]; chosen_id: string; reason: string }
  | { type: "sound_event"; episode_id: string; ts: number; label: string; sound_type: string; bearing_deg: number;
      distance_m: number; observations: number; is_survivor: boolean; reason: string; heard: Heard[] }
  | { type: "error"; message: string };

export type ClientMessage =
  | { type: "start_episode"; scenario_id: string; mode: Mode; agent: AgentName; imagination: boolean; hearing: boolean; pair_id?: string }
  | { type: "set_agent"; episode_id: string; agent: AgentName }
  | { type: "network_sim"; offline: boolean }
  | { type: "frame"; episode_id: string; ts: number; jpeg_b64: string }
  | { type: "imagine_results"; episode_id: string; request_id: string; options: { id: string; label: string; frames_b64: string[] }[] }
  | { type: "end_episode"; episode_id: string; outcome: Outcome };

export const BACKEND_HTTP = process.env.NEXT_PUBLIC_BACKEND_HTTP ?? "http://localhost:8000";
export const BACKEND_WS = process.env.NEXT_PUBLIC_BACKEND_WS ?? "ws://localhost:8000/ws";
