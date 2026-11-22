import assert from "node:assert/strict";
import { test } from "node:test";
import {
  bestCorrections,
  goalChecklist,
  requiredComplete,
  turnKind,
  warmupStep,
} from "./flow.ts";

test("turn kind prefers the websocket turn_type", () => {
  assert.equal(turnKind({ type: "turn_result", turn_type: "debrief" }), "debrief");
  assert.equal(turnKind({ type: "warmup" }), "warmup");
  assert.equal(turnKind({ type: "turn_result" }), "turn");
});

test("required goals drive the debrief checklist", () => {
  const goals = [
    { id: "party_size", prompt_en: "Say two." },
    { id: "order", prompt_en: "Order ramen." },
    { id: "ask_water", prompt_en: "Ask for water.", optional: true },
    { id: "pay", prompt_en: "Pay." },
  ];
  const required = ["party_size", "order", "pay"];
  const rows = goalChecklist(goals, required, ["party_size", "order"]);
  assert.equal(rows.find((row) => row.id === "pay")?.done, false);
  assert.equal(rows.find((row) => row.id === "ask_water")?.required, false);
  assert.equal(rows.find((row) => row.id === "order")?.done, true);
  assert.equal(requiredComplete(required, ["party_size", "order", "pay"]), true);
  assert.equal(requiredComplete(required, ["party_size", "order"]), false);
});

test("debrief keeps the latest two corrections", () => {
  const cards = bestCorrections([
    { en: "one", ja: "一" },
    { en: "", ja: "" },
    { en: "two", ja: "二" },
    { en: "three", ja: "三" },
  ]);
  assert.deepEqual(
    cards.map((card) => card.en),
    ["two", "three"],
  );
});

test("warm-up advances on a miss and finishes after the last phrase", () => {
  const miss = warmupStep(0, 3, false);
  assert.equal(miss.failed, false);
  assert.equal(miss.passed, false);
  assert.equal(miss.complete, false);
  assert.equal(miss.nextIndex, 1);
  const last = warmupStep(2, 3, true);
  assert.equal(last.complete, true);
  assert.equal(last.nextIndex, 3);
});
