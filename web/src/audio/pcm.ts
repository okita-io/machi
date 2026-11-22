/** Mono 16 kHz signed 16-bit PCM. One frame is 20 ms (320 samples, 640 bytes). */

export const SAMPLE_RATE = 16_000;
export const FRAME_MS = 20;
export const FRAME_SAMPLES = (SAMPLE_RATE * FRAME_MS) / 1000;
export const FRAME_BYTES = FRAME_SAMPLES * 2;

export type PcmPending = {
  samples: Float32Array;
  /** Read head inside `samples` for the next output sample, in input-rate samples. */
  phase: number;
};

export function emptyPcmPending(): PcmPending {
  return { samples: new Float32Array(0), phase: 0 };
}

/** Dev logs each captured frame. `VITE_LOG_PCM_FRAMES=0` silences them; production never logs. */
export function pcmFrameLogEnabled(dev: boolean, flag: string | undefined): boolean {
  if (!dev) return false;
  return flag !== "0" && flag !== "false";
}

/** Clamp a float sample in [-1, 1] to signed 16-bit PCM. */
export function floatSampleToInt16(sample: number): number {
  const clamped = Math.max(-1, Math.min(1, sample));
  return clamped < 0 ? Math.round(clamped * 32768) : Math.round(clamped * 32767);
}

/**
 * Slice already-resampled float audio into little-endian Int16 frames.
 * Pure: does not mutate `samples`.
 */
export function sliceFloat32ToInt16Frames(
  samples: Float32Array,
  frameSamples: number = FRAME_SAMPLES,
): { frames: Uint8Array[]; remainder: Float32Array } {
  const frameCount = Math.floor(samples.length / frameSamples);
  const frames: Uint8Array[] = [];
  for (let frame = 0; frame < frameCount; frame++) {
    const pcm = new Int16Array(frameSamples);
    const offset = frame * frameSamples;
    for (let i = 0; i < frameSamples; i++) {
      pcm[i] = floatSampleToInt16(samples[offset + i] ?? 0);
    }
    frames.push(new Uint8Array(pcm.buffer));
  }
  const used = frameCount * frameSamples;
  const remainder = new Float32Array(samples.length - used);
  remainder.set(samples.subarray(used));
  return { frames, remainder };
}

function concatFloat32(left: Float32Array, right: Float32Array): Float32Array {
  if (left.length === 0) return right.slice();
  if (right.length === 0) return left.slice();
  const merged = new Float32Array(left.length + right.length);
  merged.set(left, 0);
  merged.set(right, left.length);
  return merged;
}

/**
 * Resample incoming float audio to `outputRate` and pull whole Int16 frames.
 * Leftover input stays in `pending` so chunk boundaries do not drop samples.
 */
export function consumePcmFrames(
  pending: PcmPending,
  incoming: Float32Array,
  inputRate: number,
  outputRate: number = SAMPLE_RATE,
  frameSamples: number = FRAME_SAMPLES,
): { frames: Uint8Array[]; pending: PcmPending } {
  if (inputRate <= 0 || outputRate <= 0) {
    throw new Error("sample rate must be positive");
  }
  const samples = concatFloat32(pending.samples, incoming);
  const phase = pending.phase;
  if (samples.length === 0) {
    return { frames: [], pending: { samples, phase } };
  }

  const ratio = inputRate / outputRate;
  let available = 0;
  while (available < samples.length) {
    const pos = phase + available * ratio;
    const i0 = Math.floor(pos);
    const lastIndex = pos === i0 ? i0 : i0 + 1;
    if (lastIndex >= samples.length) break;
    available += 1;
  }

  const emit = Math.floor(available / frameSamples) * frameSamples;
  if (emit === 0) {
    return { frames: [], pending: { samples, phase } };
  }

  const output = new Float32Array(emit);
  for (let i = 0; i < emit; i++) {
    const pos = phase + i * ratio;
    const i0 = Math.floor(pos);
    const frac = pos - i0;
    const s0 = samples[i0] ?? 0;
    const s1 = samples[Math.min(i0 + 1, samples.length - 1)] ?? s0;
    output[i] = s0 + (s1 - s0) * frac;
  }

  const nextPos = phase + emit * ratio;
  const drop = Math.min(Math.floor(nextPos), samples.length);
  const kept = new Float32Array(samples.length - drop);
  kept.set(samples.subarray(drop));
  return {
    frames: sliceFloat32ToInt16Frames(output, frameSamples).frames,
    pending: { samples: kept, phase: nextPos - drop },
  };
}

/** Join captured Int16 frames into standard base64 for a REST review answer. */
export function pcmChunksToBase64(chunks: Uint8Array[]): string {
  const total = chunks.reduce((sum, chunk) => sum + chunk.byteLength, 0);
  const merged = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, offset);
    offset += chunk.byteLength;
  }
  let binary = "";
  const step = 0x8000;
  for (let index = 0; index < merged.length; index += step) {
    binary += String.fromCharCode(...merged.subarray(index, index + step));
  }
  return btoa(binary);
}
