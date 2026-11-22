/** Advisory pitch contour. Never an input to stars. */

export type PitchBand = {
  mora: string;
  contour: "flat" | "rising" | "dropping" | string;
  advisory: "ok" | "low" | "high" | string;
  expected_pitch?: string;
  heard?: string | null;
};

export type PitchAdvisory = {
  is_advisory: true;
  blocks_turn?: boolean;
  bands: PitchBand[];
};

export function advisoryLine(advisory: PitchAdvisory | null | undefined): string | null {
  if (!advisory?.is_advisory || !advisory.bands?.length) return null;
  const text = advisory.bands
    .map((band) => `${band.mora} ${band.contour} ${band.advisory}`)
    .join(" · ");
  return `Pitch advisory · ${text}`;
}

/** Stars stay on the hint ladder. A low or high band does not change them. */
export function debriefStars(
  stars: number,
  advisory: PitchAdvisory | null | undefined,
): number {
  void advisory?.is_advisory;
  return stars;
}
