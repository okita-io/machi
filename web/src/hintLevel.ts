/** Hint level for subtitle rows. Level 2+ shows romaji (spec: Survivor and above). */

export const HINT_LEVELS = [1, 2, 3, 4] as const;

export type HintLevel = (typeof HINT_LEVELS)[number];

export const DEFAULT_HINT_LEVEL: HintLevel = 2;

export type SpokenRole = "npc" | "learner";

export function parseHintLevel(value: string): HintLevel {
  const n = Number(value);
  if (n === 1 || n === 2 || n === 3 || n === 4) return n;
  return DEFAULT_HINT_LEVEL;
}

export type SpokenLine = {
  role: SpokenRole;
  romaji: string;
};

/** Romaji row for NPC and learner lines when the hint level is 2 or higher. */
export function showRomaji(level: number): boolean {
  return level >= 2;
}

export function romajiRow(line: SpokenLine, level: number): string | null {
  if (line.role !== "npc" && line.role !== "learner") return null;
  if (!showRomaji(level) || line.romaji.length === 0) return null;
  return line.romaji;
}
