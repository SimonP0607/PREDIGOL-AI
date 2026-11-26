/**
 * A match's statistics by half (plan PM, PM-10-03): what the API's figures become for the system's `StatBars`. Pure - no React, no
 * network. A figure the provider did not send arrives as null and stays null (`StatBars` draws it as «—» with a dashed track, never a
 * zero); a statistic the competition has not built is not in the answer, so it is not drawn.
 */
import type { MatchPeriodStats, PeriodBlock, PeriodKey } from "@/lib/api/v1/types_period_stats";
import type { StatFormat, StatRow } from "../model";

export const PERIODS: readonly PeriodKey[] = ["total", "1h", "2h"];

/** The API's column of each statistic -> the Match Center's key (its label `match.stats.label.<key>`) and its format. */
export const PERIOD_STATS: Readonly<Record<string, { key: string; format: StatFormat }>> = {
  possession_pct: { key: "possession", format: "pct" },
  expected_goals: { key: "xg", format: "dec2" },
  shots: { key: "shots", format: "int" },
  shots_on_target: { key: "shotsOnTarget", format: "int" },
  corners: { key: "corners", format: "int" },
  fouls: { key: "fouls", format: "int" },
  offsides: { key: "offsides", format: "int" },
  yellow_cards: { key: "yellowCards", format: "int" },
  red_cards: { key: "redCards", format: "int" },
  saves: { key: "saves", format: "int" },
};

export function blockOf(data: MatchPeriodStats, period: PeriodKey): PeriodBlock | null {
  return data.periods.find((p) => p.period === period) ?? null;
}

/** The rows of one period; a statistic whose two sides are both missing is left out (nothing to compare). */
export function periodRows(data: MatchPeriodStats, period: PeriodKey): StatRow[] {
  const block = blockOf(data, period);
  if (!block) return [];
  return block.figures
    .flatMap((f) => {
      const def = PERIOD_STATS[f.key];
      return def ? [{ key: def.key, format: def.format, home: f.home, away: f.away }] : [];
    })
    .filter((r) => r.home !== null || r.away !== null);
}

/** The periods that have something to draw (the toggle offers only those, the match first). */
export function periodsWithRows(data: MatchPeriodStats): PeriodKey[] {
  return PERIODS.filter((p) => periodRows(data, p).length > 0);
}

/**
 * Whether a half's figures add up to the match's, for the statistics that are counted (a count of the match is the sum of its halves).
 * The provider's own totals differ from the sum in about one match in a hundred: the card says so instead of hiding it.
 */
export function halvesAddUp(data: MatchPeriodStats): boolean {
  const total = periodRows(data, "total");
  const first = periodRows(data, "1h");
  const second = periodRows(data, "2h");
  const COUNTED = new Set([
    "shots",
    "shotsOnTarget",
    "corners",
    "fouls",
    "offsides",
    "yellowCards",
    "redCards",
    "saves",
  ]);
  return total
    .filter((r) => COUNTED.has(r.key))
    .every((r) => {
      const a = first.find((x) => x.key === r.key);
      const b = second.find((x) => x.key === r.key);
      if (!a || !b) return true;
      const sum = (x: number | null, y: number | null) => (x === null || y === null ? null : x + y);
      const home = sum(a.home, b.home);
      const away = sum(a.away, b.away);
      return (
        (home === null || r.home === null || home === r.home) &&
        (away === null || r.away === null || away === r.away)
      );
    });
}
