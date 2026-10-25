/**
 * "Tu recapitulación" in Mis picks (REVIEW PREDIGOL, point 19): what the user's own settled picks (or parlays) add
 * up to - profit day by day and in total, the average odds, how each odds range and each market went, the streaks.
 * Computed here from every record of the account (GET /me/picks, /me/parlays, every page), at one unit per record,
 * with the profit each record was settled at. Pure: no React here.
 *
 * One figure wherever it is shown (plan UX, A1, defects F53 and F54): the window and the counts follow the server's
 * history (GET /me/history, userdata/records.py) - calendar days in the reader's zone, a parlay by its first match,
 * the return over the records staked - so over the same days the recap and "Tus resultados" say the same.
 */
import type { ResultStatus, UserParlay, UserPick } from "@/lib/api/v1/types_records";
import { toNumber } from "@/lib/i18n/format";
import { dayKey, shiftDay, todayKey } from "@/lib/time";

export type Outcome = "win" | "loss" | "void";

export interface RecapRecord {
  /** When it was decided: the kick-off of its match (a parlay: of its last match). The day it counts on in charts. */
  at: string;
  /** What puts it inside a window: the kick-off of its match (a parlay: of its first match), as the server counts. */
  from: string;
  odds: number | null;
  profit: number;
  outcome: Outcome;
  market: string | null;
  /**
   * It counts in the denominator of the return: settled with a profit and not void (a push stakes its unit and gets
   * it back). The rule of the server's GET /me/history (userdata/records.py, GroupStats.roi), so "Rentabilidad
   * (ROI)" is one figure wherever it is shown (plan UX, A1).
   */
  staked: boolean;
}

export function outcomeOf(status: ResultStatus | string): Outcome | null {
  switch (status) {
    case "WIN":
    case "HALF_WIN":
    case "WON":
    case "PARTIAL_VOID":
      return "win";
    case "LOSS":
    case "HALF_LOSS":
    case "LOST":
      return "loss";
    case "PUSH":
    case "VOID":
      return "void";
    default:
      return null;
  }
}

/** The user's settled picks; the odds are the user's own when they gave them. */
export function fromPicks(picks: readonly UserPick[]): RecapRecord[] {
  const out: RecapRecord[] = [];
  for (const p of picks) {
    const outcome = outcomeOf(p.status);
    if (outcome === null) continue;
    const profit = toNumber(p.profit_units);
    out.push({
      at: p.match.kickoff_at,
      from: p.match.kickoff_at,
      odds: toNumber(p.user_odds) ?? toNumber(p.odds),
      profit: profit ?? 0,
      outcome,
      market: p.market_key,
      staked: profit !== null && p.status !== "VOID",
    });
  }
  return out;
}

/** The user's settled parlays, dated by their last match; a window takes them by their first, as the server does. */
export function fromParlays(parlays: readonly UserParlay[]): RecapRecord[] {
  const out: RecapRecord[] = [];
  for (const p of parlays) {
    const outcome = outcomeOf(p.status);
    if (outcome === null) continue;
    const kickoffs = p.legs.map((l) => l.match.kickoff_at).sort();
    const first = kickoffs[0];
    const last = kickoffs[kickoffs.length - 1];
    // Without a leg the server's history leaves it out (no first match), and so does the recap.
    if (first === undefined || last === undefined) continue;
    const profit = toNumber(p.profit_units);
    out.push({
      at: last,
      from: first,
      odds: toNumber(p.combined_odds),
      profit: profit ?? 0,
      outcome,
      market: null,
      staked: profit !== null && p.status !== "VOID",
    });
  }
  return out;
}

/**
 * The records of the last `days` calendar days in the reader's zone, today included (null: all of them): the
 * server's window for its history (period_bounds - from local midnight `days - 1` days ago to the end of today).
 */
export function within(
  records: readonly RecapRecord[],
  days: number | null,
  now: number = Date.now(),
  tz?: string,
): RecapRecord[] {
  if (days === null) return [...records];
  const today = tz ? todayKey(tz, now) : todayKey(undefined, now);
  const since = shiftDay(today, -(days - 1));
  return records.filter((r) => {
    const day = tz ? dayKey(r.from, tz) : dayKey(r.from);
    return day >= since && day <= today;
  });
}

export interface DayPoint {
  day: string;
  profit: number;
  count: number;
  /** Profit so far, this day included. */
  total: number;
}

export interface Bucket {
  key: string;
  from: number;
  to: number | null;
  count: number;
  wins: number;
  hitRate: number | null;
  profit: number;
}

export interface MarketRow {
  market: string;
  count: number;
  wins: number;
  hitRate: number | null;
  profit: number;
}

export interface Streaks {
  current: { kind: "win" | "loss"; length: number } | null;
  bestWin: number;
  worstLoss: number;
}

export interface Recap {
  settled: number;
  wins: number;
  losses: number;
  voids: number;
  /** wins / (wins + losses): a void neither wins nor loses. */
  hitRate: number | null;
  profit: number;
  /** Records staked: the sample the return is counted over. */
  staked: number;
  /** "Rentabilidad (ROI)": profit / staked, one unit each - the formula of the server's history. */
  roi: number | null;
  avgOdds: number | null;
  avgOddsWon: number | null;
  streaks: Streaks;
  /** The last 20 decided records, oldest first (voids left out). */
  last: Array<"win" | "loss">;
  days: DayPoint[];
  bestDay: DayPoint | null;
  worstDay: DayPoint | null;
  byOdds: Bucket[];
  byMarket: MarketRow[];
}

export const ODDS_BUCKETS: ReadonlyArray<{ key: string; from: number; to: number | null }> = [
  { key: "lt1.5", from: 1, to: 1.5 },
  { key: "1.5-2", from: 1.5, to: 2 },
  { key: "2-3", from: 2, to: 3 },
  { key: "3-5", from: 3, to: 5 },
  { key: "5+", from: 5, to: null },
];

const mean = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);
const rate = (wins: number, decided: number) => (decided > 0 ? wins / decided : null);

export function streaksOf(results: ReadonlyArray<"win" | "loss">): Streaks {
  let bestWin = 0;
  let worstLoss = 0;
  let kind: "win" | "loss" | null = null;
  let length = 0;
  for (const r of results) {
    if (r === kind) length += 1;
    else {
      kind = r;
      length = 1;
    }
    if (kind === "win") bestWin = Math.max(bestWin, length);
    else worstLoss = Math.max(worstLoss, length);
  }
  return { current: kind ? { kind, length } : null, bestWin, worstLoss };
}

export function recap(records: readonly RecapRecord[], tz?: string): Recap {
  const sorted = [...records].sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  const decided = sorted
    .filter((r) => r.outcome !== "void")
    .map((r) => r.outcome as "win" | "loss");
  const wins = decided.filter((r) => r === "win").length;
  const losses = decided.length - wins;
  const profit = sorted.reduce((a, r) => a + r.profit, 0);

  const byDay = new Map<string, { profit: number; count: number }>();
  for (const r of sorted) {
    const key = tz ? dayKey(r.at, tz) : dayKey(r.at);
    const d = byDay.get(key) ?? { profit: 0, count: 0 };
    d.profit += r.profit;
    d.count += 1;
    byDay.set(key, d);
  }
  let running = 0;
  const days: DayPoint[] = [...byDay.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([day, d]) => {
      running += d.profit;
      return { day, profit: d.profit, count: d.count, total: running };
    });
  const best = days.reduce<DayPoint | null>(
    (a, d) => (a === null || d.profit > a.profit ? d : a),
    null,
  );
  const worst = days.reduce<DayPoint | null>(
    (a, d) => (a === null || d.profit < a.profit ? d : a),
    null,
  );

  const byOdds: Bucket[] = ODDS_BUCKETS.map((b) => {
    const inside = sorted.filter(
      (r) => r.odds !== null && r.odds >= b.from && (b.to === null || r.odds < b.to),
    );
    const w = inside.filter((r) => r.outcome === "win").length;
    const l = inside.filter((r) => r.outcome === "loss").length;
    return {
      ...b,
      count: inside.length,
      wins: w,
      hitRate: rate(w, w + l),
      profit: inside.reduce((a, r) => a + r.profit, 0),
    };
  });

  const markets = new Map<string, RecapRecord[]>();
  for (const r of sorted) {
    if (r.market === null) continue;
    markets.set(r.market, [...(markets.get(r.market) ?? []), r]);
  }
  const byMarket: MarketRow[] = [...markets.entries()]
    .map(([market, rs]) => {
      const w = rs.filter((r) => r.outcome === "win").length;
      const l = rs.filter((r) => r.outcome === "loss").length;
      return {
        market,
        count: rs.length,
        wins: w,
        hitRate: rate(w, w + l),
        profit: rs.reduce((a, r) => a + r.profit, 0),
      };
    })
    .sort((a, b) => b.count - a.count || a.market.localeCompare(b.market));

  const priced = sorted.filter((r) => r.odds !== null).map((r) => r.odds as number);
  const pricedWon = sorted
    .filter((r) => r.odds !== null && r.outcome === "win")
    .map((r) => r.odds as number);
  const staked = sorted.filter((r) => r.staked).length;
  return {
    settled: sorted.length,
    wins,
    losses,
    voids: sorted.length - decided.length,
    hitRate: rate(wins, decided.length),
    profit,
    staked,
    roi: staked ? profit / staked : null,
    avgOdds: mean(priced),
    avgOddsWon: mean(pricedWon),
    streaks: streaksOf(decided),
    last: decided.slice(-20),
    days,
    bestDay: best,
    worstDay: worst,
    byOdds,
    byMarket,
  };
}
