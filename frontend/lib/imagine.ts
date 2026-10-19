// Imagination runner: fork the world model from the robot's current frame, one session per
// candidate maneuver, drive each one through its maneuver and capture how the world turned out.
// Reactor allows 5 concurrent sessions per account: main + 3 forks fits.

import type { Action } from "./contract";
import { ReactorWorld, StaticWorld, type World } from "./world";

export interface ImagineOption {
  id: string;
  label: string;
  world_prompt: string; // clause describing the maneuver, appended to the base prompt
  drive: Action[];
}

export type ForkStatus = "starting" | "simulating" | "done" | "failed";

export interface ImagineCallbacks {
  onTile(id: string, el: HTMLVideoElement | HTMLCanvasElement): void;
  onStatus(id: string, status: ForkStatus): void;
  /** Frames captured so far in this fork (the imagined future), oldest first. */
  onFrames?(id: string, frames: string[]): void;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function runFork(kind: "reactor" | "static", referenceUrl: string, base: string, opt: ImagineOption,
                       cb: ImagineCallbacks, prewarmed?: World): Promise<string[]> {
  const w: World = prewarmed ?? (kind === "reactor" ? new ReactorWorld() : new StaticWorld());
  w.video.className = "h-full w-full object-cover";
  cb.onTile(opt.id, w.video);
  cb.onStatus(opt.id, "starting");
  const frames: string[] = [];
  try {
    await w.start(referenceUrl, base, [opt.world_prompt]);
    if (!(await w.ready(35000))) throw new Error("no video");
    await sleep(300);
    cb.onStatus(opt.id, "simulating");
    for (const a of opt.drive) {
      w.sendAction(a);
      await sleep(a.duration_ms + 200);
      const f = w.captureFrame(640, 0.8);
      if (f) {
        frames.push(f);
        cb.onFrames?.(opt.id, [...frames]);
      }
    }
    await sleep(700); // let the last chunk land
    const last = w.captureFrame(640, 0.8);
    if (last) frames.push(last);
    cb.onFrames?.(opt.id, [...frames]);
    cb.onStatus(opt.id, "done");
  } catch (e) {
    console.warn("[imagine] fork failed", opt.id, e);
    cb.onStatus(opt.id, "failed");
  } finally {
    await w.stop();
  }
  return frames.slice(-4);
}

export async function runImagination(kind: "reactor" | "static", frame: Blob, base: string,
                                     options: ImagineOption[], cb: ImagineCallbacks, pool: World[] = []) {
  const url = URL.createObjectURL(frame);
  try {
    const results = await Promise.all(options.map((o, i) => runFork(kind, url, base, o, cb, pool[i])));
    return options.map((o, i) => ({ id: o.id, label: o.label, frames_b64: results[i] }));
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  }
}

/** Connect imagination fork sessions ahead of time (Reactor only). Staggered to respect the
 *  new-session burst limit; failures are ignored (a fork then starts cold). */
export function prewarmForks(n: number): ReactorWorld[] {
  const pool = Array.from({ length: n }, () => new ReactorWorld());
  // Reactor allows ~3 new sessions in a burst (10/min): space them out after the main session.
  pool.forEach((w, i) => setTimeout(() => void w.connect().catch(() => {}), 3500 * (i + 1)));
  return pool;
}
