import assert from "node:assert/strict";
import { test } from "node:test";
import { analyserGain, mouthFrameForGain } from "./mouth.ts";

test("silence and tiny analyser gain keep the mouth closed", () => {
  assert.equal(analyserGain(new Uint8Array(32).fill(128)), 0);
  assert.equal(mouthFrameForGain(0), "closed");
  assert.equal(mouthFrameForGain(0.079), "closed");
  assert.equal(mouthFrameForGain(Number.NaN), "closed");
  assert.equal(analyserGain([]), 0);
});

test("louder analyser gain opens the mouth", () => {
  const loud = new Uint8Array(8);
  for (let i = 0; i < loud.length; i++) loud[i] = i % 2 === 0 ? 0 : 255;
  const gain = analyserGain(loud);
  assert.ok(gain > 0.9);
  assert.equal(mouthFrameForGain(gain), "open");
  assert.equal(mouthFrameForGain(0.08), "open");
});
