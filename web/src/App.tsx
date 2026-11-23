import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { formatMicDebug } from "./audio/micDebug";
import { playNpcAudio, playSpeech, replyClips, type SpeechClip, type SpeechPart } from "./audio/playback";
import { useMic } from "./audio/useMic";
import {
  answerReview,
  createSession,
  enrollReviews,
  fetchCoach,
  fetchTurnActivity,
  listScenarios,
  sendAudioTurn,
  sendTurn,
  startReviewSession,
  synthesizeSpeech,
  type CoachPayload,
  type KeyPhrase,
  type NpcLine,
  type ReviewSessionView,
  type ScenarioSummary,
  type SessionStart,
  type TurnActivity,
  type TurnResult,
} from "./api";
import { expressionFromCoach } from "./coach";
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
import { bestCorrections, goalChecklist, turnKind, type Phase } from "./flow";
import { KeyedSprite } from "./KeyedSprite";
import type { MouthFrame } from "./mouth";
import { BriefingScreen, DebriefScreen, WarmupScreen } from "./phases";
import { ReviewPanel } from "./review";
import { advisoryLine, type PitchAdvisory } from "./pitchAdvisory";
import { type SoraExpression, soraSpriteUrl } from "./soraExpressions";
import { townMapUrl } from "./townMap";
import { EditorView } from "./EditorView";
import { TownView } from "./TownView";
import { useViewport } from "./useViewport";
import "./App.css";

type AppRoute = "town" | "play" | "editor";

function routeFromHash(): AppRoute {
  if (window.location.hash === "#/town") return "town";
  if (window.location.hash === "#/editor") return "editor";
  return "play";
}

function useHashRoute(): AppRoute {
  const [route, setRoute] = useState<AppRoute>(routeFromHash);
  useEffect(() => {
    const onHash = () => setRoute(routeFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  return route;
}

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

function keepFreshReading(current: TurnActivity | null, incoming: TurnActivity): TurnActivity {
  if (
    current?.state === "done" &&
    current.interpreted &&
    incoming.state !== "done" &&
    incoming.state !== "error"
  ) {
    return current;
  }
  return incoming;
}

function micButtonLabel(
  recording: boolean,
  sending: boolean,
  activity: TurnActivity | null,
): string {
  if (recording) return "Release to send";
  if (!sending) return "Hold to speak";
  switch (activity?.state) {
    case "transcribing":
      return "Transcribing…";
    case "thinking":
      return "Choosing a reply…";
    case "speaking":
      return "Speaking…";
    case "scoring":
      return "Checking the phrase…";
    case "done":
      return "Heard";
    default:
      return "Sending…";
  }
}

function starGlyphs(count: number): string {
  return "★".repeat(count) + "☆".repeat(Math.max(0, 3 - count));
}

function appClass(town: boolean, phone: boolean): string {
  const parts = ["app"];
  if (town) parts.push("town-mode");
  if (phone) parts.push("phone");
  return parts.join(" ");
}

export default function App() {
  const route = useHashRoute();
  const { phone } = useViewport();
  const [level, setLevel] = useState<HintLevel>(DEFAULT_HINT_LEVEL);
  const [scenarioId, setScenarioId] = useState("restaurant_ramen_01");
  const [catalog, setCatalog] = useState<ScenarioSummary[] | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [session, setSession] = useState<SessionStart | null>(null);
  const [npc, setNpc] = useState<NpcLine | null>(null);
  const [learner, setLearner] = useState<NpcLine | null>(null);
  const [coach, setCoach] = useState<CoachPayload | null>(null);
  const [coachPending, setCoachPending] = useState(false);
  const [input, setInput] = useState("ふたりです");
  const [busy, setBusy] = useState(false);
  const [goals, setGoals] = useState<string[]>([]);
  const [handsFree, setHandsFree] = useState(false);
  const [activity, setActivity] = useState<TurnActivity | null>(null);
  const [sessionEpoch, setSessionEpoch] = useState(0);
  const [replyAudio, setReplyAudio] = useState<SpeechClip[] | null>(null);
  const [readingPart, setReadingPart] = useState<SpeechPart | null>(null);
  const [repeating, setRepeating] = useState(false);
  const [ladder, setLadder] = useState<HintLadderState | null>(null);
  const [hintEpoch, setHintEpoch] = useState(0);
  const [mouth, setMouth] = useState<MouthFrame>("closed");
  const [hearing, setHearing] = useState(false);
  const [hintError, setHintError] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>("briefing");
  const [warmupPhrase, setWarmupPhrase] = useState<KeyPhrase | null>(null);
  const [warmupIndex, setWarmupIndex] = useState(0);
  const [debrief, setDebrief] = useState<TurnResult | null>(null);
  const [reviewsNote, setReviewsNote] = useState<string | null>(null);
  const [warmupTotal, setWarmupTotal] = useState(0);
  const [review, setReview] = useState<ReviewSessionView | null>(null);
  const [reviewInput, setReviewInput] = useState("");
  const [reviewBusy, setReviewBusy] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [pitchAdvisory, setPitchAdvisory] = useState<PitchAdvisory | null>(null);
  const reviewIdRef = useRef<string | null>(null);
  const hintMaxRef = useRef<Record<string, number>>({});
  const sessionIdRef = useRef<string | null>(null);
  const recoveringRef = useRef(false);
  const expectBytesRef = useRef(0);

  hintMaxRef.current = ladder?.hintMax ?? {};
  sessionIdRef.current = session?.session_id ?? null;
  reviewIdRef.current = review && !review.complete ? review.review_id : null;

  const onMouth = useCallback((frame: MouthFrame) => {
    setMouth((prev) => (prev === frame ? prev : frame));
  }, []);

  const applyTurn = useCallback(
    (result: TurnResult) => {
      const kind = turnKind(result);
      // Start audio before coach state. A pending note must not delay playback.
      // The shop line plays first. Sora then says what was heard, then the correction.
      const clips =
        kind === "warmup"
          ? replyClips({
              heard: result.tts_audio_b64,
              pronounce: result.pronounce_audio_b64,
            })
          : replyClips({
              shop: result.tts_audio_b64,
              heard: result.coach_audio_b64,
              pronounce: result.pronounce_audio_b64,
            });
      if (clips.length) playSpeech(clips, onMouth, setReadingPart);
      const coaching = clips.filter((clip) => clip.part !== "shop");
      setReplyAudio(coaching.length ? coaching : null);
      const info = result.interpretation;
      if (info && !result.reset) {
        setActivity((prev) => ({
          state: "done",
          detail: info.detail,
          heard: info.heard,
          audio_bytes: prev?.audio_bytes ?? 0,
          audio_ms: prev?.audio_ms ?? 0,
          intended_ja: info.intended_ja,
          intended_kana: info.intended_kana,
          intended_romaji: info.intended_romaji,
          instead: info.instead,
          interpreted: info.interpreted,
          pronounce: info.pronounce,
          spoken_interpreted: info.spoken_interpreted,
          spoken_pronounce: info.spoken_pronounce,
          matched: info.matched,
        }));
      }
      if (result.learner_text) setLearner(result.learner);
      if (result.npc?.ja) setNpc(result.npc);
      if (result.reset) {
        setGoals([]);
        setPitchAdvisory(null);
        setDebrief(null);
        setReviewsNote(null);
        setWarmupPhrase(null);
        setWarmupIndex(0);
        setCoach(null);
        setCoachPending(false);
        setReplyAudio(null);
        setMouth("closed");
        setHintEpoch(0);
        setLadder((prev) =>
          createHintLadder(prev?.level ?? DEFAULT_HINT_LEVEL, result.node_expects?.[0] ?? ""),
        );
        setPhase(kind === "briefing" ? "briefing" : "roleplay");
        if (kind !== "briefing") setInput("ふたりです");
        return;
      }
      if (result.pitch_advisory?.is_advisory) {
        setPitchAdvisory(result.pitch_advisory);
      }
      if (kind === "warmup") {
        const done = Boolean(result.warmup_complete) || result.phase === "roleplay";
        setPhase(done ? "roleplay" : "warmup");
        setWarmupPhrase(done ? null : result.next_phrase ?? result.phrase ?? null);
        setWarmupIndex(result.warmup_index ?? 0);
        if (typeof result.warmup_total === "number") setWarmupTotal(result.warmup_total);
        setCoachPending(false);
        setCoach(result.coach);
        if (done) setInput("ふたりです");
        else setInput("");
        return;
      }
      if (kind === "debrief") {
        setPhase("debrief");
        setDebrief(result);
        setGoals(result.completed_goals);
        setCoachPending(false);
        setCoach(result.coach);
        return;
      }
      setPhase("roleplay");
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

  const onSessionLost = useCallback(() => {
    if (recoveringRef.current) return;
    recoveringRef.current = true;
    setSessionEpoch((n) => n + 1);
  }, []);

  const onClipStart = useCallback((bytes?: number) => {
    expectBytesRef.current = bytes && bytes > 0 ? bytes : 0;
    setActivity({
      state: "received",
      detail:
        bytes && bytes > 0
          ? `Sending ${bytes} bytes. Waiting for this clip to be transcribed.`
          : "Recording a new clip. Release to transcribe it.",
      heard: "",
      audio_bytes: bytes ?? 0,
      audio_ms: 0,
      interpreted: "",
      pronounce: "",
    });
    setReadingPart(null);
  }, []);

  const onAudioFallback = useCallback(
    async (audioB64: string) => {
      const id = sessionIdRef.current;
      if (!id) throw new Error("No session");
      try {
        applyTurn(await sendAudioTurn(id, audioB64, hintMaxRef.current));
      } catch (err) {
        const message = err instanceof Error ? err.message : "";
        if (/not found|404/i.test(message)) {
          onSessionLost();
          throw new Error("The session ended before this clip could be transcribed.");
        }
        throw err;
      }
    },
    [applyTurn, onSessionLost],
  );

  const reviewActive = route === "town" && review !== null && !review.complete;
  const onReviewAudio = useCallback(async (audioB64: string) => {
    const id = reviewIdRef.current;
    if (!id) return;
    setReviewBusy(true);
    setReviewError(null);
    try {
      setReview(await answerReview(id, audioB64 ? { audio_b64: audioB64 } : { text: "" }));
      setReviewInput("");
    } catch {
      setReviewError("Couldn't score that.");
    } finally {
      setReviewBusy(false);
    }
  }, []);
  const mic = useMic(
    session?.session_id ?? null,
    handsFree,
    applyTurn,
    hintMaxRef,
    reviewActive,
    onReviewAudio,
    onSessionLost,
    onClipStart,
    onAudioFallback,
  );

  useEffect(() => {
    const sessionId = session?.session_id;
    if (!sessionId || !mic.sending) return;
    let ignore = false;
    const tick = async () => {
      try {
        const body = await fetchTurnActivity(sessionId);
        if (ignore) return;
        const expect = expectBytesRef.current;
        // A finished status from the previous clip is not this recording.
        if (expect > 0 && body.audio_bytes !== expect && body.state === "done") return;
        if (expect > 0 && body.audio_bytes === expect) expectBytesRef.current = 0;
        setActivity((current) => keepFreshReading(current, body));
      } catch {
        // Keep the last status. The next poll retries.
      }
    };
    void tick();
    const handle = window.setInterval(() => void tick(), 1000);
    return () => {
      ignore = true;
      window.clearInterval(handle);
      void fetchTurnActivity(sessionId)
        .then((body) => {
          const expect = expectBytesRef.current;
          if (expect > 0 && body.audio_bytes !== expect && body.state === "done") return;
          if (expect > 0 && body.audio_bytes === expect) expectBytesRef.current = 0;
          setActivity((current) => keepFreshReading(current, body));
        })
        .catch(() => undefined);
    };
  }, [session?.session_id, mic.sending]);

  useEffect(() => {
    let cancel = false;
    void (async () => {
      const s = await createSession(scenarioId, level);
      if (cancel) return;
      setSession(s);
      setNpc(s.opening_npc);
      setLearner(null);
      setGoals([]);
      setCoach(null);
      setCoachPending(false);
      setMouth("closed");
      setPhase(s.phase ?? "briefing");
      setWarmupPhrase(null);
      setWarmupIndex(0);
      setWarmupTotal(s.warmup_total ?? s.key_phrases.length);
      setDebrief(null);
      setReviewsNote(null);
      setPitchAdvisory(null);
      setLadder(createHintLadder(level, s.node_expects?.[0] ?? ""));
      setHintEpoch(0);
      recoveringRef.current = false;
      if (sessionEpoch > 0) {
        setActivity({
          state: "error",
          detail:
            "The previous session ended on the server, so that recording was not transcribed. This is a new session. Hold to speak again.",
          heard: "",
          audio_bytes: 0,
          audio_ms: 0,
          interpreted: "",
          pronounce: "",
        });
      }
    })();
    return () => {
      cancel = true;
    };
  }, [level, scenarioId, sessionEpoch]);

  useEffect(() => {
    if (route !== "town") return;
    let cancel = false;
    void (async () => {
      try {
        const rows = await listScenarios();
        if (!cancel) {
          setCatalog(rows);
          setCatalogError(null);
        }
      } catch {
        if (!cancel) setCatalogError("Couldn't load the town.");
      }
    })();
    return () => {
      cancel = true;
    };
  }, [route]);

  const rung = ladder ? rungFor(ladder) : 1;
  const goalId = ladder?.goalId ?? "";

  useEffect(() => {
    if (phase !== "roleplay" || !goalId) return;
    const timer = window.setTimeout(() => {
      setLadder((prev) => (prev ? reduceHintLadder(prev, { type: "timeout" }) : prev));
    }, HINT_TIMEOUT_MS);
    return () => window.clearTimeout(timer);
  }, [goalId, rung, hintEpoch, phase]);

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
    if (phase !== "roleplay" && phase !== "warmup") return;
    setBusy(true);
    try {
      applyTurn(await sendTurn(session.session_id, input, hintMaxRef.current));
    } finally {
      setBusy(false);
    }
  }

  async function startReview() {
    setReviewBusy(true);
    setReviewError(null);
    try {
      setReview(await startReviewSession());
      setReviewInput("");
    } catch {
      setReviewError("Couldn't start a review.");
    } finally {
      setReviewBusy(false);
    }
  }

  async function submitReview(event: FormEvent) {
    event.preventDefault();
    if (!review || review.complete || reviewBusy || mic.sending) return;
    setReviewBusy(true);
    setReviewError(null);
    try {
      setReview(await answerReview(review.review_id, { text: reviewInput }));
      setReviewInput("");
    } catch {
      setReviewError("Couldn't score that.");
    } finally {
      setReviewBusy(false);
    }
  }

  async function startWarmup() {
    if (!session || busy) return;
    setBusy(true);
    try {
      applyTurn(await sendTurn(session.session_id, "", {}, { advance: "warmup" }));
    } finally {
      setBusy(false);
    }
  }

  async function addToReview() {
    if (!session || busy) return;
    setBusy(true);
    try {
      const body = await enrollReviews(session.session_id);
      setReviewsNote(body.added > 0 ? "Added to review." : "Already in your review deck.");
    } catch {
      setReviewsNote("Couldn't add those to review.");
    } finally {
      setBusy(false);
    }
  }

  async function restart(mode: "briefing" | "replay") {
    if (!session || busy) return;
    setBusy(true);
    try {
      applyTurn(
        await sendTurn(session.session_id, "", {}, {
          advance: mode === "briefing" ? "briefing" : "replay",
        }),
      );
    } finally {
      setBusy(false);
    }
  }

  function onHelp() {
    setLadder((prev) => (prev ? reduceHintLadder(prev, { type: "help" }) : prev));
    setHintEpoch((n) => n + 1);
  }

  async function onRepeat() {
    if (replyAudio?.length) {
      playSpeech(replyAudio, onMouth, setReadingPart);
      return;
    }
    const heard = (activity?.spoken_interpreted || activity?.interpreted || "").trim();
    const pronounce = (activity?.spoken_pronounce || "").trim();
    const fallback = (activity?.pronounce || "").trim();
    const model = pronounce || (activity?.matched || !fallback ? fallback : `Correction. ${fallback}`);
    if (!heard && !model) return;
    setRepeating(true);
    setHintError(null);
    try {
      const clips: SpeechClip[] = [];
      if (heard) clips.push({ wav: await synthesizeSpeech(heard, "guide"), part: "heard" });
      if (model) clips.push({ wav: await synthesizeSpeech(model, "guide"), part: "pronounce" });
      setReplyAudio(clips);
      playSpeech(clips, onMouth, setReadingPart);
    } catch {
      setHintError("Couldn't play that line.");
    } finally {
      setRepeating(false);
    }
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

  function openTown() {
    if (window.location.hash !== "#/town") window.location.hash = "#/town";
  }

  function openScene(id?: string) {
    if (id) setScenarioId(id);
    if (window.location.hash !== "#/play") window.location.hash = "#/play";
  }

  function openEditor() {
    if (window.location.hash !== "#/editor") window.location.hash = "#/editor";
  }

  const nav = (
    <nav className="view-nav" aria-label="Views">
      <button type="button" className={route === "town" ? "active" : ""} onClick={openTown}>
        Town
      </button>
      <button type="button" className={route === "play" ? "active" : ""} onClick={() => openScene()}>
        Scene
      </button>
      <button type="button" className={route === "editor" ? "active" : ""} onClick={openEditor}>
        Editor
      </button>
    </nav>
  );

  if (route === "editor") {
    return (
      <div className={appClass(false, phone)} data-viewport={phone ? "phone" : "wide"}>
        <header>
          <h1>Machi</h1>
          <span className="badge">CPU demo</span>
          {nav}
        </header>
        <EditorView />
      </div>
    );
  }

  if (route === "town") {
    const mapUrl = catalog?.[0]?.scene.background ? townMapUrl(catalog[0].scene.background) : "";
    return (
      <div className={appClass(true, phone)} data-viewport={phone ? "phone" : "wide"}>
        <header>
          <h1>Machi</h1>
          <span className="badge">CPU demo</span>
          {nav}
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
        {catalogError ? <p className="loading">{catalogError}</p> : null}
        {review ? (
          <ReviewPanel
            session={review}
            input={reviewInput}
            busy={reviewBusy}
            error={reviewError || mic.error}
            hearing={hearing}
            recording={mic.recording}
            onInput={setReviewInput}
            onSubmit={(event) => void submitReview(event)}
            onHoldStart={mic.holdStart}
            onHoldEnd={mic.holdEnd}
            onHear={(text) => void onHear(text)}
            onClose={() => {
              setReview(null);
              setReviewError(null);
            }}
          />
        ) : catalog ? (
          <>
            <div className="town-actions">
              <button type="button" disabled={reviewBusy} onClick={() => void startReview()}>
                {reviewBusy ? "…" : "Review (2 min)"}
              </button>
              {reviewError ? <p className="hint-error">{reviewError}</p> : null}
            </div>
            <TownView scenarios={catalog} mapUrl={mapUrl} onOpen={(id) => openScene(id)} />
          </>
        ) : catalogError ? null : (
          <div className="loading">Loading town…</div>
        )}
      </div>
    );
  }

  if (!session || !ladder) {
    return <div className="loading">Loading Machi…</div>;
  }

  const goal = session.goals.find((item) => item.id === goalId) ?? null;
  const view = hintView(goal, session.key_phrases, rung);
  const stars = starsForLadder(ladder, session.stars);
  const checklist = goalChecklist(
    session.goals,
    session.required_goals ?? session.goals.filter((item) => !item.optional).map((item) => item.id),
    debrief?.completed_goals ?? goals,
  );
  const corrections = bestCorrections(debrief?.corrections ?? []);
  const talking = phase === "roleplay" || phase === "warmup";
  const pitchLine = advisoryLine(coach?.pitch_advisory) || advisoryLine(pitchAdvisory);
  const expression: SoraExpression | "neutral" = coachPending
    ? "think"
    : coach
      ? expressionFromCoach(coach)
      : "neutral";
  const spriteSrc = soraSpriteUrl(session.scene.guide_sprite, expression);

  return (
    <div className={appClass(false, phone)} data-viewport={phone ? "phone" : "wide"}>
      <header>
        <h1>Machi</h1>
        <span className="badge">CPU demo</span>
        {nav}
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
      <div className="scene-column">
      <main className="stage">
        <img className="scene-plate" src={session.scene.background} alt="" />
        <div className="guide-slot">
          <KeyedSprite src={spriteSrc} expression={expression} />
          <span className={`mouth ${mouth}`} data-mouth={mouth} aria-hidden="true" />
          <span className="expression" data-expression={expression}>
            {expression}
          </span>
        </div>
        {phase === "briefing" ? (
          <BriefingScreen
            title={session.title_en || "Today's visit"}
            goals={checklist}
            phrases={session.key_phrases}
            reviewsLine={session.reviews_line}
            hearing={hearing}
            onHear={(text) => void onHear(text)}
            onStart={() => void startWarmup()}
          />
        ) : null}
        {phase === "warmup" && warmupPhrase ? (
          <WarmupScreen
            phrase={warmupPhrase}
            index={warmupIndex}
            total={warmupTotal || session.key_phrases.length}
            hearing={hearing}
            onHear={(text) => void onHear(text)}
          />
        ) : null}
        {phase === "debrief" && debrief ? (
          <DebriefScreen
            stars={debrief.stars ?? stars.stars}
            goals={checklist}
            corrections={corrections}
            pitchAdvisory={debrief.pitch_advisory ?? pitchAdvisory}
            reviewsNote={reviewsNote}
            onAddReviews={() => void addToReview()}
            onReplay={() => void restart("replay")}
            onBriefing={() => void restart("briefing")}
          />
        ) : null}
        {phase === "roleplay" ? (
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
        ) : null}
      </main>
        {npc && (
          <div className="subtitle">
            {learner && <SubtitleLine role="learner" label="You" line={learner} level={level} />}
            <SubtitleLine role="npc" label="Staff" line={npc} level={level} />
          </div>
        )}
        {activity && activity.state !== "idle" ? (
          <div className="turn-status" data-state={activity.state} role="status">
            {activity.state === "done" && (activity.interpreted || activity.pronounce) ? (
              <>
                {activity.interpreted ? (
                  <span className={readingPart === "heard" ? "interpreted reading" : "interpreted"}>
                    <span className="status-kicker">Heard</span>
                    {activity.interpreted}
                  </span>
                ) : null}
                {activity.pronounce ? (
                  <span className={readingPart === "pronounce" ? "pronounce reading" : "pronounce"}>
                    <span className="status-kicker">{activity.matched ? "Say it" : "Correction"}</span>
                    {activity.pronounce}
                  </span>
                ) : null}
                <button
                  type="button"
                  className="repeat"
                  disabled={repeating}
                  onClick={() => void onRepeat()}
                >
                  {repeating ? "…" : "Repeat"}
                </button>
              </>
            ) : (
              activity.detail
            )}
          </div>
        ) : null}
      </div>
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
        {pitchLine ? <p className="pitch-advisory">{pitchLine}</p> : null}
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
            disabled={!talking || busy || mic.sending || mic.recording}
          />
        </label>
        <div className="mic-controls">
          <button
            type="button"
            className={mic.recording ? "mic-button live" : "mic-button"}
            aria-pressed={mic.recording}
            disabled={
              phase === "debrief" ||
              Boolean(mic.debug.blockedReason) ||
              ((busy || mic.sending) && !mic.recording)
            }
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
            {micButtonLabel(mic.recording, mic.sending, activity)}
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
                ? `Listening… ${mic.debug.localFrames} frames captured, ${mic.frames} acked`
                : activity && activity.state !== "idle"
                  ? activity.detail
                  : mic.ready
                  ? phase === "briefing"
                    ? "Hold to speak. Your voice is transcribed and starts the warm-up."
                    : "Hold to speak. Your voice is sent to speech recognition."
                  : "Connecting microphone channel…"}
          </p>
        </div>
        <details
          className="mic-debug"
          open
          data-blocked={mic.debug.blockedReason ? "true" : "false"}
        >
          <summary>Mic debug</summary>
          <pre>{formatMicDebug(mic.debug)}</pre>
        </details>
        <button type="submit" disabled={!talking || busy || mic.sending || mic.recording}>
          {busy || mic.sending ? "…" : "Send turn"}
        </button>
      </form>
    </div>
  );
}
