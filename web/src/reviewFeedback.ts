export function reviewMatchLabel(match: string): string {
  if (match === "good" || match === "easy") return "That landed.";
  if (match === "hard") return "Close. Counted as hard.";
  return "Missed. We'll see it again.";
}
