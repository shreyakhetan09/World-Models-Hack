"use client";

import { useEffect, useMemo, useState } from "react";
import { BACKEND_HTTP } from "@/lib/contract";

export interface EpisodeSummary {
  episode_id: string;
  scenario_id: string;
  scenario_title: string;
  hearing: boolean | null;
  imagination: boolean | null;
  started_at: number;
  duration_s: number;
  outcome: string | null;
  score: number;
  survivors_found: string[];
  time_to_first_survivor_s: number | null;
  sounds_heard: { type: string; label: string }[];
  imagination_choice: string | null;
  safety_overrides: number;
  steps: number;
}

interface Detail extends EpisodeSummary {
  timeline: { t: number; kind: string; text: string }[];
}

// Status palette (reserved for state) - always paired with an icon + label, never color alone.
const OUTCOME: Record<string, { icon: string; label: string; cls: string }> = {
  rescued: { icon: "✓", label: "Rescued", cls: "bg-survivor-tint text-survivor" },
  escaped: { icon: "✓", label: "Escaped", cls: "bg-survivor-tint text-survivor" },
  timeout: { icon: "⏱", label: "No rescue", cls: "bg-canvas text-muted" },
  failed: { icon: "✗", label: "Failed", cls: "bg-hazard-tint text-hazard" },
};

const SOUND_ICON: Record<string, string> = {
  human_distress: "🗣", child: "🧒", human_speech_warning: "⚠️", dog_or_animal: "🐕", tapping: "🔨",
  gas_hiss: "💨", structural_creak: "🏚", water: "🌊", fire: "🔥", alarm: "🚨", tv_or_radio: "📺", unknown: "🔊",
};

function fmtTime(ts: number) {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/** Score per episode, oldest -> newest. Single series: no legend; title names it. */
function ScoreChart({ eps, selected, onSelect }: { eps: EpisodeSummary[]; selected: string | null; onSelect(id: string): void }) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 460, H = 150, PAD_L = 28, PAD_B = 18, PAD_T = 14;
  const plotW = W - PAD_L - 6, plotH = H - PAD_B - PAD_T;
  const n = eps.length;
  const slot = n ? plotW / n : plotW;
  const barW = Math.max(3, Math.min(22, slot - 2)); // 2px surface gap between bars
  const y = (v: number) => PAD_T + plotH - (v / 100) * plotH;
  const h = hover !== null ? eps[hover] : null;
  return (
    <div className="viz-root relative">
      <div className="mb-1 flex items-baseline justify-between">
        <div className="text-sm font-medium text-ink">Score per episode</div>
        <div className="font-mono text-[11px] text-muted">oldest → newest · 0–100</div>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" onMouseLeave={() => setHover(null)}>
        {[0, 50, 100].map((v) => (
          <g key={v}>
            <line x1={PAD_L} x2={W - 6} y1={y(v)} y2={y(v)} stroke="var(--line)" strokeWidth={1} strokeDasharray={v === 0 ? undefined : "2 4"} />
            <text x={PAD_L - 6} y={y(v) + 3} textAnchor="end" fontSize="10" fill="var(--muted)" fontFamily="var(--font-mono)">{v}</text>
          </g>
        ))}
        {eps.map((e, i) => {
          const x = PAD_L + i * slot + (slot - barW) / 2;
          const top = y(Math.max(e.score, 1.5)); // keep a visible stub for 0 so the episode still has a mark
          const bh = y(0) - top;
          const r = Math.min(4, barW / 2, bh);
          const active = hover === i || selected === e.episode_id;
          return (
            <g key={e.episode_id} onMouseEnter={() => setHover(i)} onClick={() => onSelect(e.episode_id)} className="cursor-pointer">
              {/* hit target larger than the mark */}
              <rect x={PAD_L + i * slot} y={PAD_T} width={slot} height={plotH} fill="transparent" />
              <path
                d={`M${x},${y(0)} V${top + r} Q${x},${top} ${x + r},${top} H${x + barW - r} Q${x + barW},${top} ${x + barW},${top + r} V${y(0)} Z`}
                fill="var(--chart)" opacity={active ? 1 : hover !== null ? 0.45 : 0.85} />
            </g>
          );
        })}
        {n > 0 && (
          <text x={PAD_L + (n - 1) * slot + slot / 2} y={y(eps[n - 1].score) - 4} textAnchor="middle" fontSize="10" fill="var(--ink)" fontFamily="var(--font-mono)">
            {eps[n - 1].score}
          </text>
        )}
      </svg>
      {h && hover !== null && (
        <div className="pointer-events-none absolute top-6 z-10 w-56 rounded-xl border border-line bg-surface p-2.5 text-xs"
          style={{ left: `${Math.min(55, ((PAD_L + hover * slot) / W) * 100)}%` }}>
          <div className="font-medium text-ink">{h.scenario_title}</div>
          <div className="font-mono text-muted">{fmtTime(h.started_at)} · {h.duration_s.toFixed(0)} s</div>
          <div className="mt-1 text-ink">Score <span className="font-mono">{h.score}</span> · {OUTCOME[h.outcome ?? "timeout"]?.label ?? h.outcome}</div>
          {h.time_to_first_survivor_s !== null && <div className="text-muted">First survivor at {h.time_to_first_survivor_s.toFixed(0)} s</div>}
        </div>
      )}
    </div>
  );
}

export function EpisodesPanel({ refreshKey, scenarioId }: { refreshKey: number; scenarioId?: string }) {
  const [eps, setEps] = useState<EpisodeSummary[]>([]);
  const [rubric, setRubric] = useState("");
  const [showEmpty, setShowEmpty] = useState(false);
  const [filter, setFilter] = useState<string>(scenarioId ?? "all");
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${BACKEND_HTTP}/episodes`)
      .then((r) => r.json())
      .then((b) => {
        setEps(b.episodes);
        setRubric(b.score_rubric);
        setError(null);
      })
      .catch(() => setError("Could not load episodes"));
  }, [refreshKey]);

  useEffect(() => {
    if (!selected) return;
    fetch(`${BACKEND_HTTP}/episodes/${selected}`).then((r) => r.json()).then(setDetail).catch(() => setDetail(null));
  }, [selected]);

  // Runs that never got going (world failed to start, etc.) are hidden by default.
  const shown = useMemo(
    () => eps.filter((e) => (showEmpty || e.steps > 0) && (filter === "all" || e.scenario_id === filter)),
    [eps, showEmpty, filter],
  );
  const scenarioOptions = useMemo(() => {
    const m = new Map<string, string>();
    eps.forEach((e) => m.set(e.scenario_id, e.scenario_title));
    return [...m.entries()];
  }, [eps]);
  const rescued = shown.filter((e) => e.outcome === "rescued" || e.outcome === "escaped").length;
  const best = shown.reduce<EpisodeSummary | null>((b, e) => (!b || e.score > b.score ? e : b), null);

  if (error) return <p className="text-hazard">{error}</p>;

  const filters = (
    <div className="flex items-center gap-3 text-xs text-muted">
      <select className="rounded-full border border-line bg-surface px-3 py-1 text-ink" value={filter} onChange={(e) => setFilter(e.target.value)}>
        <option value="all">All scenarios</option>
        {scenarioOptions.map(([id, title]) => <option key={id} value={id}>{title}</option>)}
      </select>
      <label className="flex items-center gap-1">
        <input type="checkbox" checked={showEmpty} onChange={(e) => setShowEmpty(e.target.checked)} />
        include runs that never started
      </label>
    </div>
  );
  if (!shown.length) {
    return <div className="space-y-3">{filters}<p className="text-muted">No episodes yet for this filter. Run one and press Stop to save it.</p></div>;
  }

  return (
    <div className="space-y-3">
      {filters}
      <div className="grid grid-cols-3 gap-2">
        {[["Episodes", String(shown.length)], ["Rescues", `${rescued}/${shown.length}`], ["Best score", best ? String(best.score) : "–"]].map(([k, v]) => (
          <div key={k} className="rounded-2xl border border-line bg-surface px-3 py-2">
            <div className="text-xs text-muted">{k}</div>
            <div className="font-mono text-2xl text-ink">{v}</div>
          </div>
        ))}
      </div>

      <ScoreChart eps={shown} selected={selected} onSelect={setSelected} />
      <div className="text-[11px] leading-relaxed text-muted" title={rubric}>Rule-based score: {rubric}</div>


      <div className="space-y-1">
        {[...shown].reverse().map((e) => {
          const o = OUTCOME[e.outcome ?? "timeout"] ?? OUTCOME.timeout;
          const open = selected === e.episode_id;
          return (
            <div key={e.episode_id} className={`rounded-xl border ${open ? "border-primary/40 bg-tint" : "border-line bg-surface"}`}>
              <button className="flex w-full items-center gap-2 px-3 py-2 text-left" onClick={() => setSelected(open ? null : e.episode_id)}>
                <span className="w-12 font-mono text-xs text-muted">{fmtTime(e.started_at)}</span>
                <span className="flex-1 truncate text-ink">{e.scenario_title}</span>
                <span className="text-sm" title="sounds remembered">{e.sounds_heard.map((s) => SOUND_ICON[s.type] ?? "🔊").join("")}</span>
                <span className={`rounded-full px-2 py-0.5 text-xs ${o.cls}`}>{o.icon} {o.label}</span>
                <span className="w-8 text-right font-mono text-ink">{e.score}</span>
              </button>
              {open && detail?.episode_id === e.episode_id && (
                <div className="border-t border-line px-3 py-2 text-xs">
                  <div className="mb-2 grid grid-cols-2 gap-x-3 gap-y-0.5 text-ink">
                    <div>Duration: {detail.duration_s.toFixed(0)} s</div>
                    <div>Steps: {detail.steps}</div>
                    <div>First survivor: {detail.time_to_first_survivor_s !== null ? `${detail.time_to_first_survivor_s.toFixed(0)} s` : "–"}</div>
                    <div>Safety overrides: {detail.safety_overrides}</div>
                    <div>Hearing: {detail.hearing ? "on" : "off"} · Imagination: {detail.imagination ? "on" : "off"}</div>
                    <div>Imagined choice: {detail.imagination_choice ?? "–"}</div>
                  </div>
                  <ol className="space-y-0.5 border-l border-line pl-2">
                    {detail.timeline.map((t, i) => (
                      <li key={i} className={t.kind === "reveal" ? "text-survivor" : t.kind === "imagine_verdict" ? "text-primary-text" : "text-ink"}>
                        <span className="mr-1 font-mono text-muted">{t.t.toFixed(0).padStart(3, " ")}s</span>{t.text}
                      </li>
                    ))}
                  </ol>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
