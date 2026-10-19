"""Pydantic models for every message in shared/contract.md."""

from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, Field

Move = Literal["W", "A", "S", "D", "none"]
Look = Literal["left", "right", "up", "down", "none"]
AgentName = Literal["cloud", "onboard", "baseline"]
Mode = Literal["autopilot", "survivor", "collect"]
Outcome = Literal["escaped", "rescued", "failed", "timeout"]
SoundKind = Literal["voice", "tapping", "gas_hiss", "creak", "water", "alarm", "fire", "tv_radio", "dog"]


# ---------- scenario ----------

class Trigger(BaseModel):
    near: tuple[float, float]
    radius_m: float


class Trap(BaseModel):
    description: str
    cue: str
    trigger: Trigger
    world_prompt: str
    caption: str


class Reveal(BaseModel):
    radius_m: float = 2.5
    world_prompt: str
    caption: str


class Play(BaseModel):
    """One utterance: the clip plays once, starting at_s seconds into the episode."""
    at_s: float
    clip_url: Optional[str] = None  # defaults to the source's clip_url


class AudioSource(BaseModel):
    id: str
    kind: SoundKind
    position: tuple[float, float]
    clip_url: str
    loop: bool = True
    start_s: float = 0
    stop_s: Optional[float] = None
    gain_db: float = 0
    muffled: bool = False
    transcript: Optional[str] = None
    is_hazard: bool = False
    severity: Optional[Literal[1, 2, 3]] = None
    is_decoy: bool = False
    urgency: Optional[Literal[1, 2, 3]] = None
    reveal: Optional[Reveal] = None
    # If set, the source is NOT continuous: it plays each clip once at these times, then goes quiet.
    plays: Optional[list[Play]] = None


class Scenario(BaseModel):
    id: str
    title: str
    description: str
    world_prompt: str
    reference_image_url: str
    held_out: bool = False
    trap: Optional[Trap] = None
    audio_sources: list[AudioSource] = Field(default_factory=list)


# ---------- shared pieces ----------

class Action(BaseModel):
    move: Move = "none"
    look: Look = "none"
    duration_ms: int = 500


class Pose(BaseModel):
    x: float = 0
    y: float = 0
    heading_deg: float = 0


class PointLabel(BaseModel):
    point: tuple[int, int]  # [y, x] normalized 0-1000
    label: str


class Hazard(PointLabel):
    severity: Literal[1, 2, 3]


class Heard(BaseModel):
    source_id: Optional[str] = None
    bearing_deg: float
    distance_m: float
    label: str
    is_hazard: bool = False
    is_decoy_suspected: bool = False
    urgency: Literal[1, 2, 3] = 1


# ---------- frontend -> backend ----------

class StartEpisode(BaseModel):
    type: Literal["start_episode"]
    scenario_id: str
    mode: Mode = "autopilot"
    agent: AgentName = "cloud"
    imagination: bool = False
    hearing: bool = False
    pair_id: Optional[str] = None


class SetAgent(BaseModel):
    type: Literal["set_agent"]
    episode_id: str
    agent: AgentName


class NetworkSim(BaseModel):
    type: Literal["network_sim"]
    offline: bool


class Frame(BaseModel):
    type: Literal["frame"]
    episode_id: str
    ts: float
    jpeg_b64: str


class ImagineOptionResult(BaseModel):
    id: str
    label: str
    frames_b64: list[str]


class ImagineResults(BaseModel):
    type: Literal["imagine_results"]
    episode_id: str
    request_id: str
    options: list[ImagineOptionResult]


class EndEpisode(BaseModel):
    type: Literal["end_episode"]
    episode_id: str
    outcome: Outcome


ClientMessage = Union[StartEpisode, SetAgent, NetworkSim, Frame, ImagineResults, EndEpisode]


class ClientEnvelope(BaseModel):
    msg: ClientMessage = Field(discriminator="type")


# ---------- backend -> frontend ----------

class EpisodeStarted(BaseModel):
    type: Literal["episode_started"] = "episode_started"
    episode_id: str
    scenario: Scenario


class Decision(BaseModel):
    type: Literal["decision"] = "decision"
    episode_id: str
    ts: float
    action: Action
    survivors: list[PointLabel] = Field(default_factory=list)
    hazards: list[Hazard] = Field(default_factory=list)
    heard: list[Heard] = Field(default_factory=list)
    priority: str = ""
    exit_seen: bool = False
    pose: Pose = Field(default_factory=Pose)
    reason: str = ""
    safety_override: Optional[str] = None
    source: AgentName = "cloud"
    latency_ms: float = 0


class AudioSourceState(BaseModel):
    id: str
    kind: SoundKind
    clip_url: str
    bearing_deg: float
    distance_m: float
    gain: float
    muffled: bool
    playing: bool
    once: bool = False        # play-once utterance (frontend starts the clip fresh on each play)
    play_index: int = -1      # which utterance is playing (changes -> start the clip again)


class AudioState(BaseModel):
    type: Literal["audio_state"] = "audio_state"
    episode_id: str
    ts: float
    pose: Pose
    sources: list[AudioSourceState]


class ImagineOption(BaseModel):
    id: str
    label: str
    world_prompt: str
    drive: list[Action]


class ImagineRequest(BaseModel):
    type: Literal["imagine_request"] = "imagine_request"
    episode_id: str
    request_id: str
    options: list[ImagineOption]


class ImagineScore(BaseModel):
    id: str
    risk: float
    progress: float
    summary: str


class ImagineVerdict(BaseModel):
    type: Literal["imagine_verdict"] = "imagine_verdict"
    episode_id: str
    request_id: str
    scores: list[ImagineScore]
    chosen_id: str
    reason: str


class DirectorEvent(BaseModel):
    type: Literal["director_event"] = "director_event"
    episode_id: str
    kind: Literal["director", "trap", "reveal"] = "director"
    world_prompt: str  # full prompt (base + clause), for clients that don't compose layers
    clause: Optional[str] = None  # event sentence to append on top of the base prompt
    caption: str
    source_id: Optional[str] = None


class SoundEvent(BaseModel):
    """A finished sound was classified and remembered (sent as soon as the utterance ends)."""
    type: Literal["sound_event"] = "sound_event"
    episode_id: str
    ts: float
    label: str
    sound_type: str
    bearing_deg: float
    distance_m: float
    observations: int
    is_survivor: bool
    reason: str
    heard: list[Heard] = Field(default_factory=list)  # full remembered-sound list for the radar


class EpisodeSummary(BaseModel):
    type: Literal["episode_summary"] = "episode_summary"
    episode_id: str
    score: float
    outcome: Outcome
    lessons: list[str] = Field(default_factory=list)


class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    message: str


# ---------- HTTP bodies ----------

class DirectorTrigger(BaseModel):
    episode_ids: list[str]
    event: Optional[str] = None


class AudioTrigger(BaseModel):
    episode_ids: list[str]
    source: AudioSource
    # If set, place the source relative to each robot's current pose instead of source.position.
    bearing_deg: Optional[float] = None
    distance_m: Optional[float] = None


class GenerateScenario(BaseModel):
    seed: str
