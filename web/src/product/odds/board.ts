/**
 * Board helpers for the Odds page: selection order, each selection's line, the best-value cell, day groups, freshness.
 */
import type {
  BestMarket,
  BestOddsFixture,
  BestPrice,
  PriceFreshness,
} from "@/lib/api/v1/types_product";
import { toNumber } from "@/lib/i18n/format";
import { dayKey } from "@/lib/time";
import { isQuarterLine } from "@/product/records/model";

/** The order a board shows a market's selections in: home before away, over before under. */
export const SELECTION_ORDER: Readonly<Record<string, readonly string[]>> = {
  "1X2": ["Home", "Draw", "Away"],
  OU: ["Over", "Under"],
  BTTS: ["Yes", "No"],
  AH: ["Home", "Away"],
  DC: ["1X", "12", "X2"],
};

/**
 * Fewer bookmakers than this and a price is never the row's gold: the highlights ask as many (the backend's
 * HIGHLIGHT_MIN_BOOKS), and one or two books are not a market to stand out from.
 */
export const GOLD_MIN_BOOKS = 3;

/**
 * The line a selection of a board row is quoted at. A row carries one line (`BestMarket.line`); an Asian handicap's is the
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

export interface PriceSlot {
  selection: string;
  /** Null: no bookmaker quotes this selection at the market's line. */
  price: BestPrice | null;
  /**
   * The fixture's best value: the highest price edge, only when it pays above fair, never an outlier and never a price
   * fewer than GOLD_MIN_BOOKS bookmakers quote.
   */
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
    // An outlier (one book's stale or mistaken quote) is shown and flagged, never crowned; nor is a price too few books quote.
    const edge =
      price && !price.outlier && price.n_bookmakers >= GOLD_MIN_BOOKS
        ? toNumber(price.price_edge)
        : null;
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

/**
 * A row only to look at, not to add from: its line is a quarter line (.25 / .75), which never goes in a parlay (a half-won leg
 * has no clean meaning there). An Asian handicap's two sides, h and -h, are quarter lines together.
 */
export function lookupOnly(market: Pick<BestMarket, "line">): boolean {
  return isQuarterLine(market.line);
}

/**
 * When a row's prices were taken: the OLDEST capture among the selections it shows - a row is only as current as its oldest
 * price. Null without one.
 */
export function rowAsOf(market: Pick<BestMarket, "selections"> | null | undefined): string | null {
  let oldest: string | null = null;
  let oldestAt = Infinity;
  for (const s of market?.selections ?? []) {
    const at = Date.parse(s.as_of);
    if (Number.isFinite(at) && at < oldestAt) {
      oldest = s.as_of;
      oldestAt = at;
    }
  }
  return oldest;
}

/**
 * How old the rows on show are (each as old as its oldest price, `rowAsOf`): the newest row's capture and the oldest row's,
 * for «Precios de hace 14 min a hace 2 h». Null without a priced row.
 */
export function priceAges(
  fixtures: ReadonlyArray<Pick<BestOddsFixture, "markets">>,
  market: string,
): { newest: string; oldest: string } | null {
  let newest: string | null = null;
  let oldest: string | null = null;
  let newestAt = -Infinity;
  let oldestAt = Infinity;
  for (const f of fixtures) {
    const asOf = rowAsOf(f.markets.find((m) => m.market_key === market));
    if (asOf === null) continue;
    const at = Date.parse(asOf);
    if (at > newestAt) {
      newest = asOf;
      newestAt = at;
    }
    if (at < oldestAt) {
      oldest = asOf;
      oldestAt = at;
    }
  }
  return newest !== null && oldest !== null ? { newest, oldest } : null;
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
