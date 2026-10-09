/**
 * What the Live page reads out of a live match: how much we know about it, its key
 * events, a few comparable statistics and the main in-play prices. Pure functions.
 */
import type { LiveMatch, LiveQuote, MatchEvent, TeamStatLine } from "@/lib/api/v1/types_center";
import type { PriceFreshness } from "@/lib/api/v1/types_product";
import { toNumber } from "@/lib/i18n/format";
import { phaseOf, shortStatus } from "@/product/matches/status";

export type Level = "rich" | "partial" | "basic";

/** The API's own grading; an older payload without it is graded by what it carries. */
export function levelOf(m: LiveMatch): Level {
  if (m.completeness) return m.completeness.level;
  const hasDetail =
    m.statistics.length > 0 || m.events.length > 0 || m.main_odds.some((q) => q.odds !== null);
  return hasDetail ? "partial" : "basic";
}

export const SIGNALS = [
  "score",
  "minute",
  "events",
  "stats",
  "lineups",
  "players",
  "live_odds",
  "markets",
] as const;
export type Signal = (typeof SIGNALS)[number];

/** 1 to 4 bars, like a signal meter: 90+ full, rich 3, partial 2, basic 1. */
export function completenessBars(score: number): 1 | 2 | 3 | 4 {
  if (score >= 90) return 4;
  if (score >= 70) return 3;
  if (score >= 40) return 2;
  return 1;
}

// ── Key events ──────────────────────────────────────────────────────────────

export type KeyEventKind = "goal" | "own_goal" | "penalty" | "red_card";

export interface KeyEvent {
  seq: number;
  minute: number;
  extra: number | null;
  side: "home" | "away";
  player: string | null;
  kind: KeyEventKind;
}

/** Goals (not missed penalties, not a shoot-out) and red cards, in match order. */
export function keyEvents(events: readonly MatchEvent[]): KeyEvent[] {
  const out: KeyEvent[] = [];
  for (const e of events) {
    if (e.side !== "home" && e.side !== "away") continue;
    const type = e.type.toLowerCase();
    const detail = (e.detail ?? "").toLowerCase();
    const comments = (e.comments ?? "").toLowerCase();
    let kind: KeyEventKind | null = null;
    if (type === "goal") {
      if (detail.includes("missed") || comments.includes("shootout")) continue;
      kind = detail.includes("own") ? "own_goal" : detail.includes("penalty") ? "penalty" : "goal";
    } else if (type === "card" && (detail.includes("red") || detail.includes("second yellow"))) {
      kind = "red_card";
    }
    if (!kind) continue;
    out.push({
      seq: e.seq,
      minute: e.minute,
      extra: e.extra_minute,
      side: e.side,
      // The provider sometimes joins names with a middle dot ("Rayan·Buifrahi").
      player: e.player ? e.player.replace(/\s*·\s*/g, " ").trim() : null,
      kind,
    });
  }
  return out.sort(
    (a, b) => a.minute - b.minute || (a.extra ?? 0) - (b.extra ?? 0) || a.seq - b.seq,
  );
}

/** The `max` most recent, still in match order, and how many earlier ones were left out. */
export function latestEvents(
  events: readonly KeyEvent[],
  max = 4,
): { shown: KeyEvent[]; hidden: number } {
  const shown = events.slice(-max);
  return { shown, hidden: events.length - shown.length };
}

// ── Statistics ──────────────────────────────────────────────────────────────

export type StatKey = "possession" | "shots" | "shotsOnTarget" | "corners";

export interface StatRow {
  key: StatKey;
  home: number;
  away: number;
  /** Shown as a percentage (possession). */
  pct: boolean;
}

/** Possession, shots, shots on target and corners - each only when both teams have it. */
export function statRows(lines: readonly TeamStatLine[]): StatRow[] {
  const home = lines.find((l) => l.side === "home");
  const away = lines.find((l) => l.side === "away");
  if (!home || !away) return [];
  const rows: StatRow[] = [];
  const add = (key: StatKey, h: number | null, a: number | null, pct = false) => {
    if (h === null || a === null) return;
    if (pct && h + a <= 0) return;
    rows.push({ key, home: h, away: a, pct });
  };
  add("possession", toNumber(home.possession_pct), toNumber(away.possession_pct), true);
  add("shots", home.shots, away.shots);
  add("shotsOnTarget", home.shots_on_target, away.shots_on_target);
  add("corners", home.corners, away.corners);
  return rows;
}

/** The home side's share of a two-way stat (0.5 when neither has any). */
export function homeShare(row: StatRow): number {
  const total = row.home + row.away;
  return total > 0 ? row.home / total : 0.5;
}

// ── In-play prices ──────────────────────────────────────────────────────────

export const X12 = ["Home", "Draw", "Away"] as const;

export interface LiveOdds {
  /** Home, Draw, Away - null where that selection was never quoted. */
  x12: [LiveQuote | null, LiveQuote | null, LiveQuote | null] | null;
  /** The current main goals line. */
  ou: { line: string; over: LiveQuote | null; under: LiveQuote | null } | null;
  /** When the newest of the prices shown was captured. */
  newest: string | null;
}

function capturedAt(q: LiveQuote): number {
  const at = Date.parse(q.captured_at);
  return Number.isNaN(at) ? 0 : at;
}

function newestOf(quotes: readonly LiveQuote[]): LiveQuote | null {
  let best: LiveQuote | null = null;
  for (const q of quotes) if (!best || capturedAt(q) > capturedAt(best)) best = q;
  return best;
}

/**
 * 1X2 and the main Over/Under line. The book moves its main goals line during a match,
 * and every line it held in the last half hour is still listed: the current one is the
 * line quoted most recently (main lines preferred, both sides preferred).
 */
export function liveOdds(quotes: readonly LiveQuote[]): LiveOdds {
  const sides = X12.map((sel) =>
    newestOf(quotes.filter((q) => q.market_key === "1X2" && q.selection === sel)),
  ) as [LiveQuote | null, LiveQuote | null, LiveQuote | null];
  const x12 = sides.some((q) => q !== null) ? sides : null;

  const goals = quotes.filter(
    (q) => q.market_key === "OU" && (q.selection === "Over" || q.selection === "Under"),
  );
  const pool = goals.some((q) => q.main_line === true)
    ? goals.filter((q) => q.main_line === true)
    : goals;
  const byLine = new Map<string, LiveQuote[]>();
  for (const q of pool) {
    const n = toNumber(q.line);
    if (n === null) continue;
    const key = String(n);
    const list = byLine.get(key);
    if (list) list.push(q);
    else byLine.set(key, [q]);
  }
  let ou: LiveOdds["ou"] = null;
  let bestRank: [number, number] = [-1, -1];
  for (const list of byLine.values()) {
    const over = newestOf(list.filter((q) => q.selection === "Over"));
    const under = newestOf(list.filter((q) => q.selection === "Under"));
    const latest = Math.max(...list.map(capturedAt));
    const rank: [number, number] = [over && under ? 1 : 0, latest];
    if (rank[0] > bestRank[0] || (rank[0] === bestRank[0] && rank[1] > bestRank[1])) {
      bestRank = rank;
      ou = { line: (over ?? under)?.line ?? list[0]?.line ?? "", over, under };
    }
  }

  const shown = [...(x12 ?? []), ou?.over ?? null, ou?.under ?? null].filter(
    (q): q is LiveQuote => q !== null && q.odds !== null,
  );
  const newest = newestOf(shown);
  return { x12, ou, newest: newest ? newest.captured_at : null };
}

/** How current an in-play price is: they move by the minute. */
export function quoteFreshness(at: string | null, now: number): PriceFreshness {
  if (!at) return "none";
  const age = now - Date.parse(at);
  if (Number.isNaN(age)) return "none";
  if (age <= 3 * 60_000) return "fresh";
  if (age <= 10 * 60_000) return "aging";
  return "stale";
}

// ── The board ───────────────────────────────────────────────────────────────

export interface BoardSummary {
  /** Kicked off and being played (breaks included). */
  inPlay: number;
  /** Priced in play already, not kicked off yet. */
  starting: number;
  /** The newest match state on the board. */
  newest: string | null;
}

export function boardSummary(matches: readonly LiveMatch[]): BoardSummary {
  let inPlay = 0;
  let starting = 0;
  let newest: string | null = null;
  for (const m of matches) {
    const phase = phaseOf(shortStatus(m.status));
    if (phase === "pre") starting += 1;
    else if (phase !== "over" && phase !== "off") inPlay += 1;
    if (!newest || Date.parse(m.state_at) > Date.parse(newest)) newest = m.state_at;
  }
  return { inPlay, starting, newest };
}
