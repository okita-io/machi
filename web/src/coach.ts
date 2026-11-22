import { type SoraCoachExpression } from "./soraExpressions.ts";

/** Sora's out-of-role expression, driven by the tutor payload. */

export type SoraExpression = SoraCoachExpression;

const SENTIMENT: Record<string, SoraExpression> = {
  happy: "happy",
  positive: "happy",
  glad: "happy",
  cheer: "cheer",
  celebrate: "cheer",
  success: "cheer",
  think: "think",
  thinking: "think",
  encourage: "think",
  neutral: "think",
  surprised: "surprised",
  surprise: "surprised",
  sorry: "sorry",
  negative: "sorry",
  apologetic: "sorry",
  point: "point",
  correction: "point",
  correct: "point",
};

export type CoachFields = {
  sora_expression?: string;
  sentiment?: string;
  coach_note_sentiment?: string;
  correction?: string | null;
  goal_hits?: string[];
  understandable?: boolean;
};

export function expressionFromCoach(coach: CoachFields): SoraExpression {
  if (coach.sora_expression && coach.sora_expression in SENTIMENT) {
    return coach.sora_expression as SoraExpression;
  }
  const sentiment = coach.sentiment || coach.coach_note_sentiment;
  if (sentiment && SENTIMENT[sentiment]) return SENTIMENT[sentiment];
  if (coach.correction) return "point";
  if (coach.goal_hits && coach.goal_hits.length > 0) return "cheer";
  if (coach.understandable === false) return "sorry";
  return "think";
}
