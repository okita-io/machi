/** Per-goal hint ladder. Rungs climb toward less scaffolding and cost stars. */

export const HINT_TIMEOUT_MS = 45_000;

export const MIN_RUNG = 1;
export const MAX_RUNG = 4;

export type HintRung = 1 | 2 | 3 | 4;

export type HintLadderState = {
  level: number;
  goalId: string;
  rungs: Record<string, HintRung>;
  /** Highest rung reached per goal. Sent on each turn for later persistence. */
  hintMax: Record<string, number>;
};

export type HintEvent =
  | { type: "help" | "timeout" | "wrong" }
  | { type: "accepted"; nextGoalId: string };

export type KeyPhrase = { ja: string; kana: string; romaji: string; en: string };

export type GoalLike = { id: string; prompt_en: string; accept?: string[] };

export type HintView = {
  rung: HintRung;
  mode: "en" | "romaji" | "kana" | "goal";
  promptEn: string;
  text: string | null;
  hearText: string | null;
};

export function defaultRungForLevel(level: number): HintRung {
  if (level <= 1) return 1;
  if (level === 2) return 2;
  if (level === 3) return 3;
  return 4;
}

function clampRung(value: number): HintRung {
  if (value <= MIN_RUNG) return 1;
  if (value >= MAX_RUNG) return 4;
  if (value === 2) return 2;
  return 3;
}

function withGoal(state: HintLadderState, goalId: string): HintLadderState {
  if (!goalId) return { ...state, goalId: "" };
  if (state.rungs[goalId] != null) return { ...state, goalId };
  const rung = defaultRungForLevel(state.level);
  return {
    ...state,
    goalId,
    rungs: { ...state.rungs, [goalId]: rung },
    hintMax: { ...state.hintMax, [goalId]: Math.max(state.hintMax[goalId] ?? 0, rung) },
  };
}

function climb(state: HintLadderState): HintLadderState {
  const goalId = state.goalId;
  if (!goalId) return state;
  const current = state.rungs[goalId] ?? defaultRungForLevel(state.level);
  const next = clampRung(current + 1);
  return {
    ...state,
    rungs: { ...state.rungs, [goalId]: next },
    hintMax: { ...state.hintMax, [goalId]: Math.max(state.hintMax[goalId] ?? current, next) },
  };
}

export function createHintLadder(level: number, goalId: string): HintLadderState {
  return withGoal({ level, goalId: "", rungs: {}, hintMax: {} }, goalId);
}

/** Help, a 45s silence, or a wrong move each climb one rung (max 4). */
export function reduceHintLadder(state: HintLadderState, event: HintEvent): HintLadderState {
  if (event.type === "accepted") return withGoal(state, event.nextGoalId);
  return climb(state);
}

export function rungFor(state: HintLadderState): HintRung {
  if (!state.goalId) return defaultRungForLevel(state.level);
  return state.rungs[state.goalId] ?? defaultRungForLevel(state.level);
}

export function climbedAboveDefault(state: HintLadderState): number {
  const base = defaultRungForLevel(state.level);
  let extra = 0;
  for (const rung of Object.values(state.hintMax)) {
    extra = Math.max(extra, Math.max(0, rung - base));
  }
  return extra;
}

/** `success.stars`: 3 at the level default, 2 after one climb, 1 after more. */
export function starsForLadder(
  state: HintLadderState,
  rules?: Record<string, string>,
): { stars: number; rule: string } {
  const extra = climbedAboveDefault(state);
  const ruleFor = (stars: number, fallback: string) => rules?.[String(stars)] || fallback;
  if (extra <= 0) return { stars: 3, rule: ruleFor(3, "no hints above level default") };
  if (extra === 1) return { stars: 2, rule: ruleFor(2, "one rung climbed") };
  return { stars: 1, rule: ruleFor(1, "completed") };
}

export function matchKeyPhrase(goal: GoalLike, phrases: KeyPhrase[]): KeyPhrase | null {
  const accept = goal.accept ?? [];
  for (const phrase of phrases) {
    if (accept.includes(phrase.ja) || accept.includes(phrase.kana)) return phrase;
  }
  return null;
}

export function hintView(goal: GoalLike | null, phrases: KeyPhrase[], rung: HintRung): HintView {
  const phrase = goal ? matchKeyPhrase(goal, phrases) : null;
  const promptEn = goal?.prompt_en ?? "";
  if (rung <= 1) {
    return { rung: 1, mode: "en", promptEn, text: phrase?.en ?? null, hearText: null };
  }
  if (rung === 2) {
    return { rung: 2, mode: "romaji", promptEn, text: phrase?.romaji ?? null, hearText: null };
  }
  if (rung === 3) {
    return {
      rung: 3,
      mode: "kana",
      promptEn,
      text: phrase?.kana ?? null,
      hearText: phrase?.ja || phrase?.kana || null,
    };
  }
  return { rung: 4, mode: "goal", promptEn, text: null, hearText: null };
}

export function nextGoalId(expects: string[] | undefined, completed: string[]): string {
  return (expects ?? []).find((id) => !completed.includes(id)) ?? "";
}
