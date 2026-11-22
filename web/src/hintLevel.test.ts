import assert from "node:assert/strict";
import { test } from "node:test";
import {
  DEFAULT_HINT_LEVEL,
  parseHintLevel,
  romajiRow,
  showRomaji,
} from "./hintLevel.ts";

test("hint level defaults to 2", () => {
  assert.equal(DEFAULT_HINT_LEVEL, 2);
  assert.equal(parseHintLevel("nope"), 2);
  assert.equal(parseHintLevel("4"), 4);
});

test("romaji row shows for npc and learner lines at hint level 2 and above", () => {
  assert.equal(showRomaji(1), false);
  assert.equal(showRomaji(2), true);
  assert.equal(showRomaji(3), true);
  assert.equal(showRomaji(4), true);

  const npc = { role: "npc" as const, romaji: "kochira no oseki e douzo" };
  const learner = { role: "learner" as const, romaji: "futari desu" };
  assert.equal(romajiRow(npc, 1), null);
  assert.equal(romajiRow(learner, 1), null);
  assert.equal(romajiRow(npc, 2), npc.romaji);
  assert.equal(romajiRow(learner, 2), learner.romaji);
  assert.equal(romajiRow(learner, 4), learner.romaji);
  assert.equal(romajiRow({ role: "npc", romaji: "" }, 3), null);
});
