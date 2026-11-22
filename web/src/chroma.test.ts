import assert from "node:assert/strict";
import { test } from "node:test";
import { chromaKeyAlpha, keyChromaPixels } from "./chroma.ts";

test("pure chroma green becomes transparent", () => {
  assert.equal(chromaKeyAlpha(0, 255, 10, 255), 0);
  assert.equal(chromaKeyAlpha(13, 250, 40, 255), 0);
  assert.equal(chromaKeyAlpha(105, 242, 100, 255), 0);
});

test("white sticker, skin, and teal eyes stay opaque", () => {
  assert.equal(chromaKeyAlpha(252, 252, 236, 255), 255);
  assert.equal(chromaKeyAlpha(192, 185, 126, 255), 255);
  assert.equal(chromaKeyAlpha(9, 202, 162, 255), 255);
  assert.equal(chromaKeyAlpha(45, 192, 161, 255), 255);
  assert.equal(chromaKeyAlpha(0, 255, 10, 0), 0);
});

test("keyChromaPixels writes alpha and leaves color channels", () => {
  const data = new Uint8ClampedArray([0, 255, 10, 255, 252, 252, 236, 255]);
  keyChromaPixels(data);
  assert.deepEqual(Array.from(data), [0, 255, 10, 0, 252, 252, 236, 255]);
});
