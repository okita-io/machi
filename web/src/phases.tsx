import type { KeyPhrase } from "./api";
import type { CorrectionLike, GoalStatus } from "./flow";
import { advisoryLine, debriefStars, type PitchAdvisory } from "./pitchAdvisory";

export function BriefingScreen({
  title,
  goals,
  phrases,
  hearing,
  onHear,
  onStart,
}: {
  title: string;
  goals: GoalStatus[];
  phrases: KeyPhrase[];
  hearing: boolean;
  onHear: (text: string) => void;
  onStart: () => void;
}) {
  return (
    <section className="flow-panel" data-screen="briefing">
      <p className="hint-kicker">Briefing · Sora</p>
      <h2>{title}</h2>
      <ul className="goal-list">
        {goals.map((goal) => (
          <li key={goal.id}>
            {goal.promptEn}
            {goal.required ? "" : " (optional)"}
          </li>
        ))}
      </ul>
      <ul className="phrase-list">
        {phrases.slice(0, 5).map((phrase) => (
          <li key={phrase.ja}>
            <p className="ja">{phrase.ja}</p>
            <p className="romaji">{phrase.romaji}</p>
            <p>{phrase.en}</p>
            <button type="button" disabled={hearing} onClick={() => onHear(phrase.ja)}>
              {hearing ? "…" : "Hear"}
            </button>
          </li>
        ))}
      </ul>
      <button type="button" onClick={onStart}>
        Start warm-up
      </button>
    </section>
  );
}

export function WarmupScreen({
  phrase,
  index,
  total,
  hearing,
  onHear,
}: {
  phrase: KeyPhrase;
  index: number;
  total: number;
  hearing: boolean;
  onHear: (text: string) => void;
}) {
  return (
    <section className="flow-panel" data-screen="warmup">
      <p className="hint-kicker">
        Warm-up · {Math.min(index + 1, total)} / {total}
      </p>
      <p className="ja">{phrase.ja}</p>
      <p className="romaji">{phrase.romaji}</p>
      <p>{phrase.en}</p>
      <p className="hint-prompt">Say it once. A miss still moves on.</p>
      <button type="button" disabled={hearing} onClick={() => onHear(phrase.ja)}>
        {hearing ? "…" : "Hear"}
      </button>
    </section>
  );
}

export function DebriefScreen({
  stars,
  goals,
  corrections,
  pitchAdvisory,
  onReplay,
  onBriefing,
}: {
  stars: number;
  goals: GoalStatus[];
  corrections: (CorrectionLike & { romaji?: string; ruby_html?: string })[];
  pitchAdvisory?: PitchAdvisory | null;
  onReplay: () => void;
  onBriefing: () => void;
}) {
  const shown = debriefStars(stars, pitchAdvisory);
  const glyphs = "★".repeat(shown) + "☆".repeat(Math.max(0, 3 - shown));
  const pitchLine = advisoryLine(pitchAdvisory);
  return (
    <section className="flow-panel" data-screen="debrief">
      <p className="hint-kicker">Debrief</p>
      <p className="stars" data-stars={shown}>
        {glyphs}
      </p>
      {pitchLine ? (
        <p className="pitch-advisory" data-pitch-advisory="yes">
          {pitchLine}
        </p>
      ) : null}
      <ul className="goal-list">
        {goals.map((goal) => (
          <li key={goal.id} data-done={goal.done ? "yes" : "no"}>
            {goal.done ? "✓" : "·"} {goal.promptEn}
            {goal.required ? "" : " (optional)"}
          </li>
        ))}
      </ul>
      <div className="correction-list">
        {corrections.length === 0 ? <p>No corrections this time.</p> : null}
        {corrections.map((card) => (
          <article key={`${card.ja}-${card.en}`} className="correction-card">
            {card.ja ? (
              <p
                className="ja"
                dangerouslySetInnerHTML={{ __html: card.ruby_html || card.ja }}
              />
            ) : null}
            {card.romaji ? <p className="romaji">{card.romaji}</p> : null}
            {card.en ? <p>{card.en}</p> : null}
          </article>
        ))}
      </div>
      <div className="hint-actions">
        <button type="button" onClick={onReplay}>
          Replay scenario
        </button>
        <button type="button" onClick={onBriefing}>
          Return to briefing
        </button>
      </div>
    </section>
  );
}
