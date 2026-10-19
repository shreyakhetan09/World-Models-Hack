"use client";

import { useEffect, useRef, useState } from "react";
import type { Heard } from "@/lib/contract";
import type { AudioSourceState } from "@/lib/audioScene";

const SIZE = 168;
const R = SIZE / 2 - 14;
const MAX_M = 15;
const SOUND = "#e8a33d";
const HAZARD = "#e05a47";
const LINE = "var(--line)";

function xy(bearing: number, dist: number) {
  const r = (Math.min(dist, MAX_M) / MAX_M) * R;
  const b = (bearing * Math.PI) / 180;
  return [SIZE / 2 + Math.sin(b) * r, SIZE / 2 - Math.cos(b) * r];
}

/** What the robot hears, forward = up. Amber dot per source; dashed ring = muffled; coral ring =
 *  heard hazard; hollow = suspected decoy. A new sound pulses once; nothing sweeps. Hollow grey
 *  rings (operator toggle) = ground truth, to show mic-array error. */
export function AudioRadar({ heard, truth, showTruth, hearingOn }: {
  heard: Heard[];
  truth: AudioSourceState[];
  showTruth: boolean;
  hearingOn: boolean;
}) {
  const seen = useRef(new Set<string>());
  const [fresh, setFresh] = useState<Set<string>>(new Set());

  useEffect(() => {
    const keys = heard.map((h) => h.label);
    const added = keys.filter((k) => !seen.current.has(k));
    if (!added.length) return;
    added.forEach((k) => seen.current.add(k));
    setFresh(new Set(added));
    const id = setTimeout(() => setFresh(new Set()), 2600);
    return () => clearTimeout(id);
  }, [heard]);

  const audible = truth.filter((s) => s.playing && s.gain > 0.04);
  return (
    <div className="pointer-events-none absolute bottom-4 left-4 rounded-2xl bg-surface p-2">
      <div className="flex items-center justify-between px-1 pb-1 text-xs text-muted">
        <span>Hearing</span>
        <span className="font-mono text-ink">{hearingOn ? `${heard.length} src` : "off"}</span>
      </div>
      <svg width={SIZE} height={SIZE}>
        {[1, 2, 3].map((i) => (
          <circle key={i} cx={SIZE / 2} cy={SIZE / 2} r={(R * i) / 3} fill="none" stroke={LINE} strokeWidth={1} />
        ))}
        <line x1={SIZE / 2} y1={SIZE / 2 - R} x2={SIZE / 2} y2={SIZE / 2 - R + 6} stroke="var(--muted)" strokeWidth={1} />
        <text x={SIZE / 2 + 4} y={SIZE / 2 - R + 7} fontSize="9" fill="var(--muted)" fontFamily="var(--font-mono)">fwd</text>
        <polygon points={`${SIZE / 2},${SIZE / 2 - 6} ${SIZE / 2 - 4.5},${SIZE / 2 + 4} ${SIZE / 2 + 4.5},${SIZE / 2 + 4}`} fill="var(--ink)" />
        {showTruth && audible.map((s) => {
          const [x, y] = xy(s.bearing_deg, s.distance_m);
          return <circle key={`t-${s.id}`} cx={x} cy={y} r={8} fill="none" stroke="var(--muted)" strokeWidth={1} strokeDasharray="2 2" />;
        })}
        {heard.map((h, i) => {
          const [x, y] = xy(h.bearing_deg, h.distance_m);
          const muffled = /muffl/i.test(h.label);
          return (
            <g key={`h-${h.source_id ?? h.label}-${i}`}>
              {fresh.has(h.label) && <circle className="ring-pulse" cx={x} cy={y} r={7} fill="none" stroke={SOUND} strokeWidth={1.5} />}
              <circle cx={x} cy={y} r={11} fill="none" stroke={h.is_hazard ? HAZARD : SOUND} strokeWidth={1}
                strokeDasharray={muffled ? "2 3" : undefined} opacity={muffled ? 0.6 : 0.9} />
              <circle cx={x} cy={y} r={4.5} fill={h.is_decoy_suspected ? "none" : SOUND} stroke={SOUND} strokeWidth={1.5} />
            </g>
          );
        })}
      </svg>
      {heard[0] && (
        <div className="max-w-[168px] truncate px-1 pt-1 text-[11px] text-muted" title={heard.map((h) => h.label).join(" · ")}>
          {heard[0].label} <span className="font-mono text-ink">{heard[0].bearing_deg > 0 ? "+" : ""}{Math.round(heard[0].bearing_deg)}°</span>
        </div>
      )}
    </div>
  );
}
