import assert from "node:assert/strict";
import test from "node:test";

import { advisoryLine, debriefStars, type PitchAdvisory } from "./pitchAdvisory.ts";

const low: PitchAdvisory = {
  is_advisory: true,
  blocks_turn: false,
  bands: [
    { mora: "ハ", contour: "flat", advisory: "ok" },
    { mora: "シ", contour: "dropping", advisory: "low" },
  ],
};

test("advisory line is one subtle summary", () => {
  assert.equal(advisoryLine(null), null);
  assert.equal(advisoryLine({ is_advisory: true, bands: [] }), null);
  assert.equal(
    advisoryLine(low),
    "Pitch advisory · ハ flat ok · シ dropping low",
  );
});

test("pitch advisory does not change stars", () => {
  assert.equal(debriefStars(3, low), 3);
  assert.equal(debriefStars(1, low), 1);
  assert.equal(debriefStars(3, null), 3);
});
