/** The numbers behind "Por qué" (REVIEW point 15), kept apart from the component so they are tested on their own. */
import type { Dec } from "@/lib/api/v1/types";
import { toNumber } from "@/lib/i18n/format";

/** The fair price and how far the price is from it: 1 / p_market, and odds x p_market - 1. */
export function fairOf(odds: Dec, pMarket: Dec): { fair: number | null; edge: number | null } {
  const p = toNumber(pMarket);
  const o = toNumber(odds);
  if (p === null || p <= 0 || o === null) return { fair: null, edge: null };
  return { fair: 1 / p, edge: o * p - 1 };
}
