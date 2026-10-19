"use client";

import { useEffect, useRef } from "react";
import type { Decision, Pose } from "@/lib/contract";

// Decisions arrive every ~2 s; keep markers visible about that long, then fade.
const MARKER_FADE_MS = 3000;
const HAZARD = "#e05a47";
const SURVIVOR = "#2fa66a";
const INK = "#122220";

interface Props {
  decision: Decision | null;
  receivedAt: number;
  trail: Pose[];
  stats: { steps: number; survivors: number; hazardsAvoided: number; elapsedS: number };
}

/** Plain-language version of a safety-layer override, in the robot's voice. */
export function friendlyOverride(reason: string): string {
  if (/audio: gas/i.test(reason)) return "Pausing: I can hear gas ahead.";
  if (/audio: structural|creak/i.test(reason)) return "Pausing: I can hear the structure creaking ahead.";
  if (/audio: (fire|water)/i.test(reason)) return `Pausing: I can hear ${reason.match(/audio: ([^)]+)/i)?.[1]} ahead.`;
  if (/warned away/i.test(reason)) return "Pausing: someone warned me away from this direction.";
  if (/back and forth/i.test(reason)) return "Rethinking: I was turning back and forth.";
  const m = reason.match(/^(.*) directly ahead/i);
  if (m) return `Pausing: ${m[1]} directly ahead. Backing off.`;
  return `Pausing: ${reason}.`;
}

export function actionChip(d: { move: string; look: string }): "Move" | "Turn" | "Hold" | "Back" {
  if (d.move === "W" || d.move === "A" || d.move === "D") return "Move";
  if (d.move === "S") return "Back";
  if (d.look !== "none") return "Turn";
  return "Hold";
}

function label(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, dot: string) {
  ctx.font = "500 13px Satoshi, ui-sans-serif, system-ui";
  const w = ctx.measureText(text).width;
  const h = 22, r = 11;
  ctx.fillStyle = "#ffffff";
  ctx.beginPath();
  ctx.roundRect(x, y - h / 2, w + 30, h, r);
  ctx.fill();
  ctx.fillStyle = dot;
  ctx.beginPath();
  ctx.arc(x + 11, y, 3.5, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = INK;
  ctx.fillText(text, x + 20, y + 4.5);
}

/** Canvas overlay drawn on top of the world video. Coordinates are [y, x] in 0-1000. */
export function HudOverlay({ decision, receivedAt, trail, stats }: Props) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    let raf = 0;
    const draw = () => {
      const c = ref.current;
      if (!c) return;
      const { clientWidth: W, clientHeight: H } = c;
      if (c.width !== W || c.height !== H) {
        c.width = W;
        c.height = H;
      }
      const ctx = c.getContext("2d")!;
      ctx.clearRect(0, 0, W, H);
      const age = performance.now() - receivedAt;
      const alpha = Math.max(0, 1 - age / MARKER_FADE_MS);
      const px = ([y, x]: [number, number]) => [(x / 1000) * W, (y / 1000) * H] as const;

      if (decision && alpha > 0) {
        ctx.globalAlpha = alpha;
        for (const s of decision.survivors) {
          const [x, y] = px(s.point);
          ctx.strokeStyle = SURVIVOR;
          ctx.lineWidth = 1.5;
          for (const r of [10, 18]) {
            ctx.beginPath();
            ctx.arc(x, y, r, 0, Math.PI * 2);
            ctx.stroke();
          }
          label(ctx, s.label, x + 24, y, SURVIVOR);
        }
        for (const h of decision.hazards) {
          const [x, y] = px(h.point);
          ctx.strokeStyle = HAZARD;
          ctx.lineWidth = h.severity === 3 ? 2 : 1.5;
          ctx.beginPath();
          ctx.moveTo(x, y - 12);
          ctx.lineTo(x + 11, y + 8);
          ctx.lineTo(x - 11, y + 8);
          ctx.closePath();
          ctx.stroke();
          ctx.fillStyle = HAZARD;
          ctx.fillRect(x - 0.75, y - 5, 1.5, 6);
          ctx.fillRect(x - 0.75, y + 3, 1.5, 1.5);
          label(ctx, h.severity === 3 ? `${h.label} · deadly` : h.label, x + 18, y, HAZARD);
        }
        ctx.globalAlpha = 1;
      }
      drawMinimap(ctx, trail, W, H);
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [decision, receivedAt, trail]);

  const chip = decision ? actionChip(decision.action) : null;

  return (
    <div className="pointer-events-none absolute inset-0">
      <canvas ref={ref} className="absolute inset-0 h-full w-full" />

      <div className="absolute left-4 top-4 flex gap-1.5">
        {[["steps", stats.steps], ["located", stats.survivors], ["avoided", stats.hazardsAvoided], ["t+", `${stats.elapsedS.toFixed(0)}s`]].map(([k, v]) => (
          <div key={k} className="rounded-full bg-surface/95 px-3 py-1 text-xs text-muted">
            {k} <span className="font-mono text-ink">{v}</span>
          </div>
        ))}
      </div>

      {decision?.exit_seen && (
        <div className="absolute right-4 top-4 rounded-full bg-survivor-tint px-3 py-1 text-xs font-medium text-survivor">
          ● Exit in view
        </div>
      )}

      {decision?.safety_override && (
        <div key={decision.ts}
          className="slide-down absolute left-1/2 top-14 rounded-2xl border border-hazard/30 bg-hazard-tint px-4 py-2 text-sm font-medium text-hazard">
          {friendlyOverride(decision.safety_override)}
        </div>
      )}

      {decision && (
        <div className="absolute bottom-4 left-1/2 flex max-w-[52%] -translate-x-1/2 items-start gap-3 rounded-2xl bg-surface px-4 py-3">
          {chip && (
            <span className={`mt-0.5 shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium ${
              chip === "Hold" ? "bg-canvas text-muted" : "bg-tint text-primary-text"}`}>{chip}</span>
          )}
          <div className="min-w-0">
            <div className="text-[15px] leading-snug text-ink">{decision.reason}</div>
            {decision.priority && <div className="mt-0.5 truncate text-xs text-muted">Goal: {decision.priority}</div>}
          </div>
          <span className="ml-1 shrink-0 whitespace-nowrap font-mono text-[11px] text-muted">
            {Math.round(decision.latency_ms)} ms
          </span>
        </div>
      )}
    </div>
  );
}

function drawMinimap(ctx: CanvasRenderingContext2D, trail: Pose[], W: number, H: number) {
  const size = 148;
  const ox = W - size - 16;
  const oy = H - size - 16;
  ctx.fillStyle = "#ffffff";
  ctx.beginPath();
  ctx.roundRect(ox, oy, size, size, 14);
  ctx.fill();
  ctx.strokeStyle = "#e3e8e6";
  ctx.lineWidth = 1;
  ctx.stroke();
  const cx0 = ox + size / 2, cy0 = oy + size / 2;
  ctx.strokeStyle = "#e3e8e6";
  for (const r of [22, 44, 66]) {
    ctx.beginPath();
    ctx.arc(cx0, cy0, r, 0, Math.PI * 2);
    ctx.stroke();
  }
  if (trail.length === 0) return;
  const last = trail[trail.length - 1];
  const scale = 6; // px per meter, centered on the robot
  const toPx = (p: Pose) => [cx0 + (p.x - last.x) * scale, cy0 - (p.y - last.y) * scale];
  ctx.save();
  ctx.beginPath();
  ctx.roundRect(ox, oy, size, size, 14);
  ctx.clip();
  ctx.strokeStyle = "#0f6b63";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  trail.forEach((p, i) => {
    const [x, y] = toPx(p);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.restore();
  const h = (last.heading_deg * Math.PI) / 180;
  ctx.fillStyle = INK;
  ctx.beginPath();
  ctx.moveTo(cx0 + Math.sin(h) * 8, cy0 - Math.cos(h) * 8);
  ctx.lineTo(cx0 + Math.sin(h + 2.5) * 5.5, cy0 - Math.cos(h + 2.5) * 5.5);
  ctx.lineTo(cx0 + Math.sin(h - 2.5) * 5.5, cy0 - Math.cos(h - 2.5) * 5.5);
  ctx.fill();
}
