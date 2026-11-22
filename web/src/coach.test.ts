import assert from "node:assert/strict";
import { test } from "node:test";
import { expressionFromCoach } from "./coach.ts";

test("sora expression prefers the payload id, then coach-note sentiment", () => {
  assert.equal(expressionFromCoach({ sora_expression: "cheer", sentiment: "sorry" }), "cheer");
  assert.equal(expressionFromCoach({ sentiment: "positive" }), "happy");
  assert.equal(expressionFromCoach({ coach_note_sentiment: "surprised" }), "surprised");
  assert.equal(expressionFromCoach({ correction: "ふたりです" }), "point");
  assert.equal(expressionFromCoach({ goal_hits: ["party_size"] }), "cheer");
  assert.equal(expressionFromCoach({ understandable: false }), "sorry");
  assert.equal(expressionFromCoach({}), "think");
  assert.equal(expressionFromCoach({ sora_expression: "nope", sentiment: "encourage" }), "think");
});
