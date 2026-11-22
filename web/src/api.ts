import type { PitchAdvisory } from "./pitchAdvisory";

const API_BASE = import.meta.env.VITE_API_BASE || "/api";

export type NpcLine = {
  ja: string;
  romaji: string;
  ruby_html: string;
};

export type KeyPhrase = { ja: string; romaji: string; en: string; kana: string };

export type GoalCard = {
  id: string;
  prompt_en: string;
  accept: string[];
  optional?: boolean;
};

export type SessionStart = {
  session_id: string;
  scene: { background: string; guide_sprite: string };
  opening_npc: NpcLine;
  key_phrases: KeyPhrase[];
  goals: GoalCard[];
  stars: Record<string, string>;
  node_expects: string[];
  node_id: string;
  hint_rung: number;
  phase?: "briefing" | "warmup" | "roleplay" | "debrief";
  title_en?: string;
  required_goals?: string[];
  briefing_en?: string;
};

export type CorrectionCard = {
  en: string;
  ja: string;
  romaji: string;
  ruby_html: string;
  weight?: number;
};

export type ScenarioSummary = {
  id: string;
  title_en: string;
  title_ja: string;
  scene: { background: string; sprite: string };
};

export async function listScenarios(): Promise<ScenarioSummary[]> {
  const r = await fetch(`${API_BASE}/scenarios`);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function createSession(scenarioId: string, level = 1): Promise<SessionStart> {
  const r = await fetch(`${API_BASE}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scenario_id: scenarioId, level }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export type CoachPayload = {
  coach_note_en: string;
  goal_hits: string[];
  correction?: string | null;
  hint_rung?: number;
  sentiment?: string;
  coach_note_sentiment?: string;
  sora_expression?: string;
  understandable?: boolean;
  pronunciation_tip_en?: string | null;
  pitch_advisory?: PitchAdvisory | null;
};

export type TurnResult = {
  learner_text: string;
  learner: NpcLine;
  npc: NpcLine;
  coach: CoachPayload;
  coach_pending?: boolean;
  tts_audio_b64: string;
  completed_goals: string[];
  goal_hits?: string[];
  accepted?: boolean;
  node_expects?: string[];
  hint_max?: Record<string, number>;
  type?: string;
  turn_type?: string;
  phase?: "briefing" | "warmup" | "roleplay" | "debrief";
  reset?: boolean;
  stars?: number;
  goals_completed?: string[];
  corrections?: CorrectionCard[];
  complete?: boolean;
  pitch_advisory?: PitchAdvisory | null;
  warmup_index?: number;
  warmup_total?: number;
  warmup_passed?: boolean | null;
  warmup_complete?: boolean;
  phrase?: KeyPhrase | null;
  next_phrase?: KeyPhrase | null;
  node_id?: string;
};

export async function sendTurn(
  sessionId: string,
  text: string,
  hintMax: Record<string, number> = {},
  options?: { skipWarmup?: boolean; advance?: "warmup" | "briefing" | "replay" },
): Promise<TurnResult> {
  const r = await fetch(`${API_BASE}/sessions/${sessionId}/turn`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      text,
      hint_max: hintMax,
      ...(options?.skipWarmup ? { skip_warmup: true } : {}),
      ...(options?.advance ? { advance: options.advance } : {}),
    }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

/** Tap-to-hear. Posts to the orchestrator's TTS stub and returns WAV base64. */
export async function synthesizeSpeech(text: string, voice = "guide"): Promise<string> {
  const r = await fetch(`${API_BASE}/v1/synthesize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, voice }),
  });
  if (!r.ok) throw new Error(await r.text());
  const body = (await r.json()) as { audio_b64?: string };
  if (!body.audio_b64) throw new Error("tts_empty");
  return body.audio_b64;
}

/** Idempotent. Completing a visit already enrolls the same corrections. */
export async function enrollReviews(sessionId: string): Promise<{ added: number }> {
  const r = await fetch(`${API_BASE}/sessions/${sessionId}/reviews`, { method: "POST" });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function fetchCoach(
  sessionId: string,
): Promise<{ pending: boolean; coach?: CoachPayload | null }> {
  const r = await fetch(`${API_BASE}/sessions/${sessionId}/coach`);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}