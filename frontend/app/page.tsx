"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AudioRadar } from "@/components/AudioRadar";
import { EpisodesPanel } from "@/components/EpisodesPanel";
import { actionChip, friendlyOverride, HudOverlay } from "@/components/HudOverlay";
import { ImaginationOverlay, type ImaginationView } from "@/components/ImaginationOverlay";
import { prewarmForks, runImagination } from "@/lib/imagine";
import { AudioScenePlayer, type AudioSourceState } from "@/lib/audioScene";
import { BackendClient } from "@/lib/backend";
import { BACKEND_HTTP, type Decision, type Heard, type Mode, type Pose, type Scenario, type ServerMessage } from "@/lib/contract";
import { frameBlob, ReactorWorld, StaticWorld, type World } from "@/lib/world";

const CALLOUT_URL = "/static/audio/voices/robot_callout.wav";
const VERDICT_HOLD_MS = 3000;
const FORKS = 3;
const MISSION_END_HOLD_MS = 4000;

const FRAME_INTERVAL_MS = Number(process.env.NEXT_PUBLIC_FRAME_INTERVAL_MS ?? 500);
type WorldKind = "static" | "reactor";
type LogEntry = { id: number; t: number; text: string; chip: string; override?: string | null; thumb?: string | null; repeat?: number };
type Banner = { text: string; tone: "danger" | "found" };

// Operator palette: inject a sound relative to the robot's current pose (POST /audio/trigger).
const INJECT_PRESETS = [
  { label: "🗣 Cry for help · behind-left", bearing: -130, distance: 7, source: {
    kind: "voice", clip_url: "/static/audio/voices/help_im_stuck_weak.wav", muffled: true, urgency: 3,
    reveal: { radius_m: 3, world_prompt: "A dust-covered person lies trapped under a collapsed desk, waving one arm toward the camera.", caption: "Survivor trapped under debris" } } },
  { label: "🧒 Child crying · right", bearing: 100, distance: 9, source: {
    kind: "voice", clip_url: "/static/audio/voices/is_anyone_there_child.wav", urgency: 3,
    reveal: { radius_m: 3, world_prompt: "A frightened child crouches beside an overturned cabinet, looking at the camera.", caption: "Child found" } } },
  { label: "💨 Gas hiss · ahead", bearing: 8, distance: 4, source: {
    kind: "gas_hiss", clip_url: "/static/audio/fx/gas_hiss.wav", is_hazard: true, severity: 3 } },
  { label: "🏚 Creaking · overhead", bearing: 0, distance: 3, source: {
    kind: "creak", clip_url: "/static/audio/fx/creak.wav", is_hazard: true, severity: 3, stop_s: 25 } },
  { label: "⚠️ \"Don't come this way!\"", bearing: 5, distance: 10, source: {
    kind: "voice", clip_url: "/static/audio/voices/dont_come_this_way.wav", is_hazard: true, loop: false } },
  { label: "🔨 SOS tapping · behind-right", bearing: 140, distance: 7, source: {
    kind: "tapping", clip_url: "/static/audio/fx/sos_knock.wav", muffled: true, urgency: 3,
    reveal: { radius_m: 3, world_prompt: "A worker pinned behind fallen boxes knocks on a metal shelf with a wrench.", caption: "Survivor found by tapping" } } },
  { label: "📺 TV voice (decoy) · left", bearing: -70, distance: 6, source: {
    kind: "tv_radio", clip_url: "/static/audio/voices/tv_news_decoy.wav", is_decoy: true } },
] as const;

export default function MissionControl() {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioId, setScenarioId] = useState("");
  const [worldKind, setWorldKind] = useState<WorldKind>(
    process.env.NEXT_PUBLIC_DEFAULT_WORLD === "reactor" ? "reactor" : "static",
  );
  const [mode, setMode] = useState<Mode>("autopilot");
  const [hearing, setHearing] = useState(true);
  const [imagination, setImagination] = useState(true);
  const [imagineView, setImagineView] = useState<ImaginationView | null>(null);
  const [imagineHistory, setImagineHistory] = useState<{ id: string; reason: string; chosen: string }[]>([]);

  const [connected, setConnected] = useState(false);
  const [worldStatus, setWorldStatus] = useState("idle");
  const [episodeId, setEpisodeId] = useState<string | null>(null);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [receivedAt, setReceivedAt] = useState(0);
  const [trail, setTrail] = useState<Pose[]>([]);
  const [log, setLog] = useState<LogEntry[]>([]);
  const [banner, setBanner] = useState<Banner | null>(null);
  const [truth, setTruth] = useState<AudioSourceState[]>([]);
  const [heard, setHeard] = useState<Heard[]>([]);
  const [showTruth, setShowTruth] = useState(false);
  const [hearingActive, setHearingActive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState({ steps: 0, survivors: 0, hazardsAvoided: 0, elapsedS: 0 });
  const [tab, setTab] = useState<"log" | "imagination" | "episodes">("log");
  const [episodesVersion, setEpisodesVersion] = useState(0);
  const [projector, setProjector] = useState(false);

  useEffect(() => {
    document.documentElement.dataset.theme = projector ? "dark" : "light";
  }, [projector]);

  const backend = useRef<BackendClient | null>(null);
  const world = useRef<World | null>(null);
  const videoHost = useRef<HTMLDivElement>(null);
  const episodeRef = useRef<string | null>(null);
  const startedAt = useRef(0);
  const lastThumb = useRef<string | null>(null);
  const logId = useRef(0);
  const player = useRef<AudioScenePlayer | null>(null);
  const injectId = useRef(0);
  const imagining = useRef(false);
  const scenarioRef = useRef<Scenario | null>(null);
  const worldKindRef = useRef<WorldKind>("static");
  const forkPool = useRef<World[]>([]);
  const stopRef = useRef<((o: "rescued") => Promise<void>) | null>(null);

  useEffect(() => {
    fetch(`${BACKEND_HTTP}/scenarios`)
      .then((r) => r.json())
      .then((s: Scenario[]) => {
        setScenarios(s);
        setScenarioId((cur) => cur || s[0]?.id || "");
      })
      .catch(() => setError(`Backend not reachable at ${BACKEND_HTTP}. Is uvicorn running?`));

    const client = new BackendClient();
    client.onConnection = setConnected;
    client.connect();
    backend.current = client;
    return () => client.close();
  }, []);

  const handleDecision = useCallback((d: Decision) => {
    if (d.episode_id !== episodeRef.current) return;
    world.current?.sendAction(d.action);
    setDecision(d);
    setReceivedAt(performance.now());
    setTrail((t) => [...t.slice(-500), d.pose]);
    setHeard(d.heard);
    setStats((s) => ({
      ...s,
      steps: s.steps + 1,
      survivors: s.survivors + d.survivors.length,
      hazardsAvoided: s.hazardsAvoided + (d.safety_override || (d.hazards.length && d.action.move !== "W") ? 1 : 0),
    }));
    const entry = { id: logId.current++, t: Date.now(), text: d.reason, chip: actionChip(d.action), override: d.safety_override, thumb: lastThumb.current };
    setLog((l) => (l[0] && l[0].text === entry.text && !entry.override
      ? [{ ...l[0], t: entry.t, thumb: entry.thumb, repeat: (l[0].repeat ?? 1) + 1 }, ...l.slice(1)]
      : [entry, ...l].slice(0, 200)));
  }, []);

  const imagine = useCallback(async (req: Extract<ServerMessage, { type: "imagine_request" }>) => {
    const main = world.current;
    const scenario = scenarioRef.current;
    if (!main || !scenario) return;
    imagining.current = true;
    const blob = frameBlob(main);
    await main.pause();
    setImagineView({ requestId: req.request_id, options: req.options, status: {}, tiles: {} });
    if (!blob) return;
    const pool = forkPool.current;
    forkPool.current = [];
    const options = await runImagination(worldKindRef.current, blob, scenario.world_prompt, req.options, {
      onTile: (id, el) => setImagineView((v) => (v ? { ...v, tiles: { ...v.tiles, [id]: el } } : v)),
      onStatus: (id, st) => setImagineView((v) => (v ? { ...v, status: { ...v.status, [id]: st } } : v)),
      onFrames: (id, fr) => setImagineView((v) => (v ? { ...v, frames: { ...v.frames, [id]: fr } } : v)),
    }, pool);
    backend.current?.send({ type: "imagine_results", episode_id: req.episode_id, request_id: req.request_id, options });
  }, []);

  useEffect(() => {
    const client = backend.current;
    if (!client) return;
    return client.subscribe((msg) => {
      if (msg.type === "decision") handleDecision(msg);
      else if (msg.type === "audio_state" && msg.episode_id === episodeRef.current) {
        player.current?.update(msg.sources);
        setTruth(msg.sources);
      } else if (msg.type === "director_event" && msg.episode_id === episodeRef.current) {
        void world.current?.addEvent(msg.clause ?? msg.world_prompt);
        setBanner({ text: msg.caption, tone: msg.kind === "reveal" ? "found" : "danger" });
        if (msg.kind === "reveal") {
          setStats((st) => ({ ...st, survivors: st.survivors + 1 }));
          // Mission complete: hold the moment, then end the episode (keeps the demo under a minute).
          const eid = msg.episode_id;
          setTimeout(() => { if (episodeRef.current === eid) stopRef.current?.("rescued"); }, MISSION_END_HOLD_MS);
        }
        setTimeout(() => setBanner(null), msg.kind === "reveal" ? 5000 : 4000);
      } else if (msg.type === "imagine_request" && msg.episode_id === episodeRef.current) {
        void imagine(msg);
      } else if (msg.type === "imagine_verdict" && msg.episode_id === episodeRef.current) {
        setImagineView((v) => (v && v.requestId === msg.request_id ? { ...v, verdict: msg } : v));
        const chosen = msg.chosen_id;
        setImagineHistory((h) => [{ id: msg.request_id, reason: msg.reason, chosen }, ...h]);
        setTimeout(async () => {
          setImagineView(null);
          await world.current?.resume();
          imagining.current = false;
        }, VERDICT_HOLD_MS);
      } else if (msg.type === "sound_event" && msg.episode_id === episodeRef.current) {
        setHeard(msg.heard);
        const entry = { id: logId.current++, t: Date.now(), text: msg.reason, chip: "Heard" };
        setLog((l) => [entry, ...l].slice(0, 200));
      } else if (msg.type === "episode_summary") {
        setEpisodesVersion((v) => v + 1);
      } else if (msg.type === "error") setError(msg.message);
    });
  }, [handleDecision, imagine, connected]);


  // Frame loop: capture -> backend while an episode runs.
  useEffect(() => {
    if (!episodeId) return;
    const id = setInterval(() => {
      if (imagining.current) return; // main world is paused while the robot imagines
      const jpeg = world.current?.captureFrame();
      setStats((s) => ({ ...s, elapsedS: (performance.now() - startedAt.current) / 1000 }));
      if (!jpeg) return;
      lastThumb.current = jpeg;
      backend.current?.send({ type: "frame", episode_id: episodeId, ts: Date.now() / 1000, jpeg_b64: jpeg });
    }, FRAME_INTERVAL_MS);
    return () => clearInterval(id);
  }, [episodeId]);

  async function start() {
    const scenario = scenarios.find((s) => s.id === scenarioId);
    const client = backend.current;
    if (!scenario || !client) return;
    setError(null);
    player.current ??= new AudioScenePlayer();
    player.current.unlock(); // inside the click handler, so the browser allows audio

    const w: World = worldKind === "reactor" ? new ReactorWorld() : new StaticWorld();
    w.onStatus = setWorldStatus;
    world.current = w;
    w.video.className = "h-full w-full object-cover";
    videoHost.current?.replaceChildren(w.video);
    scenarioRef.current = scenario;
    worldKindRef.current = worldKind;
    imagining.current = false;
    setImagineView(null);
    setImagineHistory([]);
    try {
      await w.start(`${BACKEND_HTTP}${scenario.reference_image_url}`, scenario.world_prompt);
      await w.ready(40000); // start the episode clock when the world is actually visible
    } catch (e) {
      setError(`World failed to start: ${(e as Error).message}`);
      return;
    }

    const started = await new Promise<string>((resolve) => {
      const off = client.subscribe((msg) => {
        if (msg.type === "episode_started") {
          off();
          resolve(msg.episode_id);
        }
      });
      client.send({ type: "start_episode", scenario_id: scenario.id, mode, agent: "cloud", imagination, hearing });
    });
    episodeRef.current = started;
    startedAt.current = performance.now();
    setStats({ steps: 0, survivors: 0, hazardsAvoided: 0, elapsedS: 0 });
    setTrail([{ x: 0, y: 0, heading_deg: 0 }]);
    setLog([]);
    setDecision(null);
    setHeard([]);
    setTruth([]);
    setHearingActive(hearing);
    setEpisodeId(started);
    // Pre-warm the imagination forks so the "imagine" moment doesn't wait on Reactor session start.
    if (worldKind === "reactor" && imagination && hearing) forkPool.current = prewarmForks(FORKS);
    if (hearing) void player.current.playOnce(CALLOUT_URL, 0.8); // "If you can hear me, call out!"
  }

  async function stop(outcome: "timeout" | "escaped" | "failed" | "rescued" = "timeout") {
    if (episodeId) backend.current?.send({ type: "end_episode", episode_id: episodeId, outcome });
    episodeRef.current = null;
    setEpisodeId(null);
    player.current?.stopAll();
    forkPool.current.forEach((w) => void w.stop()); // unused pre-warmed forks: disconnect (stops billing)
    forkPool.current = [];
    await world.current?.stop();
    setWorldStatus("idle");
  }

  useEffect(() => {
    stopRef.current = (o) => stop(o);
  });

  async function inject(preset: (typeof INJECT_PRESETS)[number]) {
    if (!episodeId) return;
    await fetch(`${BACKEND_HTTP}/audio/trigger`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        episode_ids: [episodeId],
        bearing_deg: preset.bearing,
        distance_m: preset.distance,
        source: { id: `inj_${preset.source.kind}_${injectId.current++}`, position: [0, 0], ...preset.source },
      }),
    });
  }

  async function triggerEvent() {
    if (!episodeId) return;
    await fetch(`${BACKEND_HTTP}/director/trigger`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ episode_ids: [episodeId] }),
    });
  }

  const running = episodeId !== null;
  const pill = "rounded-full border border-line bg-surface px-3 py-1.5 text-sm text-ink disabled:opacity-60";
  const toggle = (on: boolean) =>
    `flex cursor-pointer items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm ${
      on ? "border-primary/30 bg-tint text-primary-text" : "border-line bg-surface text-muted"}`;

  return (
    <div className="flex h-screen flex-col bg-canvas text-ink">
      <header className="flex flex-wrap items-center gap-2.5 px-5 py-3">
        <Wordmark />
        <div className="mx-2 h-5 w-px bg-line" />
        <select className={pill} value={scenarioId} disabled={running} onChange={(e) => setScenarioId(e.target.value)}>
          {scenarios.map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}
        </select>
        <select className={pill} value={mode} disabled={running} onChange={(e) => setMode(e.target.value as Mode)}>
          <option value="autopilot">Autopilot</option>
          <option value="survivor" disabled>Survivor (coming soon)</option>
        </select>
        <select className={pill} value={worldKind} disabled={running} onChange={(e) => setWorldKind(e.target.value as WorldKind)}>
          <option value="static">Static world (free)</option>
          <option value="reactor">Reactor world (~$0.42/min)</option>
        </select>
        <label className={toggle(hearing)}>
          <input type="checkbox" className="sr-only" checked={hearing} disabled={running} onChange={(e) => setHearing(e.target.checked)} />
          <span className={`h-1.5 w-1.5 rounded-full ${hearing ? "bg-primary" : "bg-line"}`} />Hearing
        </label>
        <label className={toggle(imagination)}>
          <input type="checkbox" className="sr-only" checked={imagination} disabled={running} onChange={(e) => setImagination(e.target.checked)} />
          <span className={`h-1.5 w-1.5 rounded-full ${imagination ? "bg-primary" : "bg-line"}`} />Imagination
        </label>
        {!running ? (
          <button className="rounded-full bg-primary px-5 py-1.5 text-sm font-medium text-on-primary disabled:opacity-40"
            disabled={!connected || !scenarioId} onClick={start}>Start</button>
        ) : (
          <>
            <button className="rounded-full border border-hazard/40 bg-surface px-5 py-1.5 text-sm font-medium text-hazard"
              onClick={() => stop(stats.survivors > 0 ? "rescued" : "timeout")}>Stop</button>
            <button className={pill} onClick={triggerEvent}>Disaster event</button>
          </>
        )}
        <div className="ml-auto flex items-center gap-2 font-mono text-xs text-muted">
          <span className="flex items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1">
            <span className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-survivor" : "bg-hazard"}`} />
            {connected ? "online" : "offline"}
          </span>
          <span className="rounded-full border border-line bg-surface px-3 py-1">world {worldStatus}</span>
          <button className="rounded-full border border-line bg-surface px-3 py-1 font-sans" onClick={() => setProjector((p) => !p)}
            title="High-contrast dark mode for a stage projector">{projector ? "Light" : "Projector"}</button>
        </div>
      </header>

      {error && <div className="mx-5 mb-2 rounded-xl border border-hazard/30 bg-hazard-tint px-4 py-2 text-sm text-hazard">{error}</div>}

      <main className="flex min-h-0 flex-1 gap-4 px-5 pb-5">
        <section className="relative w-[65%] overflow-hidden rounded-2xl bg-frame">
          <div ref={videoHost} className="absolute inset-0" />
          {!running && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-sm text-[#8fa09c]">
              <svg width="56" height="56" viewBox="0 0 56 56">
                {[26, 18, 10].map((r) => <circle key={r} cx="28" cy="28" r={r} fill="none" stroke="#2c3b38" strokeWidth="1" />)}
                <circle cx="28" cy="28" r="2.5" fill="#5cc2b6" />
              </svg>
              Pick a scenario and press Start
            </div>
          )}
          {running && <HudOverlay decision={decision} receivedAt={receivedAt} trail={trail} stats={stats} />}
          {running && <AudioRadar heard={heard} truth={truth} showTruth={showTruth} hearingOn={hearingActive} />}
          {imagineView && <ImaginationOverlay view={imagineView} />}
          {banner && (
            <div className={`slide-down absolute left-1/2 top-24 z-20 max-w-[80%] rounded-2xl border px-5 py-2.5 text-base font-medium ${
              banner.tone === "found" ? "border-survivor/30 bg-survivor-tint text-survivor" : "border-hazard/30 bg-hazard-tint text-hazard"}`}>
              {banner.text}
            </div>
          )}
        </section>

        <aside className="flex w-[35%] min-w-0 flex-col overflow-hidden rounded-2xl border border-line bg-surface">
          <nav className="m-3 flex rounded-full bg-canvas p-1 text-sm">
            {(["log", "imagination", "episodes"] as const).map((t) => (
              <button key={t} onClick={() => setTab(t)}
                className={`flex-1 rounded-full py-1.5 ${tab === t ? "bg-surface font-medium text-ink" : "text-muted"}`}>
                {t === "log" ? "Decisions" : t === "imagination" ? "Imagination" : "Episodes"}
              </button>
            ))}
          </nav>
          {running && (
            <div className="mx-3 mb-2 rounded-xl border border-line p-2.5">
              <div className="mb-1.5 flex items-center justify-between text-xs text-muted">
                <span>Inject a sound</span>
                <label className="flex items-center gap-1">
                  <input type="checkbox" checked={showTruth} onChange={(e) => setShowTruth(e.target.checked)} />
                  show true positions
                </label>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {INJECT_PRESETS.map((p) => (
                  <button key={p.label} onClick={() => inject(p)}
                    className="rounded-full border border-line px-2.5 py-1 text-xs text-ink hover:border-sound hover:bg-sound-tint">{p.label}</button>
                ))}
              </div>
            </div>
          )}
          <div className="flex-1 overflow-y-auto px-3 pb-3 text-sm">
            {tab === "log" && (log.length === 0
              ? <p className="px-1 text-muted">Decisions appear here.</p>
              : log.map((e) => (
                <details key={e.id} className={`mb-2 rounded-xl border px-3 py-2 ${e.override ? "border-hazard/30 bg-hazard-tint" : "border-line"}`}>
                  <summary className="flex cursor-pointer list-none items-start gap-2">
                    <span className="mt-0.5 w-14 shrink-0 font-mono text-[11px] text-muted">{new Date(e.t).toLocaleTimeString([], { hour12: false })}</span>
                    <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${
                      e.override ? "bg-surface text-hazard" : e.chip === "Heard" ? "bg-sound-tint text-ink" : e.chip === "Hold" ? "bg-canvas text-muted" : "bg-tint text-primary-text"}`}>
                      {e.chip === "Heard" && <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-sound align-middle" />}{e.chip}</span>
                    <span className="min-w-0 text-ink">
                      {e.override ? <span className="text-hazard">{friendlyOverride(e.override)} </span> : null}
                      {e.text}
                      {e.repeat && e.repeat > 1 ? <span className="ml-1 font-mono text-[11px] text-muted">×{e.repeat}</span> : null}
                    </span>
                  </summary>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  {e.thumb && <img alt="frame" className="mt-2 w-full rounded-lg" src={`data:image/jpeg;base64,${e.thumb}`} />}
                </details>
              )))}
            {tab === "imagination" && (imagineHistory.length === 0
              ? <p className="px-1 text-muted">When the robot locates a survivor, it imagines each route in a forked world before moving.</p>
              : imagineHistory.map((h) => (
                <div key={h.id} className="mb-2 rounded-xl border border-line px-3 py-2">
                  <span className="rounded-full bg-tint px-2 py-0.5 text-[11px] font-medium text-primary-text">Chose {h.chosen.replace("_", " ")}</span>
                  <div className="mt-1.5 text-ink">{h.reason}</div>
                </div>
              )))}
            {tab === "episodes" && <EpisodesPanel key={scenarioId} refreshKey={episodesVersion} scenarioId={scenarioId} />}
          </div>
        </aside>
      </main>
    </div>
  );
}

/** Lowercase, slightly rounded wordmark; a small ring stands in for the dot of the i. */
function Wordmark() {
  return (
    <div className="flex items-baseline text-[22px] font-medium tracking-tight text-ink">
      <span>rescues</span>
      <span className="relative inline-block">
        <span>ı</span>
        <svg width="8" height="8" viewBox="0 0 9 9" className="absolute left-1/2 -translate-x-1/2" style={{ top: "0.16em" }}>
          <circle cx="4.5" cy="4.5" r="3.2" fill="none" stroke="var(--primary-text)" strokeWidth="1.4" />
        </svg>
      </span>
      <span>m</span>
    </div>
  );
}
