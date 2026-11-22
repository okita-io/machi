/** Briefing, warm-up, and debrief view models. The server owns phase. */

export type Phase = "briefing" | "warmup" | "roleplay" | "debrief";

export type GoalLike = { id: string; prompt_en: string; optional?: boolean };

export type GoalStatus = {
  id: string;
  promptEn: string;
  done: boolean;
  required: boolean;
};

export type CorrectionLike = { en?: string; ja?: string };

export function turnKind(result: { type?: string; turn_type?: string }): string {
  if (result.turn_type) return result.turn_type;
  if (result.type && result.type !== "turn_result") return result.type;
  return "turn";
}

/** Required goals from `success.required` decide whether the visit is complete. */
export function goalChecklist(
  goals: GoalLike[],
  required: string[],
  completed: string[],
): GoalStatus[] {
  const requiredIds = new Set(required);
  const done = new Set(completed);
  return goals.map((goal) => ({
    id: goal.id,
    promptEn: goal.prompt_en,
    done: done.has(goal.id),
    required: requiredIds.has(goal.id),
  }));
}

export function requiredComplete(required: string[], completed: string[]): boolean {
  return required.length > 0 && required.every((id) => completed.includes(id));
}

/** Debrief keeps the latest two tutor corrections. */
export function bestCorrections<T extends CorrectionLike>(items: T[]): T[] {
  return items.filter((item) => (item.en || item.ja || "").trim()).slice(-2);
}

/**
 * One attempt per phrase, then role-play. A miss still advances: there is no fail state.
 */
export function warmupStep(
  index: number,
  total: number,
  passed: boolean,
): { passed: boolean; failed: false; complete: boolean; nextIndex: number } {
  const nextIndex = Math.min(index + 1, total);
  return { passed, failed: false, complete: nextIndex >= total, nextIndex };
}
