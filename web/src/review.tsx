import type { FormEvent } from "react";
import type { ReviewSessionView } from "./api";
import { reviewMatchLabel } from "./reviewFeedback";

export function ReviewPanel({
  session,
  input,
  busy,
  error,
  hearing,
  recording,
  onInput,
  onSubmit,
  onHoldStart,
  onHoldEnd,
  onHear,
  onClose,
}: {
  session: ReviewSessionView;
  input: string;
  busy: boolean;
  error: string | null;
  hearing: boolean;
  recording: boolean;
  onInput: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
  onHoldStart: () => void;
  onHoldEnd: () => void;
  onHear: (text: string) => void;
  onClose: () => void;
}) {
  const card = session.card;
  const last = session.last;
  return (
    <section className="flow-panel town-review" data-screen="review">
      <p className="hint-kicker">Review · 2 min · Sora</p>
      <p>{session.situation}</p>
      {session.complete && session.summary ? (
        <div>
          <p>
            Reviewed {session.summary.cards_reviewed}{" "}
            {session.summary.cards_reviewed === 1 ? "card" : "cards"}.
          </p>
          <ul className="phrase-list">
            {session.summary.next_due.map((row) => (
              <li key={row.card_id}>
                {row.phrase_ja} · {row.rating} · due {row.due_at}
              </li>
            ))}
          </ul>
        </div>
      ) : card ? (
        <div>
          <p className="hint-kicker">
            Card {Math.min(session.index + 1, session.card_total)} / {session.card_total}
          </p>
          <p className="ja" dangerouslySetInnerHTML={{ __html: card.kana_ruby || card.ja }} />
          {card.romaji ? <p className="romaji">{card.romaji}</p> : null}
          {card.en ? <p>{card.en}</p> : null}
          <button type="button" disabled={hearing || !card.ja} onClick={() => onHear(card.ja)}>
            {hearing ? "…" : "Hear"}
          </button>
        </div>
      ) : (
        <p>Nothing is due.</p>
      )}
      {last ? (
        <p className="reviews-note" data-match={last.match}>
          {reviewMatchLabel(last.match)} You said: {last.utterance || "…"}
        </p>
      ) : null}
      {error ? <p className="hint-error">{error}</p> : null}
      {session.complete ? (
        <button type="button" onClick={onClose}>
          Back to town
        </button>
      ) : (
        <form className="review-form" onSubmit={onSubmit}>
          <label>
            You say
            <input
              value={input}
              onChange={(event) => onInput(event.target.value)}
              disabled={busy || recording}
            />
          </label>
          <div className="hint-actions">
            <button type="submit" disabled={busy || recording}>
              {busy ? "…" : "Send"}
            </button>
            <button
              type="button"
              className={recording ? "mic-button live" : "mic-button"}
              aria-pressed={recording}
              disabled={busy && !recording}
              onPointerDown={(event) => {
                event.preventDefault();
                event.currentTarget.setPointerCapture(event.pointerId);
                onHoldStart();
              }}
              onPointerUp={(event) => {
                if (event.currentTarget.hasPointerCapture(event.pointerId)) {
                  event.currentTarget.releasePointerCapture(event.pointerId);
                }
                onHoldEnd();
              }}
              onPointerCancel={onHoldEnd}
            >
              {recording ? "Listening…" : "Hold to talk"}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
