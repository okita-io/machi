/** Sora's seven plates: resting face plus the six coach moods. */

export const SORA_EXPRESSIONS = [
  "neutral",
  "happy",
  "think",
  "cheer",
  "surprised",
  "sorry",
  "point",
] as const;

export type SoraExpression = (typeof SORA_EXPRESSIONS)[number];

/** Moods the tutor may set. Neutral is the resting plate. */
export const SORA_COACH_EXPRESSIONS = [
  "happy",
  "think",
  "cheer",
  "surprised",
  "sorry",
  "point",
] as const satisfies readonly SoraExpression[];

export type SoraCoachExpression = (typeof SORA_COACH_EXPRESSIONS)[number];

const EXPRESSION_NAMES = new Set<string>(SORA_EXPRESSIONS);

export function isSoraExpression(value: string): value is SoraExpression {
  return EXPRESSION_NAMES.has(value);
}

/**
 * Swap the file on a guide sprite URL (`.../sprites/sora/neutral.webp`).
 * Unknown expressions fall back to the resting face.
 */
export function soraSpriteUrl(guideSprite: string, expression: string): string {
  const name = EXPRESSION_NAMES.has(expression) ? expression : "neutral";
  const file = `${name}.webp`;
  if (/\/sprites\/sora\/[^/?#]+$/.test(guideSprite)) {
    return guideSprite.replace(/\/[^/?#]+$/, `/${file}`);
  }
  const trimmed = guideSprite.replace(/\/$/, "");
  const slash = trimmed.lastIndexOf("/");
  const root = slash >= 0 ? trimmed.slice(0, slash) : "";
  return `${root}/sora/${file}`;
}

/** When a plate 404s, use neutral. A missing neutral stays put so the UI does not loop. */
export function spriteSrcOnMissing(src: string): string {
  const path = src.split(/[?#]/, 1)[0] ?? src;
  if (path.endsWith("/neutral.webp")) return src;
  return src.replace(/\/[^/?#]+$/, "/neutral.webp");
}
