// A "world" is whatever produces the first-person video the agent sees.
//  - ReactorWorld: the real Lingbot-World-2 stream (costs money while running).
//  - StaticWorld: free stand-in that pans/zooms the reference image, so the whole
//    agent loop can be developed and tested without a Reactor key.

import { LingbotWorld2Model } from "@reactor-models/lingbot-world-2";
import type { Action } from "./contract";
import { composePrompt } from "./prompts";

export interface World {
  /** prompt = scenario base prompt; events = extra clauses (e.g. an imagined maneuver). */
  start(referenceImageUrl: string, prompt: string, events?: string[]): Promise<void>;
  pause(): Promise<void>;
  resume(): Promise<void>;
  /** Wait until the first real frame is visible (or timeout). */
  ready(timeoutMs?: number): Promise<boolean>;
  /** Apply an action for action.duration_ms, then go idle. A newer action replaces it. */
  sendAction(action: Action): void;
  /** Add a scene event clause (director event, trap, reveal) on top of the base prompt. */
  addEvent(clause: string): Promise<void>;
  /** Current frame as base64 JPEG (no data: prefix), or null if no frame yet. */
  captureFrame(maxWidth?: number, quality?: number): string | null;
  stop(): Promise<void>;
  readonly video: HTMLVideoElement | HTMLCanvasElement;
  onStatus?: (status: string) => void;
}

function frameToJpeg(source: CanvasImageSource, w: number, h: number, maxWidth: number, quality: number) {
  if (!w || !h) return null;
  const scale = Math.min(1, maxWidth / w);
  const c = document.createElement("canvas");
  c.width = Math.round(w * scale);
  c.height = Math.round(h * scale);
  c.getContext("2d")!.drawImage(source, 0, 0, c.width, c.height);
  return c.toDataURL("image/jpeg", quality).split(",")[1] ?? null;
}

// The SDK calls the resolver on every request, and a session can only be operated by the exact
// token that created it, so memoize one token per page and re-mint only near expiry.
let cachedToken: { jwt: string; expiresAt: number } | null = null;
let pendingToken: Promise<string> | null = null;

/** Current frame of a world as a JPEG Blob (for starting imagination forks from "now"). */
export function frameBlob(world: World, maxWidth = 1280): Blob | null {
  const b64 = world.captureFrame(maxWidth, 0.9);
  if (!b64) return null;
  const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  return new Blob([bytes], { type: "image/jpeg" });
}

async function fetchReactorJwt(): Promise<string> {
  if (cachedToken && cachedToken.expiresAt - Date.now() / 1000 > 300) return cachedToken.jwt;
  pendingToken ??= (async () => {
    const res = await fetch("/api/reactor-token", { method: "POST" });
    const body = await res.json();
    if (!res.ok) throw new Error(body.error ?? "could not get Reactor token");
    cachedToken = { jwt: body.jwt, expiresAt: body.expires_at };
    return body.jwt as string;
  })().finally(() => {
    pendingToken = null;
  });
  return pendingToken;
}

export class ReactorWorld implements World {
  readonly video: HTMLVideoElement;
  onStatus?: (status: string) => void;
  private model: LingbotWorld2Model | null = null;
  private idleTimer: ReturnType<typeof setTimeout> | null = null;
  private base = "";
  private events: string[] = [];
  private moving = false;

  /** Degrees per generated frame while looking (Reactor range 0-30). */
  constructor(private rotationSpeedDeg = 3) {
    this.video = document.createElement("video");
    this.video.autoplay = true;
    this.video.muted = true;
    this.video.playsInline = true;
  }

  /** Create + connect the session without starting generation. Lets imagination forks be
   *  pre-warmed so they skip session creation / capacity waits when the robot needs them.
   *  (Billing runs while connected, even before generation starts.) */
  private connecting: Promise<void> | null = null;

  /** Idempotent: concurrent callers (pre-warm + fork start) share one in-flight connection. */
  connect(): Promise<void> {
    this.connecting ??= this.doConnect().catch((e) => {
      this.connecting = null;
      throw e;
    });
    return this.connecting;
  }

  private async doConnect() {
    const model = new LingbotWorld2Model();
    this.model = model;
    model.on("statusChanged", (s) => this.onStatus?.(s));
    model.onMainVideo((_track, stream) => {
      this.video.srcObject = stream;
      void this.video.play().catch(() => {});
    });
    model.onCommandError((e) => console.warn("[reactor] command_error", e));

    // Reactor answers 429 when it has no free GPU capacity; that is usually brief, so retry.
    for (let attempt = 1; ; attempt++) {
      try {
        await model.connect(fetchReactorJwt);
        if (model.getStatus() !== "disconnected") break;
        throw model.getLastError() ?? new Error("connect failed");
      } catch (e) {
        const msg = String((e as Error)?.message ?? e);
        if (!/429|capacity|rate/i.test(msg) || attempt >= 12) {
          this.model = null;
          throw e;
        }
        this.onStatus?.(`no Reactor capacity, retrying (${attempt}/12)`);
        await new Promise((r) => setTimeout(r, 5000));
      }
    }
  }

  async start(referenceImageUrl: string, prompt: string, events: string[] = []) {
    try {
      await this.connect();
    } catch {
      this.connecting = null; // pre-warm failed: try once more from cold
      await this.connect();
    }
    const model = this.model!;
    const blob = await (await fetch(referenceImageUrl)).blob();
    const ref = await model.uploadFile(blob, { name: "reference.jpg" });
    await model.setImage({ image: ref });
    this.base = prompt;
    this.events = events;
    this.moving = false;
    await model.setPrompt({ prompt: composePrompt(this.base, false, this.events) });
    await model.setRotationSpeedDeg({ rotation_speed_deg: this.rotationSpeedDeg });
    await model.start();
  }

  async pause() {
    await this.model?.pause();
  }

  async resume() {
    await this.model?.resume();
  }

  async ready(timeoutMs = 30000) {
    const until = performance.now() + timeoutMs;
    while (performance.now() < until) {
      if (this.video.videoWidth > 0 && this.video.readyState >= 2) return true;
      await new Promise((r) => setTimeout(r, 200));
    }
    return false;
  }

  sendAction(action: Action) {
    const m = this.model;
    if (!m) return;
    if (this.idleTimer) clearTimeout(this.idleTimer);
    this.setMoving(action.move !== "none");
    void m.setMoveLongitudinal({ move_longitudinal: action.move === "W" ? "forward" : action.move === "S" ? "back" : "idle" });
    void m.setMoveLateral({ move_lateral: action.move === "A" ? "strafe_left" : action.move === "D" ? "strafe_right" : "idle" });
    void m.setLookHorizontal({ look_horizontal: action.look === "left" || action.look === "right" ? action.look : "idle" });
    void m.setLookVertical({ look_vertical: action.look === "up" || action.look === "down" ? action.look : "idle" });
    this.idleTimer = setTimeout(() => this.idle(), action.duration_ms);
  }

  private idle() {
    const m = this.model;
    if (!m) return;
    void m.setMoveLongitudinal({ move_longitudinal: "idle" });
    void m.setMoveLateral({ move_lateral: "idle" });
    void m.setLookHorizontal({ look_horizontal: "idle" });
    void m.setLookVertical({ look_vertical: "idle" });
    this.setMoving(false);
  }

  private setMoving(moving: boolean) {
    if (moving === this.moving) return;
    this.moving = moving;
    void this.model?.setPrompt({ prompt: composePrompt(this.base, moving, this.events) });
  }

  async addEvent(clause: string) {
    this.events = [...this.events.slice(-1), clause]; // keep at most 2 events (length budget)
    await this.model?.setPrompt({ prompt: composePrompt(this.base, this.moving, this.events) });
  }

  captureFrame(maxWidth = 640, quality = 0.8) {
    return frameToJpeg(this.video, this.video.videoWidth, this.video.videoHeight, maxWidth, quality);
  }

  async stop() {
    if (this.idleTimer) clearTimeout(this.idleTimer);
    const m = this.model;
    this.model = null;
    this.connecting = null;
    if (m) {
      await m.reset().catch(() => {});
      await m.disconnect().catch(() => {});
    }
    this.video.srcObject = null;
  }
}

/** Free offline world: a camera "moving" over the reference image. */
export class StaticWorld implements World {
  readonly video: HTMLCanvasElement;
  onStatus?: (status: string) => void;
  private img: HTMLImageElement | null = null;
  private raf = 0;
  private cam = { yaw: 0, zoom: 1 };
  private vel = { yaw: 0, zoom: 0 };
  private idleAt = 0;
  private caption = "";

  constructor() {
    this.video = document.createElement("canvas");
    this.video.width = 1280;
    this.video.height = 720;
  }

  private paused = false;

  async start(referenceImageUrl: string, prompt: string, events: string[] = []) {
    this.onStatus?.("connecting");
    this.caption = events.length ? events[events.length - 1] : prompt;
    this.img = await new Promise<HTMLImageElement | null>((resolve) => {
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = () => resolve(img);
      img.onerror = () => resolve(null); // no reference image yet: draw a placeholder
      img.src = referenceImageUrl;
    });
    this.onStatus?.("ready");
    let last = performance.now();
    const tick = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      if (now > this.idleAt || this.paused) this.vel = { yaw: 0, zoom: 0 };
      this.cam.yaw += this.vel.yaw * dt;
      this.cam.zoom = Math.min(2.5, Math.max(1, this.cam.zoom + this.vel.zoom * dt));
      this.draw();
      this.raf = requestAnimationFrame(tick);
    };
    this.raf = requestAnimationFrame(tick);
  }

  sendAction(action: Action) {
    this.vel = {
      yaw: action.look === "left" ? -0.25 : action.look === "right" ? 0.25 : 0,
      zoom: action.move === "W" ? 0.15 : action.move === "S" ? -0.15 : 0,
    };
    if (action.move === "A") this.vel.yaw = -0.12;
    if (action.move === "D") this.vel.yaw = 0.12;
    this.idleAt = performance.now() + action.duration_ms;
  }

  async addEvent(clause: string) {
    this.caption = clause;
  }

  async pause() {
    this.paused = true;
  }

  async resume() {
    this.paused = false;
  }

  async ready() {
    return true;
  }

  private draw() {
    const c = this.video;
    const ctx = c.getContext("2d")!;
    const { width: W, height: H } = c;
    if (this.img) {
      const z = this.cam.zoom;
      const sw = this.img.width / z;
      const sh = this.img.height / z;
      const maxShift = (this.img.width - sw) / 2;
      const sx = (this.img.width - sw) / 2 + Math.max(-1, Math.min(1, this.cam.yaw)) * maxShift;
      const sy = (this.img.height - sh) / 2;
      ctx.drawImage(this.img, sx, sy, sw, sh, 0, 0, W, H);
    } else {
      const g = ctx.createLinearGradient(0, 0, 0, H);
      g.addColorStop(0, "#1e293b");
      g.addColorStop(1, "#0f172a");
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = "#64748b";
      ctx.font = "28px sans-serif";
      ctx.fillText("StaticWorld: no reference image yet", 40, 60);
      ctx.font = "18px sans-serif";
      ctx.fillText(this.caption.slice(0, 120), 40, 100);
      ctx.strokeStyle = "#334155";
      const vx = W / 2 - this.cam.yaw * 300;
      for (let i = -8; i <= 8; i++) {
        ctx.beginPath();
        ctx.moveTo(vx, H / 2);
        ctx.lineTo(W / 2 + i * 200 * this.cam.zoom, H);
        ctx.stroke();
      }
    }
  }

  captureFrame(maxWidth = 640, quality = 0.8) {
    return frameToJpeg(this.video, this.video.width, this.video.height, maxWidth, quality);
  }

  async stop() {
    cancelAnimationFrame(this.raf);
  }
}
