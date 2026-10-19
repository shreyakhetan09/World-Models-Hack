// Spatial playback of the backend's audio scene through the room's speakers (Web Audio, HRTF),
// so the audience hears what the robot hears. Driven by {type:"audio_state"} at ~4 Hz.
// The listener is the robot facing forward (-z). Bearing 0 = ahead, +90 = right.

import { BACKEND_HTTP } from "./contract";

export interface AudioSourceState {
  id: string;
  kind: string;
  clip_url: string;
  bearing_deg: number;
  distance_m: number;
  gain: number;
  muffled: boolean;
  playing: boolean;
  once?: boolean;      // play-once utterance
  play_index?: number; // changes when a new utterance starts
}

interface Voice {
  src: AudioBufferSourceNode;
  gain: GainNode;
  filter: BiquadFilterNode;
  panner: PannerNode;
}

export class AudioScenePlayer {
  private ctx: AudioContext | null = null;
  private master: GainNode | null = null;
  private buffers = new Map<string, Promise<AudioBuffer | null>>();
  private voices = new Map<string, Voice>();
  private lastPlay = new Map<string, number>();
  private _volume = 0.9;

  /** Must be called from a user gesture (e.g. the Start click) to unlock audio. */
  unlock() {
    if (!this.ctx) {
      this.ctx = new AudioContext();
      this.master = this.ctx.createGain();
      this.master.gain.value = this._volume;
      this.master.connect(this.ctx.destination);
    }
    void this.ctx.resume();
  }

  set volume(v: number) {
    this._volume = v;
    if (this.master) this.master.gain.value = v;
  }

  private load(url: string) {
    let p = this.buffers.get(url);
    if (!p) {
      p = fetch(`${BACKEND_HTTP}${url}`)
        .then((r) => r.arrayBuffer())
        .then((b) => this.ctx!.decodeAudioData(b))
        .catch(() => null);
      this.buffers.set(url, p);
    }
    return p;
  }

  /** Non-spatial one-shot (e.g. the robot's own loudspeaker call-out). */
  async playOnce(url: string, gain = 1) {
    if (!this.ctx) return;
    const buffer = await this.load(url);
    if (!buffer) return;
    const src = this.ctx.createBufferSource();
    src.buffer = buffer;
    const g = this.ctx.createGain();
    g.gain.value = gain;
    src.connect(g).connect(this.master!);
    src.start();
  }

  private async start(s: AudioSourceState) {
    const ctx = this.ctx!;
    const buffer = await this.load(s.clip_url);
    if (!buffer || this.voices.has(s.id)) return;
    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.loop = !s.once;
    if (s.once) src.onended = () => { if (this.voices.get(s.id)?.src === src) this.voices.delete(s.id); };
    const filter = ctx.createBiquadFilter();
    filter.type = "lowpass";
    const gain = ctx.createGain();
    gain.gain.value = 0;
    const panner = new PannerNode(ctx, { panningModel: "HRTF", distanceModel: "linear", refDistance: 1, maxDistance: 1000 });
    src.connect(filter).connect(gain).connect(panner).connect(this.master!);
    src.start();
    this.voices.set(s.id, { src, gain, filter, panner });
  }

  update(sources: AudioSourceState[]) {
    const ctx = this.ctx;
    if (!ctx) return;
    const t = ctx.currentTime;
    for (const s of sources) {
      if (s.once) {
        // play-once utterance: start each play_index exactly once, from the beginning
        const idx = s.play_index ?? -1;
        if (s.playing && idx >= 0 && idx !== this.lastPlay.get(s.id) && s.gain > 0.01) {
          this.lastPlay.set(s.id, idx);
          const old = this.voices.get(s.id);
          if (old) {
            try { old.src.stop(); } catch {}
            this.voices.delete(s.id);
          }
          void this.start(s);
        }
      } else if (s.playing && s.gain > 0.01 && !this.voices.has(s.id)) {
        void this.start(s);
      }
      const v = this.voices.get(s.id);
      if (!v) continue;
      const b = (s.bearing_deg * Math.PI) / 180;
      // Distance attenuation is already in s.gain; keep the panner at a fixed radius for direction only.
      v.panner.positionX.setTargetAtTime(Math.sin(b) * 2, t, 0.08);
      v.panner.positionZ.setTargetAtTime(-Math.cos(b) * 2, t, 0.08);
      v.filter.frequency.setTargetAtTime(s.muffled ? 700 : 18000, t, 0.1);
      v.gain.gain.setTargetAtTime(s.playing ? Math.min(1, s.gain * 1.8) : 0, t, 0.12);
    }
  }

  stopAll() {
    for (const v of this.voices.values()) {
      try {
        v.src.stop();
      } catch {}
      v.src.disconnect();
    }
    this.voices.clear();
    this.lastPlay.clear();
  }
}
