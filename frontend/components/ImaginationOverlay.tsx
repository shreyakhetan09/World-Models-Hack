"use client";

import type { ForkStatus, ImagineOption } from "@/lib/imagine";

export interface ImagineScore {
  id: string;
  risk: number;
  progress: number;
  summary: string;
}

export interface ImaginationView {
  requestId: string;
  options: ImagineOption[];
  status: Record<string, ForkStatus>;
  tiles: Record<string, HTMLVideoElement | HTMLCanvasElement>;
  frames?: Record<string, string[]>; // captured frames per fork (kept after the fork session ends)
  verdict?: { scores: ImagineScore[]; chosen_id: string; reason: string };
}

const STATUS_TEXT: Record<ForkStatus, string> = {
  starting: "Forking the world from the current view…",
  simulating: "Simulating the maneuver…",
  done: "Outcome captured",
  failed: "Simulation failed",
};

/** The imagination moment: three rounded cards, one per imagined future, then scores and the choice. */
export function ImaginationOverlay({ view }: { view: ImaginationView }) {
  const v = view.verdict;
  return (
    <div className="absolute inset-0 z-10 flex flex-col bg-canvas/[0.97] p-5">
      <div className="mb-4 flex items-start gap-3">
        <svg width="28" height="28" viewBox="0 0 28 28" className="mt-0.5 shrink-0">
          {[13, 9, 5].map((r) => <circle key={r} cx="14" cy="14" r={r} fill="none" stroke="var(--primary-text)" strokeWidth="1" opacity={r === 5 ? 1 : 0.5} />)}
        </svg>
        <div>
          <div className="text-lg font-medium text-ink">{v ? "Imagined futures: decision" : "Imagining possible futures"}</div>
          <div className="text-sm text-muted">
            {v ? v.reason : "The world model is forked from the robot's current view; each fork runs one maneuver."}
          </div>
        </div>
      </div>
      <div className="grid flex-1 grid-cols-3 gap-4">
        {view.options.map((o) => {
          const s = v?.scores.find((x) => x.id === o.id);
          const chosen = v?.chosen_id === o.id;
          const frames = view.frames?.[o.id] ?? [];
          const done = view.status[o.id] === "done" || view.status[o.id] === "failed" || !!v;
          return (
            <div key={o.id}
              className={`flex flex-col overflow-hidden rounded-2xl bg-surface ${
                chosen ? "border-2 border-primary" : "border border-line"} ${v && !chosen ? "opacity-70" : ""}`}>
              <div className="flex items-center justify-between px-3 py-2">
                <span className="text-sm font-medium text-ink">{o.label}</span>
                {chosen && <span className="rounded-full bg-primary px-2.5 py-0.5 text-xs font-medium text-on-primary">Chosen</span>}
              </div>
              <div className="mx-3 overflow-hidden rounded-xl bg-frame">
                {done && frames.length ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img alt="imagined outcome" className="aspect-video w-full object-cover" src={`data:image/jpeg;base64,${frames[frames.length - 1]}`} />
                ) : (
                  <div className="relative aspect-video"
                    ref={(el) => {
                      const tile = view.tiles[o.id];
                      if (el && tile && el.firstChild !== tile) el.replaceChildren(tile);
                    }} />
                )}
              </div>
              {done && frames.length > 1 && (
                <div className="mx-3 mt-1.5 flex gap-1">
                  {frames.map((f, i) => (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img key={i} alt={`step ${i + 1}`} className="h-9 flex-1 rounded-md object-cover" src={`data:image/jpeg;base64,${f}`} />
                  ))}
                </div>
              )}
              <div className="flex-1 px-3 py-2.5 text-xs">
                {!s && <div className="text-muted">{STATUS_TEXT[view.status[o.id] ?? "starting"]}</div>}
                {s && (
                  <>
                    <div className="mb-1.5 flex gap-1.5">
                      <span className="rounded-full bg-tint px-2 py-0.5 font-mono text-primary-text">progress {s.progress.toFixed(0)}</span>
                      <span className={`rounded-full px-2 py-0.5 font-mono ${s.risk >= 5 ? "bg-hazard-tint text-hazard" : "bg-canvas text-muted"}`}>
                        risk {s.risk.toFixed(0)}
                      </span>
                    </div>
                    <div className="leading-relaxed text-ink">{s.summary}</div>
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
