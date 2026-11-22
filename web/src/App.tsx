import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { createSession, sendTurn, type NpcLine, type SessionStart } from "./api";
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

  useEffect(() => {
    void (async () => {
      const s = await createSession("restaurant_ramen_01", 1);
      setSession(s);
      setNpc(s.opening_npc);
    })();
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!session || busy) return;
    setBusy(true);
    try {
      const result = await sendTurn(session.session_id, input);
      setNpc(result.npc);
      setCoach(result.coach.coach_note_en);
      setGoals(result.completed_goals);
      playTts(result.tts_audio_b64);
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
          <input value={input} onChange={(e) => setInput(e.target.value)} disabled={busy} />
        </label>
        <button type="submit" disabled={busy}>
          {busy ? "…" : "Send turn"}
        </button>
      </form>
    </div>
  );
}