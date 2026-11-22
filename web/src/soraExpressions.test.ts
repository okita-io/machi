import assert from "node:assert/strict";
import { readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import {
  SORA_EXPRESSIONS,
  spriteSrcOnMissing,
  soraSpriteUrl,
} from "./soraExpressions.ts";

const spriteDir = join(
  dirname(fileURLToPath(import.meta.url)),
  "../../assets/sprites/sora",
);

test("the expression enum matches the seven Sora webps", () => {
  assert.equal(SORA_EXPRESSIONS.length, 7);
  const files = readdirSync(spriteDir)
    .filter((name) => name.endsWith(".webp"))
    .map((name) => name.replace(/\.webp$/, ""))
    .sort();
  assert.deepEqual(files, [...SORA_EXPRESSIONS].sort());
});

test("a missing plate falls back to neutral", () => {
  const guide = "http://localhost:8080/sprites/sora/neutral.webp";
  const cheer = soraSpriteUrl(guide, "cheer");
  assert.equal(spriteSrcOnMissing(cheer), guide);
  assert.equal(spriteSrcOnMissing(guide), guide);
  assert.equal(soraSpriteUrl(guide, "wave"), guide);
  assert.equal(
    spriteSrcOnMissing("http://localhost:8080/sprites/sora/nope.webp"),
    guide,
  );
});
