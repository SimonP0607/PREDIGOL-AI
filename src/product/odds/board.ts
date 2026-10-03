/** Board helpers for the Odds page: selection order, the best-value cell, day groups, freshness. */
import type { BestMarket, BestPrice, PriceFreshness } from "@/lib/api/v1/types_product";
import { toNumber } from "@/lib/i18n/format";
import { dayKey } from "@/lib/time";

/** The order a board shows a market's selections in: home before away, over before under. */
export const SELECTION_ORDER: Readonly<Record<string, readonly string[]>> = {
  "1X2": ["Home", "Draw", "Away"],
  OU: ["Over", "Under"],
  BTTS: ["Yes", "No"],
  AH: ["Home", "Away"],
  DC: ["1X", "12", "X2"],
};

export interface PriceSlot {
  selection: string;
  /** Null: no bookmaker quotes this selection at the market's line. */
  price: BestPrice | null;
  /** The fixture's best value: the highest price edge, and only when it pays above fair. */
  best: boolean;
}

/** Every selection of the market in board order; a known selection without a price keeps its slot. */
export function boardSelections(market: BestMarket): string[] {
  const known = SELECTION_ORDER[market.market_key] ?? [];
  const extra = market.selections
    .map((s) => s.selection)
    .filter((s) => !known.includes(s))
    .sort();
  return [...known, ...extra];
}

export function priceSlots(market: BestMarket): PriceSlot[] {
  const bySelection = new Map(market.selections.map((s) => [s.selection, s]));
  const order = boardSelections(market);
  let best: string | null = null;
  let bestEdge = 0;
  for (const selection of order) {
    const price = bySelection.get(selection);
    // An outlier (one book's stale or mistaken quote) is shown and flagged, never crowned.
    const edge = price?.outlier ? null : toNumber(price?.price_edge);
    if (edge !== null && edge > bestEdge) {
      best = selection;
      bestEdge = edge;
    }
  }
  return order.map((selection) => ({
    selection,
    price: bySelection.get(selection) ?? null,
    best: selection === best,
  }));
}

export interface DayGroup<T> {
  /** YYYY-MM-DD in the reader's zone. */
  key: string;
  /** The first kick-off of the day, to label it. */
  first: string;
  items: T[];
}

/** Items in kick-off order, grouped by the reader's local day. */
export function groupByDay<T extends { kickoff_at: string }>(items: readonly T[]): DayGroup<T>[] {
  const sorted = [...items].sort((a, b) => Date.parse(a.kickoff_at) - Date.parse(b.kickoff_at));
  const groups: DayGroup<T>[] = [];
  for (const item of sorted) {
    const key = dayKey(item.kickoff_at);
    const last = groups[groups.length - 1];
    if (last && last.key === key) last.items.push(item);
    else groups.push({ key, first: item.kickoff_at, items: [item] });
  }
  return groups;
}

const HOUR = 3_600_000;

/** How current a price is: fresh within an hour, aging up to three (the value gate's limit), then stale. */
export function priceFreshness(
  asOf: string | null | undefined,
  now: number = Date.now(),
): PriceFreshness {
  if (!asOf) return "none";
  const age = now - Date.parse(asOf);
  if (!Number.isFinite(age)) return "none";
  if (age <= HOUR) return "fresh";
  if (age <= 3 * HOUR) return "aging";
  return "stale";
}
