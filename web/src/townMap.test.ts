import assert from "node:assert/strict";
import { test } from "node:test";
import { soraSpriteUrl } from "./sprites.ts";
import {
  TOWN_HOTSPOTS,
  hotspotForScenario,
  resolveTown,
  townMapUrl,
  type ScenarioCard,
} from "./townMap.ts";

const LISTED: ScenarioCard[] = [
  { id: "restaurant_ramen_01", title_en: "Ramen shop: a table for two", title_ja: "ラーメン屋" },
  { id: "konbini_checkout_01", title_en: "Konbini: one bento", title_ja: "コンビニ" },
  { id: "directions_01", title_en: "Directions: the station", title_ja: "駅への道" },
  { id: "coin_laundry_01", title_en: "Coin laundry: washer 3", title_ja: "コインランドリー" },
  { id: "taxi_01", title_en: "Taxi: to the station", title_ja: "タクシー" },
  { id: "train_ticket_01", title_en: "Train ticket: Shinagawa", title_ja: "切符" },
  { id: "shrine_01", title_en: "Shrine", title_ja: "神社" },
];

test("six buildings cover the map and the ramen shop shares the ramen building", () => {
  assert.equal(TOWN_HOTSPOTS.length, 6);
  const ids = TOWN_HOTSPOTS.map((spot) => spot.id);
  assert.deepEqual(new Set(ids).size, 6);
  assert.equal(hotspotForScenario("restaurant_ramen_01")?.id, "ramen");
  for (const spot of TOWN_HOTSPOTS) {
    assert.ok(spot.left >= 0 && spot.top >= 0);
    assert.ok(spot.left + spot.width <= 100.1);
    assert.ok(spot.top + spot.height <= 100.1);
  }
});

test("listed buildings unlock and unknown scenarios stay locked", () => {
  const { hotspots, locked } = resolveTown(LISTED);
  assert.equal(hotspots.every((spot) => !spot.locked), true);
  assert.equal(hotspots.find((spot) => spot.id === "ramen")?.titleJa, "ラーメン屋");
  assert.deepEqual(locked, [
    {
      id: "shrine_01",
      titleEn: "Shrine",
      titleJa: "神社",
      tooltip: "Not on the town map yet",
    },
  ]);
  const missing = resolveTown(LISTED.filter((card) => card.id !== "taxi_01"));
  assert.equal(missing.hotspots.find((spot) => spot.id === "taxi")?.locked, true);
});

test("town map and sprite URLs sit on the assets host", () => {
  assert.equal(
    townMapUrl("http://localhost:8080/bg/ramen.webp"),
    "http://localhost:8080/bg/town_map.webp",
  );
  const guide = "http://localhost:8080/sprites/sora/neutral.webp";
  assert.equal(soraSpriteUrl(guide, "neutral"), guide);
  assert.equal(soraSpriteUrl(guide, "cheer"), "http://localhost:8080/sprites/sora/cheer.webp");
  assert.equal(soraSpriteUrl(guide, "wave"), guide);
});
