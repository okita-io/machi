import {
  consumePcmFrames,
  emptyPcmPending,
  FRAME_SAMPLES,
  pcmFrameLogEnabled,
  SAMPLE_RATE,
  type PcmPending,
} from "./pcm";
import { PCM_WORKLET_NAME, PCM_WORKLET_SOURCE } from "./workletSource";

export function micCaptureAvailable(isSecureContext: boolean, hasGetUserMedia: boolean): boolean {
  return isSecureContext && hasGetUserMedia;
}

export function micErrorMessage(err: unknown): string {
  if (err instanceof DOMException && err.name === "NotAllowedError") {
    return "Microphone permission was denied";
  }
  if (err instanceof Error && err.message) return err.message;
  return "Microphone failed";
}

function asFloat32(data: unknown): Float32Array {
  if (data instanceof Float32Array) return data;
  if (data instanceof ArrayBuffer) return new Float32Array(data);
  return new Float32Array();
}

export type MicFrameHandler = (frame: Uint8Array) => void;

/**
 * AudioWorklet capture. `prepare` opens the mic; `connect` starts 16 kHz Int16 frames.
 * Callers send `audio_start` between those two so binary frames never precede the event.
 */
export class MicCapture {
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private node: AudioWorkletNode | null = null;
  private pending: PcmPending = emptyPcmPending();
  private frameIndex = 0;

  async prepare(): Promise<void> {
    const hasMic = typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia;
    if (!micCaptureAvailable(window.isSecureContext, hasMic)) {
      throw new Error("Microphone needs localhost or HTTPS");
    }
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    try {
      this.ctx = new AudioContext({ sampleRate: SAMPLE_RATE });
    } catch {
      this.ctx = new AudioContext();
    }
    await this.ctx.resume();
    const url = URL.createObjectURL(
      new Blob([PCM_WORKLET_SOURCE], { type: "application/javascript" }),
    );
    try {
      await this.ctx.audioWorklet.addModule(url);
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  connect(onFrame: MicFrameHandler): void {
    if (!this.ctx || !this.stream) {
      throw new Error("Microphone is not prepared");
    }
    const ctx = this.ctx;
    this.source = ctx.createMediaStreamSource(this.stream);
    this.node = new AudioWorkletNode(ctx, PCM_WORKLET_NAME);
    this.pending = emptyPcmPending();
    this.frameIndex = 0;
    const inputRate = ctx.sampleRate;
    const logFrames = pcmFrameLogEnabled(import.meta.env.DEV, import.meta.env.VITE_LOG_PCM_FRAMES);
    this.node.port.onmessage = (event: MessageEvent) => {
      const chunk = asFloat32(event.data);
      if (chunk.length === 0) return;
      const next = consumePcmFrames(this.pending, chunk, inputRate, SAMPLE_RATE, FRAME_SAMPLES);
      this.pending = next.pending;
      for (const frame of next.frames) {
        this.frameIndex += 1;
        if (logFrames) {
          console.log(`[machi] pcm frame ${this.frameIndex} (${frame.byteLength} bytes)`);
        }
        onFrame(frame);
      }
    };
    this.source.connect(this.node);
  }

  async stop(): Promise<void> {
    this.node?.disconnect();
    this.source?.disconnect();
    this.node = null;
    this.source = null;
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
    this.pending = emptyPcmPending();
    const ctx = this.ctx;
    this.ctx = null;
    if (ctx && ctx.state !== "closed") {
      await ctx.close();
    }
  }
}
