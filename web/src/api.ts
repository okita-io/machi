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
  reviews_line?: string;
  review_phrases?: KeyPhrase[];
  warmup_total?: number;
};

export type ReviewCard = {
  card_id: number;
  ja: string;
  en: string;
  romaji: string;
  kana_ruby: string;
  srs_tags: string[];
};

export type ReviewGrade = "again" | "hard" | "good" | "easy";

export type ReviewLast = {
  card_id: number;
  utterance: string;
  match: ReviewGrade;
  rating: ReviewGrade;
  phrase_ja: string;
  reps: number;
  due_at: string;
};

export type ReviewSummary = {
  cards_reviewed: number;
  next_due: {
    card_id: number;
    due_at: string;
    rating: string;
    phrase_ja: string;
    reps: number;
  }[];
};

export type ReviewSessionView = {
  review_id: string;
  budget_s: number;
  index: number;
  card_total: number;
  complete: boolean;
  situation: string;
  situation_tag: string;
  card: ReviewCard | null;
  last: ReviewLast | null;
  summary: ReviewSummary | null;
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

export type ScenarioIssue = {
  path: string;
  message: string;
  line: number | null;
};

export async function fetchScenarioYaml(id: string): Promise<string> {
  const r = await fetch(`${API_BASE}/scenarios/${encodeURIComponent(id)}/raw`);
  if (!r.ok) throw new Error(await r.text());
  const body = (await r.json()) as { yaml?: string };
  if (typeof body.yaml !== "string") throw new Error("empty scenario");
  return body.yaml;
}

export async function validateScenario(
  yaml: string,
): Promise<{ ok: boolean; id?: string; errors: ScenarioIssue[] }> {
  const r = await fetch(`${API_BASE}/scenarios/validate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ yaml }),
  });
  const body = (await r.json()) as { ok?: boolean; id?: string; errors?: ScenarioIssue[] };
  if (r.status !== 200 && r.status !== 422) throw new Error(JSON.stringify(body));
  return {
    ok: Boolean(body.ok),
    id: body.id,
    errors: (body.errors ?? []).map((err) => ({
      path: err.path,
      message: err.message,
      line: err.line ?? null,
    })),
  };
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
  coach_audio_b64?: string;
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

export type InterpretedWord = {
  heard: string;
  intended: string;
};

export type TurnActivity = {
  state: "idle" | "received" | "transcribing" | "thinking" | "speaking" | "scoring" | "done" | "error";
  detail: string;
  heard: string;
  audio_bytes: number;
  audio_ms: number;
  intended_ja?: string;
  intended_kana?: string;
  intended_romaji?: string;
  instead?: InterpretedWord[];
  interpreted?: string;
  pronounce?: string;
  matched?: boolean;
};

export async function fetchTurnActivity(sessionId: string): Promise<TurnActivity> {
  const r = await fetch(`${API_BASE}/sessions/${sessionId}/activity`);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

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

/** Push-to-talk clip. No `text`, so the server transcribes this PCM. */
export async function sendAudioTurn(
  sessionId: string,
  audioB64: string,
  hintMax: Record<string, number> = {},
): Promise<TurnResult> {
  const r = await fetch(`${API_BASE}/sessions/${sessionId}/turn`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ audio_b64: audioB64, hint_max: hintMax }),
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

export async function startReviewSession(): Promise<ReviewSessionView> {
  const r = await fetch(`${API_BASE}/review/sessions`, { method: "POST" });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function answerReview(
  reviewId: string,
  body: { text?: string; audio_b64?: string; self_rating?: ReviewGrade },
): Promise<ReviewSessionView> {
  const r = await fetch(`${API_BASE}/review/sessions/${reviewId}/answer`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
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