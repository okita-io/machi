/**
 * Green-screen key for baked Sora plates.
 * Pure green (low red and blue) becomes transparent. Teal eyes, the white
 * sticker outline, and the character stay opaque. Soft fringe fades out.
 */

/** Green excess above this starts to drop alpha. Teal eyes sit under it. */
const KEY_START = 48;
/** Excess at or above this is fully transparent. */
const KEY_END = 120;

/** Output alpha 0–255 for one RGBA pixel. */
export function chromaKeyAlpha(r: number, g: number, b: number, a = 255): number {
  if (a <= 0) return 0;
  const excess = g - Math.max(r, b);
  if (excess <= KEY_START || g < 140) return a;
  const fade = Math.min(1, (excess - KEY_START) / (KEY_END - KEY_START));
  return Math.round(a * (1 - fade));
}

/** Key green to alpha in place. `data` is an RGBA buffer (4 bytes per pixel). */
export function keyChromaPixels(data: Uint8ClampedArray): void {
  for (let i = 0; i < data.length; i += 4) {
    data[i + 3] = chromaKeyAlpha(data[i], data[i + 1], data[i + 2], data[i + 3]);
  }
}
