import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { useMic } from "./audio/useMic";
import { createSession, sendTurn, type NpcLine, type SessionStart, type TurnResult } from "./api";
import "./App.css";

function NpcSubtitle({ line }: { line: NpcLine }) {
  return (
    <div className="subtitle">
      <p className="ja" dangerouslySetInnerHTML={{ __html: line.ruby_html || line.ja }} />
      <p className="romaji">{line.romaji}</p>
    </div>
  );
}

export default function App() {
  const [session, setSession] = useState<SessionStart | null>(null);
  const [npc, setNpc] = useState<NpcLine | null>(null);
  const [coach, setCoach] = useState("");
  const [input, setInput] = useState("ふたりです");
  const [busy, setBusy] = useState(false);
  const [goals, setGoals] = useState<string[]>([]);
  const [handsFree, setHandsFree] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const playTts = useCallback((b64: string) => {
    const src = `data:audio/wav;base64,${b64}`;
    if (!audioRef.current) {
      audioRef.current = new Audio(src);
    } else {
      audioRef.current.src = src;
    }
    void audioRef.current.play();
  }, []);

  const applyTurn = useCallback(
    (result: TurnResult) => {
      setNpc(result.npc);
      setCoach(result.coach.coach_note_en);
      setGoals(result.completed_goals);
      playTts(result.tts_audio_b64);
    },
    [playTts],
  );

  const mic = useMic(session?.session_id ?? null, handsFree, applyTurn);

  useEffect(() => {
    void (async () => {
      const s = await createSession("restaurant_ramen_01", 1);
      setSession(s);
      setNpc(s.opening_npc);
    })();
  }, []);

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
      </header>
      <main className="stage" style={{ backgroundImage: `url(${session.scene.background})` }}>
        <img className="guide" src={session.scene.guide_sprite} alt="Sora" />
        {npc && <NpcSubtitle line={npc} />}
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