/** What the statistics pages of plan EA share: the colour of each side and the rows of the trends matrix (V2·7). */

/** The rows of the market x context matrix, in the order of the maqueta. */
export const MATRIX_KEYS = [
  "over_2_5",
  "btts",
  "corners_over_9_5",
  "cards_over_4_5",
  "clean_sheet",
  "scores_first",
  "win",
];

/** The first side primary, the second the system's information blue. */
export function teamColor(i: number): string {
  return i === 0 ? "var(--color-primary)" : "var(--color-info)";
}
