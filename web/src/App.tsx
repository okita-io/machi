import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { playNpcAudio } from "./audio/playback";
import { useMic } from "./audio/useMic";
import {
  createSession,
  fetchCoach,
  sendTurn,
  synthesizeSpeech,
  type CoachPayload,
  type NpcLine,
  type SessionStart,
  type TurnResult,
} from "./api";
import { expressionFromCoach, type SoraExpression } from "./coach";
import {
  DEFAULT_HINT_LEVEL,
  HINT_LEVELS,
  parseHintLevel,
  romajiRow,
  type HintLevel,
  type SpokenRole,
} from "./hintLevel";
import {
  HINT_TIMEOUT_MS,
  createHintLadder,
  hintView,
  nextGoalId,
  reduceHintLadder,
  rungFor,
  starsForLadder,
  type HintLadderState,
} from "./hintLadder";
import type { MouthFrame } from "./mouth";
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

function starGlyphs(count: number): string {
  return "★".repeat(count) + "☆".repeat(Math.max(0, 3 - count));
}

export default function App() {
  const [level, setLevel] = useState<HintLevel>(DEFAULT_HINT_LEVEL);
  const [session, setSession] = useState<SessionStart | null>(null);
  const [npc, setNpc] = useState<NpcLine | null>(null);
  const [learner, setLearner] = useState<NpcLine | null>(null);
  const [coach, setCoach] = useState<CoachPayload | null>(null);
  const [coachPending, setCoachPending] = useState(false);
  const [input, setInput] = useState("ふたりです");
  const [busy, setBusy] = useState(false);
  const [goals, setGoals] = useState<string[]>([]);
  const [handsFree, setHandsFree] = useState(false);
  const [ladder, setLadder] = useState<HintLadderState | null>(null);
  const [hintEpoch, setHintEpoch] = useState(0);
  const [mouth, setMouth] = useState<MouthFrame>("closed");
  const [hearing, setHearing] = useState(false);
  const [hintError, setHintError] = useState<string | null>(null);
  const hintMaxRef = useRef<Record<string, number>>({});
  const sessionIdRef = useRef<string | null>(null);

  hintMaxRef.current = ladder?.hintMax ?? {};
  sessionIdRef.current = session?.session_id ?? null;

  const onMouth = useCallback((frame: MouthFrame) => {
    setMouth((prev) => (prev === frame ? prev : frame));
  }, []);

  const applyTurn = useCallback(
    (result: TurnResult) => {
      // Start NPC audio before coach state. A pending note must not delay playback.
      if (result.tts_audio_b64) playNpcAudio(result.tts_audio_b64, onMouth);
      setLearner(result.learner);
      setNpc(result.npc);
      setGoals(result.completed_goals);
      setHintEpoch((n) => n + 1);
      setLadder((prev) => {
        if (!prev) return prev;
        const completed = result.completed_goals ?? [];
        const goalId = nextGoalId(result.node_expects, completed);
        const accepted = result.accepted ?? (result.goal_hits?.length ?? 0) > 0;
        if (accepted) return reduceHintLadder(prev, { type: "accepted", nextGoalId: goalId });
        return reduceHintLadder(prev, { type: "wrong" });
      });
      if (result.coach_pending) {
        setCoachPending(true);
      } else {
        setCoachPending(false);
        setCoach(result.coach);
      }
    },
    [onMouth],
  );

  const mic = useMic(session?.session_id ?? null, handsFree, applyTurn, hintMaxRef);

  useEffect(() => {
    let cancel = false;
    void (async () => {
      const s = await createSession("restaurant_ramen_01", level);
      if (cancel) return;
      setSession(s);
      setNpc(s.opening_npc);
      setLearner(null);
      setGoals([]);
      setCoach(null);
      setCoachPending(false);
      setMouth("closed");
      setLadder(createHintLadder(level, s.node_expects?.[0] ?? ""));
      setHintEpoch(0);
    })();
    return () => {
      cancel = true;
    };
  }, [level]);

  const rung = ladder ? rungFor(ladder) : 1;
  const goalId = ladder?.goalId ?? "";

  useEffect(() => {
    if (!goalId) return;
    const timer = window.setTimeout(() => {
      setLadder((prev) => (prev ? reduceHintLadder(prev, { type: "timeout" }) : prev));
    }, HINT_TIMEOUT_MS);
    return () => window.clearTimeout(timer);
  }, [goalId, rung, hintEpoch]);

  useEffect(() => {
    if (!coachPending) return;
    const sessionId = sessionIdRef.current;
    if (!sessionId) return;
    let cancel = false;
    const tick = async () => {
      try {
        const body = await fetchCoach(sessionId);
        if (cancel || body.pending) return;
        if (body.coach) {
          setCoach(body.coach);
          setCoachPending(false);
        }
      } catch {
        // Keep polling. NPC audio is already playing.
      }
    };
    const id = window.setInterval(() => void tick(), 400);
    void tick();
    return () => {
      cancel = true;
      window.clearInterval(id);
    };
  }, [coachPending]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!session || busy || mic.sending) return;
    setBusy(true);
    try {
      applyTurn(await sendTurn(session.session_id, input, hintMaxRef.current));
    } finally {
      setBusy(false);
    }
  }

  function onHelp() {
    setLadder((prev) => (prev ? reduceHintLadder(prev, { type: "help" }) : prev));
    setHintEpoch((n) => n + 1);
  }

  async function onHear(text: string) {
    setHearing(true);
    setHintError(null);
    try {
      const wav = await synthesizeSpeech(text);
      playNpcAudio(wav, onMouth);
    } catch {
      setHintError("Couldn't play that line.");
    } finally {
      setHearing(false);
    }
  }

  if (!session || !ladder) {
    return <div className="loading">Loading Machi…</div>;
  }

  const goal = session.goals.find((item) => item.id === goalId) ?? null;
  const view = hintView(goal, session.key_phrases, rung);
  const stars = starsForLadder(ladder, session.stars);
  const expression: SoraExpression = coachPending
    ? "think"
    : coach
      ? expressionFromCoach(coach)
      : "happy";

  return (
    <div className="app">
      <header>
        <h1>Machi</h1>
        <span className="badge">CPU demo</span>
        <span className="stars" title={stars.rule}>
          {starGlyphs(stars.stars)}
        </span>
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
        <div className="guide-slot">
          <img
            className="guide"
            src={session.scene.guide_sprite}
            alt="Sora"
            data-expression={expression}
          />
          <span className={`mouth ${mouth}`} data-mouth={mouth} aria-hidden="true" />
          <span className="expression" data-expression={expression}>
            {expression}
          </span>
        </div>
        <div className="hint-card">
          <p className="hint-kicker">
            {goal ? `Goal · rung ${view.rung}` : "Listen"}
          </p>
          {view.mode === "goal" || !view.text ? (
            <p className="hint-prompt">{view.promptEn || "Follow the staff."}</p>
          ) : (
            <>
              <p className="hint-prompt">{view.promptEn}</p>
              <p className="hint-line">{view.text}</p>
            </>
          )}
          <div className="hint-actions">
            {view.hearText ? (
              <button type="button" disabled={hearing} onClick={() => void onHear(view.hearText!)}>
                {hearing ? "…" : "Hear it"}
              </button>
            ) : null}
            <button type="button" onClick={onHelp} disabled={!goalId || rung >= 4}>
              Help
            </button>
          </div>
          {hintError ? <p className="hint-error">{hintError}</p> : null}
        </div>
        {npc && (
          <div className="subtitle">
            {learner && <SubtitleLine role="learner" label="You" line={learner} level={level} />}
            <SubtitleLine role="npc" label="Staff" line={npc} level={level} />
          </div>
        )}
      </main>
      <aside className="coach" aria-live="polite">
        <h2>Sora · coach</h2>
        <p className="expression-id" data-expression={expression}>
          {expression}
        </p>
        <p>
          {coachPending
            ? "Sora is writing a note — the line already started."
            : coach?.coach_note_en || "Try the key phrases below. Type what you would say."}
        </p>
        {coach?.correction ? (
          <p className="correction">
            Try: <strong>{coach.correction}</strong>
          </p>
        ) : null}
        {coach?.goal_hits?.length ? (
          <p className="goals">Hits: {coach.goal_hits.join(", ")}</p>
        ) : null}
        {typeof coach?.hint_rung === "number" ? (
          <p className="goals">Tutor rung: {coach.hint_rung}</p>
        ) : null}
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
