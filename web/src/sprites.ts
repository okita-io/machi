/** Expression plates baked next to the resting sprite. */
export const SORA_SPRITE_FILES = [
  "neutral",
  "happy",
  "think",
  "cheer",
  "surprised",
  "sorry",
  "point",
] as const;

export type SoraSpriteName = (typeof SORA_SPRITE_FILES)[number];

const SPRITE_NAMES = new Set<string>(SORA_SPRITE_FILES);

/**
 * Swap the file on a guide sprite URL (`.../sprites/sora/neutral.webp`).
 * Unknown expressions fall back to the resting face.
 */
export function soraSpriteUrl(guideSprite: string, expression: string): string {
  const name = SPRITE_NAMES.has(expression) ? expression : "neutral";
  const file = `${name}.webp`;
  if (/\/sprites\/sora\/[^/?#]+$/.test(guideSprite)) {
    return guideSprite.replace(/\/[^/?#]+$/, `/${file}`);
  }
  const trimmed = guideSprite.replace(/\/$/, "");
  const slash = trimmed.lastIndexOf("/");
  const root = slash >= 0 ? trimmed.slice(0, slash) : "";
  return `${root}/sora/${file}`;
}
