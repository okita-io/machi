import assert from "node:assert/strict";
import { test } from "node:test";
import { reviewMatchLabel } from "./reviewFeedback.ts";

test("review feedback names the fuzzy grade", () => {
  assert.equal(reviewMatchLabel("good"), "That landed.");
  assert.equal(reviewMatchLabel("easy"), "That landed.");
  assert.equal(reviewMatchLabel("hard"), "Close. Counted as hard.");
  assert.equal(reviewMatchLabel("again"), "Missed. We'll see it again.");
});
