import assert from "node:assert/strict";
import { test } from "node:test";
import {
  HINT_TIMEOUT_MS,
  createHintLadder,
  hintView,
  matchKeyPhrase,
  reduceHintLadder,
  starsForLadder,
} from "./hintLadder.ts";

const PHRASES = [
  { ja: "二人です", kana: "ふたりです", romaji: "futari desu", en: "Two people." },
  {
    ja: "醤油ラーメンを一つお願いします",
    kana: "しょうゆラーメンをひとつおねがいします",
    romaji: "shouyu raamen o hitotsu onegaishimasu",
    en: "One shoyu ramen, please.",
  },
];

const PARTY = {
  id: "party_size",
  prompt_en: "Tell them how many people are in your party (2).",
  accept: ["ふたりです", "二人です"],
};

const STARS = {
  "3": "no hints above level default",
  "2": "one rung climbed",
  "1": "completed",
};

test("silence window for a missed goal is 45 seconds", () => {
  assert.equal(HINT_TIMEOUT_MS, 45_000);
});

test("help, timeout, and a wrong move each climb one rung and cap at 4", () => {
  let state = createHintLadder(1, "party_size");
  assert.equal(state.rungs.party_size, 1);
  assert.deepEqual(state.hintMax, { party_size: 1 });

  state = reduceHintLadder(state, { type: "help" });
  state = reduceHintLadder(state, { type: "timeout" });
  state = reduceHintLadder(state, { type: "wrong" });
  assert.equal(state.rungs.party_size, 4);
  assert.equal(state.hintMax.party_size, 4);

  const stuck = reduceHintLadder(state, { type: "help" });
  assert.equal(stuck.rungs.party_size, 4);
  assert.equal(stuck.hintMax.party_size, 4);
});

test("rungs are stored per goal and stars follow success.stars", () => {
  let state = createHintLadder(2, "party_size");
  assert.equal(state.rungs.party_size, 2);
  assert.deepEqual(starsForLadder(state, STARS), {
    stars: 3,
    rule: "no hints above level default",
  });

  state = reduceHintLadder(state, { type: "help" });
  assert.deepEqual(starsForLadder(state, STARS), {
    stars: 2,
    rule: "one rung climbed",
  });

  state = reduceHintLadder(state, { type: "accepted", nextGoalId: "order" });
  assert.equal(state.goalId, "order");
  assert.equal(state.rungs.order, 2);
  assert.equal(state.rungs.party_size, 3);
  assert.equal(state.hintMax.party_size, 3);

  state = reduceHintLadder(state, { type: "wrong" });
  assert.equal(state.rungs.order, 3);
  assert.equal(state.rungs.party_size, 3);
  assert.deepEqual(starsForLadder(state, STARS), { stars: 2, rule: "one rung climbed" });

  state = reduceHintLadder(state, { type: "timeout" });
  assert.equal(state.rungs.order, 4);
  assert.deepEqual(starsForLadder(state, STARS), { stars: 1, rule: "completed" });
});

test("rung content runs from English through the goal card", () => {
  const phrase = matchKeyPhrase(PARTY, PHRASES);
  assert.equal(phrase?.en, "Two people.");

  assert.equal(hintView(PARTY, PHRASES, 1).text, "Two people.");
  assert.equal(hintView(PARTY, PHRASES, 1).hearText, null);
  assert.equal(hintView(PARTY, PHRASES, 2).mode, "romaji");
  assert.equal(hintView(PARTY, PHRASES, 2).text, "futari desu");
  const kana = hintView(PARTY, PHRASES, 3);
  assert.equal(kana.text, "ふたりです");
  assert.equal(kana.hearText, "二人です");
  const card = hintView(PARTY, PHRASES, 4);
  assert.equal(card.mode, "goal");
  assert.equal(card.text, null);
  assert.equal(card.hearText, null);
  assert.equal(card.promptEn, PARTY.prompt_en);
});
