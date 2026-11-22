/** Clickable buildings on `assets/bg/town_map.webp`. Percents of the image. */

export const TOWN_MAP_FILE = "bg/town_map.webp";

export type TownBuildingId = "ramen" | "konbini" | "street" | "laundry" | "taxi" | "station";

export type TownHotspot = {
  id: TownBuildingId;
  scenarioId: string;
  labelEn: string;
  labelJa: string;
  left: number;
  top: number;
  width: number;
  height: number;
};

export const TOWN_HOTSPOTS: readonly TownHotspot[] = [
  {
    id: "ramen",
    scenarioId: "restaurant_ramen_01",
    labelEn: "Ramen shop",
    labelJa: "ラーメン屋",
    left: 6.2,
    top: 4.7,
    width: 26.8,
    height: 46.4,
  },
  {
    id: "konbini",
    scenarioId: "konbini_checkout_01",
    labelEn: "Konbini",
    labelJa: "コンビニ",
    left: 37.8,
    top: 7.3,
    width: 26.8,
    height: 40.6,
  },
  {
    id: "laundry",
    scenarioId: "coin_laundry_01",
    labelEn: "Coin laundry",
    labelJa: "コインランドリー",
    left: 71.4,
    top: 10.9,
    width: 24.1,
    height: 37.5,
  },
  {
    id: "taxi",
    scenarioId: "taxi_01",
    labelEn: "Taxi",
    labelJa: "タクシー",
    left: 6.2,
    top: 51.6,
    width: 24.4,
    height: 38.5,
  },
  {
    id: "station",
    scenarioId: "train_ticket_01",
    labelEn: "Station",
    labelJa: "駅",
    left: 34.8,
    top: 47.4,
    width: 36.9,
    height: 47.4,
  },
  {
    id: "street",
    scenarioId: "directions_01",
    labelEn: "Street",
    labelJa: "街",
    left: 77.1,
    top: 58.9,
    width: 18.8,
    height: 29.2,
  },
];

export type ScenarioCard = {
  id: string;
  title_en: string;
  title_ja: string;
};

export type TownHotspotState = TownHotspot & {
  locked: boolean;
  titleEn: string;
  titleJa: string;
};

export type LockedScenario = {
  id: string;
  titleEn: string;
  titleJa: string;
  tooltip: string;
};

export function hotspotForScenario(scenarioId: string): TownHotspot | undefined {
  return TOWN_HOTSPOTS.find((spot) => spot.scenarioId === scenarioId);
}

/** Buildings whose scenario is missing, plus scenarios with no map building. */
export function resolveTown(scenarios: ScenarioCard[]): {
  hotspots: TownHotspotState[];
  locked: LockedScenario[];
} {
  const known = new Map(scenarios.map((card) => [card.id, card]));
  const mapped = new Set(TOWN_HOTSPOTS.map((spot) => spot.scenarioId));
  const hotspots = TOWN_HOTSPOTS.map((spot) => {
    const found = known.get(spot.scenarioId);
    return {
      ...spot,
      locked: !found,
      titleEn: found?.title_en ?? spot.labelEn,
      titleJa: found?.title_ja ?? spot.labelJa,
    };
  });
  const locked = scenarios
    .filter((card) => !mapped.has(card.id))
    .map((card) => ({
      id: card.id,
      titleEn: card.title_en,
      titleJa: card.title_ja,
      tooltip: "Not on the town map yet",
    }));
  return { hotspots, locked };
}

/** Origin of an assets URL such as `http://host:8080/bg/ramen.webp`. */
export function assetsRootFromBackground(backgroundUrl: string): string {
  const marker = "/bg/";
  const idx = backgroundUrl.lastIndexOf(marker);
  if (idx >= 0) return backgroundUrl.slice(0, idx);
  return backgroundUrl.replace(/\/[^/]*$/, "");
}

export function townMapUrl(backgroundUrl: string): string {
  return `${assetsRootFromBackground(backgroundUrl)}/${TOWN_MAP_FILE}`;
}
