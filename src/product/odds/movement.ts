/**
 * Price movement for the Odds page: the BEST price available at each capture, per
 * selection, before kick-off. Pure: no React here.
 */
import type { OddsSeries } from "@/lib/api/v1/types";
import { toNumber } from "@/lib/i18n/format";

export interface MovePoint {
  /** The capture instant, to the minute (ms since epoch). */
  t: number;
  /** The highest price any bookmaker quoted at that capture. */
  odds: number;
  bookmaker: string;
}

export interface MoveLine {
  selection: string;
  points: MovePoint[];
}

const MINUTE = 60_000;

/**
 * For every capture instant, the highest prematch price any bookmaker quoted for each
 * selection of the market at that line. Captures are matched to the minute, so books
 * stored a few milliseconds apart in one capture count as the same instant.
 */
export function bestPriceLines(
  series: readonly OddsSeries[],
  q: { market: string; line: string | number | null; selections: readonly string[] },
): MoveLine[] {
  const line = toNumber(q.line);
  const bySelection = new Map<string, Map<number, MovePoint>>();
  for (const s of series) {
    if (s.market_key !== q.market || !q.selections.includes(s.selection)) continue;
    if (line !== null && toNumber(s.line) !== line) continue;
    let byInstant = bySelection.get(s.selection);
    if (!byInstant) {
      byInstant = new Map();
      bySelection.set(s.selection, byInstant);
    }
    for (const p of s.points) {
      if (p.source !== "prematch") continue;
      const at = Date.parse(p.captured_at);
      const odds = toNumber(p.odds_decimal);
      if (!Number.isFinite(at) || odds === null || odds <= 1) continue;
      const t = Math.floor(at / MINUTE) * MINUTE;
      const current = byInstant.get(t);
      if (!current || odds > current.odds) byInstant.set(t, { t, odds, bookmaker: s.bookmaker });
    }
  }
  return q.selections.map((selection) => ({
    selection,
    points: [...(bySelection.get(selection)?.values() ?? [])].sort((a, b) => a.t - b.t),
  }));
}

/** First and last capture across every line: one time axis for all of them. */
export function timeExtent(lines: readonly MoveLine[]): [number, number] | null {
  let lo = Infinity;
  let hi = -Infinity;
  for (const l of lines) {
    for (const p of l.points) {
      if (p.t < lo) lo = p.t;
      if (p.t > hi) hi = p.t;
    }
  }
  return Number.isFinite(lo) && hi > lo ? [lo, hi] : null;
}

const floor2 = (n: number) => Math.floor(n * 100) / 100;
const ceil2 = (n: number) => Math.ceil(n * 100) / 100;

/**
 * A y-range that shows the movement without inflating a small one: the range of the
 * prices plus some air, never narrower than ±2.5 % around its middle, never below 1.
 */
export function oddsDomain(values: readonly number[]): [number, number] {
  if (values.length === 0) return [1, 2];
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const mid = (lo + hi) / 2;
  const half = Math.max(((hi - lo) / 2) * 1.3, mid * 0.025, 0.02);
  return [Math.max(1, floor2(mid - half)), ceil2(mid + half)];
}

/** Three ticks for a compact axis: both ends and the middle, at two decimals, never repeated. */
export function oddsTicks([lo, hi]: readonly [number, number]): number[] {
  const ticks = [lo, Math.round(((lo + hi) / 2) * 100) / 100, hi];
  return ticks.filter((v, i) => ticks.indexOf(v) === i);
}
