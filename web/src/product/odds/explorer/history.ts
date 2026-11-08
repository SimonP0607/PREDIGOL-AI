/**
 * «Movimiento»: the best price of each selection over the stored history (outliers already left out by the API), and the
 * change since the first capture said with an arrow and in words - never by colour alone (WCAG 1.4.1). Pure; the chart
 * that draws it is loaded only when a reader opens it (MovementChart.tsx).
 */
import { toNumber } from "@/lib/i18n/format";
import type { MoveLine, MovePoint } from "../movement";
import type { OddsMovement, OddsMovementSeries } from "./model";

const MINUTE = 60_000;

/** One series per selection, its points in time order (to the minute), each with its bookmaker's name. */
export function movementLines(movement: OddsMovement | undefined): Array<
  MoveLine & {
    series: OddsMovementSeries;
  }
> {
  if (!movement?.available) return [];
  const names = new Map(movement.bookmakers.map((b) => [b.id, b.name]));
  return movement.series.map((series) => {
    const byMinute = new Map<number, MovePoint>();
    for (const p of series.points) {
      const at = Date.parse(p.captured_at);
      const odds = toNumber(p.best_odds);
      if (!Number.isFinite(at) || odds === null || odds <= 1) continue;
      const t = Math.floor(at / MINUTE) * MINUTE;
      const held = byMinute.get(t);
      if (!held || odds > held.odds) {
        byMinute.set(t, { t, odds, bookmaker: names.get(p.bookmaker_id) ?? "—" });
      }
    }
    return {
      selection: series.selection,
      series,
      points: [...byMinute.values()].sort((a, b) => a.t - b.t),
    };
  });
}

export type Trend = "up" | "down" | "flat";

export interface MoveSummary {
  first: number;
  last: number;
  /** last / first - 1; null with a single capture. */
  change: number | null;
  trend: Trend;
}

export function moveSummary(points: readonly MovePoint[]): MoveSummary | null {
  const first = points[0];
  const last = points[points.length - 1];
  if (!first || !last) return null;
  const change = points.length > 1 ? last.odds / first.odds - 1 : null;
  const trend: Trend =
    change === null || Math.abs(change) < 1e-9 ? "flat" : change > 0 ? "up" : "down";
  return { first: first.odds, last: last.odds, change, trend };
}
