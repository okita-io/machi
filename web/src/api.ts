const API_BASE = import.meta.env.VITE_API_BASE || "/api";

export type NpcLine = {
  ja: string;
  romaji: string;
  ruby_html: string;
};

export type SessionStart = {
  session_id: string;
  scene: { background: string; guide_sprite: string };
  opening_npc: NpcLine;
  key_phrases: Array<{ ja: string; romaji: string; en: string; kana: string }>;
  hint_rung: number;
};

export async function createSession(scenarioId: string, level = 1): Promise<SessionStart> {
  const r = await fetch(`${API_BASE}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scenario_id: scenarioId, level }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export type TurnResult = {
  learner_text: string;
  learner: NpcLine;
  npc: NpcLine;
  coach: { coach_note_en: string; goal_hits: string[] };
  tts_audio_b64: string;
  completed_goals: string[];
};

export async function sendTurn(sessionId: string, text: string): Promise<TurnResult> {
  const r = await fetch(`${API_BASE}/sessions/${sessionId}/turn`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}