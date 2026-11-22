import { FormEvent, useCallback, useEffect, useState } from "react";
import { playNpcAudio } from "./audio/playback";
import { useMic } from "./audio/useMic";
import { createSession, sendTurn, type NpcLine, type SessionStart, type TurnResult } from "./api";
import {
  DEFAULT_HINT_LEVEL,
  HINT_LEVELS,
  parseHintLevel,
  romajiRow,
  type HintLevel,
  type SpokenRole,
} from "./hintLevel";
import "./App.css";

function SubtitleLine({
  role,
  label,
  line,
  level,
}: {
  role: SpokenRole;
  label: string;
  line: NpcLine;
  level: number;
}) {
  const romaji = romajiRow({ role, romaji: line.romaji }, level);
  return (
    <div className="subtitle-line" data-role={role}>
      <p className="who">{label}</p>
      <p className="ja" dangerouslySetInnerHTML={{ __html: line.ruby_html || line.ja }} />
      {romaji ? <p className="romaji">{romaji}</p> : null}
    </div>
  );
}

export default function App() {
  const [level, setLevel] = useState<HintLevel>(DEFAULT_HINT_LEVEL);
  const [session, setSession] = useState<SessionStart | null>(null);
  const [npc, setNpc] = useState<NpcLine | null>(null);
  const [learner, setLearner] = useState<NpcLine | null>(null);
  const [coach, setCoach] = useState("");
  const [input, setInput] = useState("ふたりです");
  const [busy, setBusy] = useState(false);
  const [goals, setGoals] = useState<string[]>([]);
  const [handsFree, setHandsFree] = useState(false);

  const applyTurn = useCallback((result: TurnResult) => {
    setLearner(result.learner);
    setNpc(result.npc);
    setCoach(result.coach.coach_note_en);
    setGoals(result.completed_goals);
    playNpcAudio(result.tts_audio_b64);
  }, []);

  const mic = useMic(session?.session_id ?? null, handsFree, applyTurn);

  useEffect(() => {
    let cancel = false;
    void (async () => {
      const s = await createSession("restaurant_ramen_01", level);
      if (cancel) return;
      setSession(s);
      setNpc(s.opening_npc);
      setLearner(null);
      setGoals([]);
      setCoach("");
    })();
    return () => {
      cancel = true;
    };
  }, [level]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!session || busy || mic.sending) return;
    setBusy(true);
    try {
      applyTurn(await sendTurn(session.session_id, input));
    } finally {
      setBusy(false);
    }
  }

  if (!session) {
    return <div className="loading">Loading Machi…</div>;
  }

  return (
    <div className="app">
      <header>
        <h1>Machi</h1>
        <span className="badge">CPU demo</span>
        <label className="level-control">
          Level
          <select
            aria-label="Hint level"
            value={level}
            onChange={(e) => setLevel(parseHintLevel(e.target.value))}
          >
            {HINT_LEVELS.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
      </header>
      <main className="stage" style={{ backgroundImage: `url(${session.scene.background})` }}>
        <img className="guide" src={session.scene.guide_sprite} alt="Sora" />
        {npc && (
          <div className="subtitle">
            {learner && <SubtitleLine role="learner" label="You" line={learner} level={level} />}
            <SubtitleLine role="npc" label="Staff" line={npc} level={level} />
          </div>
        )}
      </main>
      <aside className="coach">
        <h2>Sora · coach</h2>
        <p>{coach || "Try the key phrases below. Type what you would say."}</p>
        <ul>
          {session.key_phrases.map((kp) => (
            <li key={kp.ja}>
              <strong>{kp.en}</strong> — {kp.romaji}
            </li>
          ))}
        </ul>
        <p className="goals">Goals: {goals.length ? goals.join(", ") : "—"}</p>
      </aside>
      <form className="input-bar" onSubmit={onSubmit}>
        <label>
          You say (typed or mock speech)
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={busy || mic.sending || mic.recording}
          />
        </label>
        <div className="mic-controls">
          <button
            type="button"
            className={mic.recording ? "mic-button live" : "mic-button"}
            aria-pressed={mic.recording}
            disabled={!mic.ready || ((busy || mic.sending) && !mic.recording)}
            onPointerDown={(e) => {
              e.preventDefault();
              e.currentTarget.setPointerCapture(e.pointerId);
              mic.holdStart();
            }}
            onPointerUp={(e) => {
              if (e.currentTarget.hasPointerCapture(e.pointerId)) {
                e.currentTarget.releasePointerCapture(e.pointerId);
              }
              mic.holdEnd();
            }}
            onPointerCancel={() => mic.holdEnd()}
          >
            {mic.recording ? "Release to send" : "Hold to talk"}
          </button>
          <label className="mic-check">
            <input
              type="checkbox"
              checked={handsFree}
              onChange={(e) => setHandsFree(e.target.checked)}
            />
            Hands-free
          </label>
          <p className="mic-meta" role="status">
            {mic.error
              ? mic.error
              : mic.recording
                ? `Listening… ${mic.frames} frames`
                : mic.ready
                  ? "16 kHz · push-to-talk"
                  : "Connecting microphone channel…"}
          </p>
        </div>
        <button type="submit" disabled={busy || mic.sending || mic.recording}>
          {busy || mic.sending ? "…" : "Send turn"}
        </button>
      </form>
    </div>
  );
}