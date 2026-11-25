/**
 * The line each selection of an odds row is quoted at (an Asian handicap's away side is the other face of the home line).
 * The rest of the old Odds page's board helpers (selection order, best-value cell, row ages, day groups) went with the page
 * (UX-232) and their leftovers with PM-13-07's cleanup: nothing read them.
 */
import { toNumber } from "@/lib/i18n/format";

/**
 * The line a selection of a board row is quoted at. A row carries one line; an Asian handicap's is the
 * home side's, h, and its away side is the other face of that bet, quoted at -h: "1 −0,25" beside "2 +0,25" (plan Cuotas,
 * E1). Every other selection is at the row's line. Null without one.
 */
export function selectionLine(
  marketKey: string,
  selection: string,
  line: string | number | null | undefined,
): number | null {
  const n = toNumber(line);
  if (n === null) return null;
  return marketKey === "AH" && selection === "Away" && n !== 0 ? -n : n;
}
