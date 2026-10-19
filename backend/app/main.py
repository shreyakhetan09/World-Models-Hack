"""RescueSim backend: FastAPI app implementing shared/contract.md."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from .autopilot import live_decision  # noqa: E402
from .mock_agent import mock_decision  # noqa: E402
from .audio_engine import position_from  # noqa: E402
from .imagination import fallback_verdict, score as score_imagination  # noqa: E402
from .models import (  # noqa: E402
    AudioState,
    AudioTrigger,
    ClientEnvelope,
    DirectorEvent,
    DirectorTrigger,
    EndEpisode,
    EpisodeStarted,
    EpisodeSummary,
    ErrorMessage,
    Frame,
    ImagineResults,
    NetworkSim,
    SetAgent,
    StartEpisode,
)
from .episodes import SCORE_RUBRIC, summarize, timeline  # noqa: E402
from .scenarios import get_scenario, get_scenarios  # noqa: E402
from .state import Episode, EpisodeStore  # noqa: E402

AGENT_MODE = os.getenv("AGENT_MODE", "mock")
AUDIO_TICK_S = 0.25
IMAGINE_TIMEOUT_S = float(os.getenv("IMAGINE_TIMEOUT_S", "45"))
DECISION_MIN_INTERVAL_S = float(os.getenv("DECISION_MIN_INTERVAL_MS", "500")) / 1000

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("rescuesim")

app = FastAPI(title="RescueSim backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    # e.g. https://.*\.vercel\.app to also allow Vercel preview deployments
    allow_origin_regex=os.getenv("CORS_ORIGIN_REGEX") or None,
    allow_methods=["*"],
    allow_headers=["*"],
)
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

store = EpisodeStore()


class Connection:
    """One browser WebSocket. Processes only the latest frame per episode (never queues)."""

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.send_lock = asyncio.Lock()
        self.pending: dict[str, Frame] = {}
        self.workers: dict[str, asyncio.Task] = {}
        self.tickers: dict[str, asyncio.Task] = {}
        self.offline = False

    async def send(self, msg: BaseModel) -> None:
        async with self.send_lock:
            await self.ws.send_text(msg.model_dump_json())

    def submit_frame(self, frame: Frame) -> None:
        if frame.episode_id in self.pending:
            log.debug("dropping stale frame for %s", frame.episode_id)
        self.pending[frame.episode_id] = frame
        task = self.workers.get(frame.episode_id)
        if task is None or task.done():
            self.workers[frame.episode_id] = asyncio.create_task(self._work(frame.episode_id))

    async def _work(self, episode_id: str) -> None:
        last = 0.0
        while episode_id in self.pending:
            wait = DECISION_MIN_INTERVAL_S - (time.monotonic() - last)
            if wait > 0:
                await asyncio.sleep(wait)
            frame = self.pending.pop(episode_id, None)
            ep = store.get(episode_id)
            if frame is None or ep is None or ep.outcome is not None:
                return
            if ep.imagining:
                p = ep.pending_imagination
                if p is not None and time.time() - p.started > IMAGINE_TIMEOUT_S:
                    await self.finish_imagination(ep, fallback_verdict(p, ep.id, "timed out"))
                continue  # the world is paused while the robot imagines
            if time.time() < ep.busy_until:
                continue  # still executing the previous plan step
            last = time.monotonic()
            try:
                decision = await decide(ep, frame, offline=self.offline)
            except Exception:  # never crash the loop; the HUD shows "re-assessing"
                log.exception("decision failed for %s", episode_id)
                continue
            ep.record("decision", decision=decision.model_dump(exclude={"type"}))
            log.info("decision ep=%s move=%s look=%s latency=%.0fms", ep.id,
                     decision.action.move, decision.action.look, decision.latency_ms)
            await self.send(decision)
            while ep.outbox:
                await self.send(ep.outbox.pop(0))

    async def finish_imagination(self, ep: Episode, verdict) -> None:
        p = ep.pending_imagination
        chosen = p.maneuvers[verdict.chosen_id]
        ep.plan = [a.model_copy() for a in chosen.drive]
        ep.plan_label, ep.plan_total = chosen.label, len(ep.plan)
        ep.pending_imagination, ep.imagining = None, False
        ep.record("imagine_verdict", chosen=verdict.chosen_id, reason=verdict.reason,
                  scores=[s.model_dump() for s in verdict.scores])
        log.info("imagination ep=%s chose %s", ep.id, verdict.chosen_id)
        await self.send(verdict)

    async def handle_imagine_results(self, ep: Episode, msg: ImagineResults) -> None:
        p = ep.pending_imagination
        if p is None or msg.request_id != p.request_id:
            return
        try:
            verdict = await asyncio.wait_for(
                asyncio.to_thread(score_imagination, p, msg, ep.last_jpeg), timeout=25)
        except Exception as e:
            log.warning("imagination scoring failed: %s %s", type(e).__name__, str(e)[:200])
            verdict = fallback_verdict(p, ep.id, "scoring failed")
        await self.finish_imagination(ep, verdict)

    async def classify(self, ep: Episode) -> None:
        """Classify finished utterances right away, in parallel with driving/imagining."""
        from .autopilot import classify_capture

        try:
            while ep.audio.captures and ep.outcome is None:
                cap = ep.audio.take_capture()
                try:
                    # no wait_for: a timed-out thread would still finish and remember the sound twice
                    ev = await asyncio.to_thread(classify_capture, ep, cap)
                except Exception as e:
                    log.warning("sound classification failed: %s %s", type(e).__name__, str(e)[:200])
                    ep.audio.captures.insert(0, cap)  # keep the only recording; retry on the next tick
                    return
                if ev is not None:
                    await self.send(ev)
        finally:
            ep.classifying = False

    def start_audio(self, ep: Episode) -> None:
        if ep.audio is not None:
            self.tickers[ep.id] = asyncio.create_task(self._audio_tick(ep))

    async def _audio_tick(self, ep: Episode) -> None:
        """Ground-truth audio for speakers/radar at ~4 Hz, plus reveals when the robot arrives."""
        while ep.outcome is None:
            try:
                p = ep.pending_imagination
                if ep.imagining and p is not None and time.time() - p.started > IMAGINE_TIMEOUT_S:
                    await self.finish_imagination(ep, fallback_verdict(p, ep.id, "timed out"))
                ep.audio.tick(ep.pose)
                if ep.hearing and ep.audio.captures and not ep.classifying:
                    ep.classifying = True
                    asyncio.create_task(self.classify(ep))
                await self.send(AudioState(episode_id=ep.id, ts=time.time(), pose=ep.pose,
                                           sources=ep.audio.states(ep.pose)))
                for src in ep.audio.due_reveals(ep.pose):
                    ep.survivors_found.append(src.reveal.caption)
                    ep.record("reveal", source_id=src.id, caption=src.reveal.caption)
                    log.info("reveal ep=%s source=%s", ep.id, src.id)
                    await self.send(DirectorEvent(
                        episode_id=ep.id, kind="reveal", source_id=src.id, clause=src.reveal.world_prompt,
                        world_prompt=f"{ep.scenario.world_prompt} {src.reveal.world_prompt}",
                        caption=f"Located by sound: {src.reveal.caption}"))
            except Exception:
                log.exception("audio tick failed for %s", ep.id)
                return
            await asyncio.sleep(AUDIO_TICK_S)

    def cancel(self) -> None:
        for t in [*self.workers.values(), *self.tickers.values()]:
            t.cancel()


async def decide(ep: Episode, frame: Frame, offline: bool):
    if AGENT_MODE == "mock":
        await asyncio.sleep(0.05)
        return mock_decision(ep)
    if AGENT_MODE == "live":
        return await live_decision(ep, frame.jpeg_b64)
    raise NotImplementedError(f"AGENT_MODE={AGENT_MODE}")


connections: set[Connection] = set()


async def broadcast_to_episode(episode_id: str, msg: BaseModel) -> None:
    # Single-operator app: send to every connection; clients filter by episode_id.
    for conn in list(connections):
        try:
            await conn.send(msg)
        except Exception:
            log.warning("broadcast failed; dropping connection")
            connections.discard(conn)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    conn = Connection(ws)
    connections.add(conn)
    log.info("ws connected (%d open)", len(connections))
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = ClientEnvelope.model_validate_json(f'{{"msg": {raw}}}').msg
            except ValidationError as e:
                await conn.send(ErrorMessage(message=f"invalid message: {e.errors()[:3]}"))
                continue
            try:
                await handle(conn, msg)
            except HTTPException as e:
                await conn.send(ErrorMessage(message=str(e.detail)))
    except WebSocketDisconnect:
        pass
    finally:
        conn.cancel()
        connections.discard(conn)
        log.info("ws disconnected (%d open)", len(connections))


async def handle(conn: Connection, msg: Any) -> None:
    if isinstance(msg, StartEpisode):
        scenario = get_scenario(msg.scenario_id)
        if scenario is None:
            await conn.send(ErrorMessage(message=f"unknown scenario {msg.scenario_id}"))
            return
        ep = store.create(scenario=scenario, mode=msg.mode, agent=msg.agent,
                          imagination=msg.imagination, hearing=msg.hearing, pair_id=msg.pair_id)
        ep.record("start", mode=msg.mode, agent=msg.agent)
        log.info("episode %s started scenario=%s mode=%s agent=%s", ep.id, scenario.id,
                 msg.mode, msg.agent)
        await conn.send(EpisodeStarted(episode_id=ep.id, scenario=scenario))
        conn.start_audio(ep)
    elif isinstance(msg, Frame):
        if store.get(msg.episode_id) is None:
            await conn.send(ErrorMessage(message=f"unknown episode {msg.episode_id}"))
            return
        conn.submit_frame(msg)
    elif isinstance(msg, SetAgent):
        ep = _require(msg.episode_id)
        ep.agent = msg.agent
        ep.record("set_agent", agent=msg.agent)
    elif isinstance(msg, NetworkSim):
        conn.offline = msg.offline
        log.info("network_sim offline=%s", msg.offline)
    elif isinstance(msg, ImagineResults):
        ep = _require(msg.episode_id)
        ep.record("imagine_results", request_id=msg.request_id,
                  options=[o.label for o in msg.options])
        asyncio.create_task(conn.handle_imagine_results(ep, msg))
    elif isinstance(msg, EndEpisode):
        ep = _require(msg.episode_id)
        ep.outcome = msg.outcome
        ep.record("end", outcome=msg.outcome)
        path = ep.save()
        log.info("episode %s ended outcome=%s saved=%s", ep.id, msg.outcome, path.name)
        await conn.send(EpisodeSummary(episode_id=ep.id, score=ep.summary()["score"], outcome=msg.outcome))


def _require(episode_id: str) -> Episode:
    ep = store.get(episode_id)
    if ep is None:
        raise HTTPException(404, f"unknown episode {episode_id}")
    return ep


# ---------- HTTP ----------

@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "agent_mode": AGENT_MODE, "gemini_key": bool(os.getenv("GEMINI_API_KEY"))}


@app.get("/scenarios")
def scenarios():
    return get_scenarios()


@app.get("/episodes")
def episodes() -> dict[str, Any]:
    from .scenarios import get_scenario as _sc

    items = store.list()
    for it in items:
        sc = _sc(it.get("scenario_id") or "")
        if sc:
            it["scenario_title"] = sc.title
    return {"episodes": items, "score_rubric": SCORE_RUBRIC}


@app.get("/episodes/{episode_id}")
def episode_detail(episode_id: str) -> dict[str, Any]:
    d = store.load(episode_id)
    if d is None:
        raise HTTPException(404, f"unknown episode {episode_id}")
    sc = get_scenario(d.get("scenario_id") or "")
    summary = summarize(d, sc.title if sc else "")
    return {**summary, "timeline": timeline(d), "trail": d.get("trail", [])}


@app.post("/director/trigger")
async def director_trigger(body: DirectorTrigger) -> dict[str, Any]:
    event = body.event or ("A sudden aftershock shakes the corridor: ceiling panels crash down ahead and a "
                           "thick cloud of grey dust rolls toward the camera")
    for eid in body.episode_ids:
        ep = _require(eid)
        ep.record("director", event=event)
        ep.events.append((time.time(), event))
        await broadcast_to_episode(eid, DirectorEvent(
            episode_id=eid, kind="director",
            world_prompt=f"{ep.scenario.world_prompt} {event}", clause=event,
            caption=event.split(":")[0].strip().rstrip(".")))
    return {"ok": True, "event": event}


@app.post("/audio/trigger")
async def audio_trigger(body: AudioTrigger) -> dict[str, Any]:
    placed = {}
    for eid in body.episode_ids:
        ep = _require(eid)
        src = body.source
        if body.bearing_deg is not None and body.distance_m is not None:
            src = src.model_copy(update={"position": position_from(ep.pose, body.bearing_deg, body.distance_m)})
        ep.audio.inject(src)
        ep.record("audio_inject", source=src.model_dump())
        placed[eid] = src.position
    return {"ok": True, "placed": placed}


@app.post("/live/token")
async def live_token() -> dict[str, Any]:
    raise HTTPException(501, "Live guide not implemented yet (P7)")


@app.get("/models")
def models_list() -> list[dict[str, Any]]:
    return []


@app.get("/experiments/results")
def experiments_results() -> Optional[dict[str, Any]]:
    return None
