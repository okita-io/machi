/** Map AnalyserNode loudness to a 2-frame mouth. Silence stays closed. */

export type MouthFrame = "closed" | "open";

/** Time-domain RMS at or above this opens the mouth. */
export const MOUTH_OPEN_GAIN = 0.08;

const SILENCE = 128;

/**
 * Loudness in 0..1 from AnalyserNode `getByteTimeDomainData` bytes.
 * Those samples sit at 128 when the signal is silent.
 */
export function analyserGain(timeDomain: ArrayLike<number>): number {
  if (timeDomain.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < timeDomain.length; i++) {
    const centered = (timeDomain[i] - SILENCE) / SILENCE;
    sum += centered * centered;
  }
  return Math.sqrt(sum / timeDomain.length);
}

export function mouthFrameForGain(gain: number, openAt = MOUTH_OPEN_GAIN): MouthFrame {
  if (!Number.isFinite(gain) || gain < openAt) return "closed";
  return "open";
}
