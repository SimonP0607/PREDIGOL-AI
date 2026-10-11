/**
 * The Match Center's pure logic: phase, live state, best prices per line, in-play
 * prices, events, statistics, form and line-ups. No React here, so it can be tested.
 */
import type { MarketQuote, MatchSummary } from "@/lib/api/v1/types";
import type { PriceFreshness } from "@/lib/api/v1/types_product";
import type {
  Absence,
  H2HMatch,
  LineupPlayer,
  LiveQuote,
  LiveState,
  MatchEvent,
  PlayerLine,
  Side,
  StandingLine,
  TeamForm,
  TeamLineup,
  TeamStatLine,
} from "@/lib/api/v1/types_center";
import { intlTag, t, translateOr } from "@/lib/i18n";
import { fmtPct, toNumber } from "@/lib/i18n/format";
import { MARKETS, selectionLabel } from "@/product/shared/markets";

// ── Phase ───────────────────────────────────────────────────────────────────

export type Phase =
  | "scheduled"
  | "live"
  | "finished"
  | "awaiting"
  | "postponed"
  | "cancelled"
  | "abandoned"
  | "not_played";

/**
 * The Match Center's phase: the API's (fbi.core.match_state) when it sent one. A suspension is
 * shown in play (the header says "Susp."); an older API's answer falls back to the stored group.
 */
export function matchPhase(
  m: Pick<MatchSummary, "status_group" | "awaiting_result"> & Partial<Pick<MatchSummary, "phase">>,
): Phase {
  switch (m.phase) {
    case "scheduled":
    case "finished":
    case "awaiting":
    case "postponed":
    case "cancelled":
    case "abandoned":
    case "not_played":
      return m.phase;
    case "live":
    case "suspended":
      return "live";
    default:
      break;
  }
  if (m.status_group === "live") return "live";
  if (m.status_group === "finished") return "finished";
  if (m.status_group === "postponed") return "postponed";
  if (m.status_group === "cancelled") return "cancelled";
  return m.awaiting_result ? "awaiting" : "scheduled";
}

/** Not played to the end: nothing to show as a result, the bets void or wait for a human. */
export function notPlayed(phase: Phase): boolean {
  return (
    phase === "postponed" ||
    phase === "cancelled" ||
    phase === "abandoned" ||
    phase === "not_played"
  );
}

/** The second feed spells states out ("First Half"); the first uses short codes ("1H"). */
const FEED_STATUS: Record<string, string> = {
  "not started": "NS",
  "first half": "1H",
  halftime: "HT",
  "half time": "HT",
  "second half": "2H",
  "extra time": "ET",
  "break time": "BT",
  penalties: "P",
  "penalty in progress": "P",
  "match finished": "FT",
  finished: "FT",
  interrupted: "INT",
  suspended: "SUSP",
  abandoned: "ABD",
};

export function normalizeStatus(status: string): string {
  return FEED_STATUS[status.trim().toLowerCase()] ?? status;
}

export const FINISHED_CODES: ReadonlySet<string> = new Set(["FT", "AET", "PEN"]);
const AFTER_HALF_TIME = new Set(["HT", "2H", "ET", "BT", "P", "FT", "AET", "PEN"]);
const EXTRA_TIME = new Set(["ET", "BT", "P", "AET", "PEN"]);

// ── Live state ──────────────────────────────────────────────────────────────

export interface Goals {
  home: number;
  away: number;
}

export interface LiveSnapshot {
  status: string;
  elapsed: number | null;
  extra: number | null;
  goals: Goals | null;
  at: string;
}

function byNewest(a: LiveState, b: LiveState): number {
  return Date.parse(b.observed_at) - Date.parse(a.observed_at);
}

/** Minute and status from the newest observation; the score from the newest one that has it. */
export function liveSnapshot(states: readonly LiveState[]): LiveSnapshot | null {
  if (states.length === 0) return null;
  const sorted = [...states].sort(byNewest);
  const newest = sorted[0];
  if (!newest) return null;
  const scored = sorted.find((s) => s.goals_home !== null && s.goals_away !== null);
  return {
    status: normalizeStatus(newest.status),
    elapsed: newest.elapsed,
    extra: newest.extra,
    goals:
      scored && scored.goals_home !== null && scored.goals_away !== null
        ? { home: scored.goals_home, away: scored.goals_away }
        : null,
    at: newest.observed_at,
  };
}

/** The score observed at half-time, when the in-play states caught it. */
export function halfTimeFromStates(states: readonly LiveState[]): Goals | null {
  const ht = [...states]
    .sort(byNewest)
    .find(
      (s) => normalizeStatus(s.status) === "HT" && s.goals_home !== null && s.goals_away !== null,
    );
  return ht && ht.goals_home !== null && ht.goals_away !== null
    ? { home: ht.goals_home, away: ht.goals_away }
    : null;
}

/** Live: the in-play score first. Otherwise the recorded result, else what was seen in play. */
export function shownScore(
  m: Pick<MatchSummary, "score">,
  live: LiveSnapshot | null,
  phase: Phase,
): Goals | null {
  const recorded = m.score ? { home: m.score.home, away: m.score.away } : null;
  if (phase === "live" || phase === "awaiting") return live?.goals ?? recorded;
  if (phase === "finished") return recorded ?? live?.goals ?? null;
  return null;
}

export function reachedHalfTime(phase: Phase, status: string | null): boolean {
  if (phase === "finished") return true;
  return status !== null && AFTER_HALF_TIME.has(status);
}

export function reachedExtraTime(
  m: Pick<MatchSummary, "score" | "status_short">,
  status: string | null,
): boolean {
  if (m.score && (m.score.et_home !== null || m.score.pen_home !== null)) return true;
  if (EXTRA_TIME.has(m.status_short)) return true;
  return status !== null && EXTRA_TIME.has(status);
}

// ── Prices across bookmakers ────────────────────────────────────────────────

export const SELECTIONS: Record<string, readonly string[]> = {
  "1X2": ["Home", "Draw", "Away"],
  OU: ["Over", "Under"],
  BTTS: ["Yes", "No"],
  AH: ["Home", "Away"],
  DC: ["1X", "12", "X2"],
};

const LINE_MARKETS = new Set(["OU", "AH"]);

export interface BestPrice {
  market: string;
  selection: string;
  line: number;
  odds: string;
  bookmaker: string;
  /** Bookmakers quoting this selection at this line. */
  books: number;
  capturedAt: string;
}

/** The highest price per market, selection and line, with who offers it and how many quote it. */
export function bestPrices(
  quotes: readonly MarketQuote[],
  source: MarketQuote["source"],
): BestPrice[] {
  const groups = new Map<string, { best: MarketQuote; odds: number; books: Set<number> }>();
  for (const q of quotes) {
    if (q.source !== source) continue;
    const odds = toNumber(q.odds_decimal);
    if (odds === null || odds <= 1) continue;
    const line = toNumber(q.line) ?? 0;
    const key = `${q.market_key}|${q.selection}|${line}`;
    const g = groups.get(key);
    if (!g) {
      groups.set(key, { best: q, odds, books: new Set([q.bookmaker_id]) });
      continue;
    }
    g.books.add(q.bookmaker_id);
    if (odds > g.odds || (odds === g.odds && q.captured_at > g.best.captured_at)) {
      g.best = q;
      g.odds = odds;
    }
  }
  return [...groups.values()].map(({ best, books }) => ({
    market: best.market_key,
    selection: best.selection,
    line: toNumber(best.line) ?? 0,
    odds: best.odds_decimal,
    bookmaker: best.bookmaker,
    books: books.size,
    capturedAt: best.captured_at,
  }));
}

export interface PriceRow<T> {
  key: string;
  /** OU: the total; AH: the home side's handicap; null for single-line markets. */
  line: number | null;
  cells: Array<T | null>;
}

export interface MarketBoard {
  market: string;
  /** Different bookmakers quoting the market at all. */
  books: number;
  rows: Array<PriceRow<BestPrice>>;
  /** Index of the most balanced line: the one shown first. */
  main: number;
  updatedAt: string | null;
}

function oddsOf(cell: { odds: string | null } | null): number | null {
  return cell ? toNumber(cell.odds) : null;
}

/** The line whose two prices are closest to each other. */
function balancedIndex<T extends { odds: string | null }>(rows: Array<PriceRow<T>>): number {
  let best = -1;
  let bestGap = Infinity;
  rows.forEach((r, i) => {
    const a = oddsOf(r.cells[0] ?? null);
    const b = oddsOf(r.cells[1] ?? null);
    if (a === null || b === null || a <= 0 || b <= 0) return;
    const gap = Math.abs(Math.log(a / b));
    if (gap < bestGap) {
      bestGap = gap;
      best = i;
    }
  });
  return best;
}

/** Rows of a market: one row per line, the selections in their natural order. */
export function priceRows<T extends { selection: string; line: number }>(
  market: string,
  prices: readonly T[],
): Array<PriceRow<T>> {
  const order = SELECTIONS[market] ?? [];
  if (!LINE_MARKETS.has(market)) {
    const cells = order.map((sel) => prices.find((p) => p.selection === sel) ?? null);
    return cells.some((c) => c !== null) ? [{ key: market, line: null, cells }] : [];
  }
  const lines = new Map<number, Array<T | null>>();
  for (const p of prices) {
    // AH: "Away +1.5" sits on the same row as "Home -1.5".
    const rowLine = market === "AH" && p.selection === "Away" ? -p.line : p.line;
    const idx = order.indexOf(p.selection);
    if (idx < 0) continue;
    const key = Math.round(rowLine * 100) / 100;
    const cells = lines.get(key) ?? order.map(() => null);
    cells[idx] = p;
    lines.set(key, cells);
  }
  return [...lines.entries()]
    .sort(([a], [b]) => a - b)
    .map(([line, cells]) => ({ key: `${market}|${line}`, line, cells }));
}

export function marketBoards(
  quotes: readonly MarketQuote[],
  source: MarketQuote["source"],
): MarketBoard[] {
  const prices = bestPrices(quotes, source);
  const boards: MarketBoard[] = [];
  for (const market of MARKETS) {
    const mine = prices.filter((p) => p.market === market);
    const rows = priceRows(market, mine);
    if (rows.length === 0) continue;
    const books = new Set(
      quotes
        .filter((q) => q.source === source && q.market_key === market)
        .map((q) => q.bookmaker_id),
    ).size;
    const balanced = balancedIndex(rows);
    const main =
      balanced >= 0
        ? balanced
        : rows.reduce((bi, r, i, all) => (rowBooks(r) > rowBooks(all[bi] ?? r) ? i : bi), 0);
    const updatedAt = mine.reduce<string | null>(
      (acc, p) => (acc === null || p.capturedAt > acc ? p.capturedAt : acc),
      null,
    );
    boards.push({ market, books, rows, main, updatedAt });
  }
  return boards;
}

function rowBooks(r: PriceRow<BestPrice>): number {
  return r.cells.reduce((n, c) => n + (c?.books ?? 0), 0);
}

/** A window of rows around the main line; all of them when expanded. */
export function visibleRows<T>(rows: readonly T[], main: number, expanded: boolean, size = 5): T[] {
  if (expanded || rows.length <= size) return [...rows];
  const start = Math.min(Math.max(0, main - Math.floor(size / 2)), rows.length - size);
  return rows.slice(start, start + size);
}

export function latestCapture(quotes: readonly MarketQuote[], source: MarketQuote["source"]) {
  return quotes.reduce<string | null>(
    (acc, q) =>
      q.source === source && (acc === null || q.captured_at > acc) ? q.captured_at : acc,
    null,
  );
}

// ── In-play prices (one source, no bookmaker dimension) ─────────────────────

export interface LivePrice {
  selection: string;
  line: number;
  /** Null: withdrawn by the bookmaker at this instant. */
  odds: string | null;
  suspended: boolean;
  main: boolean;
  at: string;
  minute: number | null;
}

export interface LiveMarket {
  market: string;
  rows: Array<PriceRow<LivePrice>>;
  main: number;
  at: string | null;
}

export function liveMarkets(quotes: readonly LiveQuote[]): LiveMarket[] {
  const out: LiveMarket[] = [];
  for (const market of MARKETS) {
    const prices: LivePrice[] = quotes
      .filter((q) => q.market_key === market)
      .map((q) => ({
        selection: q.selection,
        line: toNumber(q.line) ?? 0,
        odds: q.odds,
        suspended: q.suspended,
        main: q.main_line === true,
        at: q.captured_at,
        minute: q.minute,
      }));
    const all = priceRows(market, prices);
    const rows = all.filter(
      (r) => r.cells.some((c) => c !== null && c.odds !== null) || r.cells.some((c) => c?.main),
    );
    if (rows.length === 0) continue;
    const flagged = rows.findIndex((r) => r.cells.some((c) => c?.main));
    const balanced = balancedIndex(rows);
    const main = flagged >= 0 ? flagged : balanced >= 0 ? balanced : 0;
    const at = prices.reduce<string | null>(
      (acc, p) => (acc === null || p.at > acc ? p.at : acc),
      null,
    );
    out.push({ market, rows, main, at });
  }
  return out;
}

// ── Events ──────────────────────────────────────────────────────────────────

export type EventKind =
  | "goal"
  | "ownGoal"
  | "penalty"
  | "missedPenalty"
  | "yellow"
  | "secondYellow"
  | "red"
  | "sub"
  | "var"
  | "other";

export function eventKind(e: Pick<MatchEvent, "type" | "detail">): EventKind {
  const type = e.type.trim().toLowerCase();
  const detail = (e.detail ?? "").toLowerCase();
  if (type === "goal") {
    if (detail.includes("own")) return "ownGoal";
    if (detail.includes("missed")) return "missedPenalty";
    if (detail.includes("penalty")) return "penalty";
    return "goal";
  }
  if (type === "card") {
    if (detail.includes("second")) return "secondYellow";
    if (detail.includes("red")) return "red";
    if (detail.includes("yellow")) return "yellow";
    return "other";
  }
  if (type === "subst" || type === "substitution") return "sub";
  if (type === "var") return "var";
  return "other";
}

export function isScoring(kind: EventKind): boolean {
  return kind === "goal" || kind === "ownGoal" || kind === "penalty";
}

function eventOrder(e: MatchEvent): number {
  return e.minute * 100 + (e.extra_minute ?? 0);
}

export function chronological(events: readonly MatchEvent[]): MatchEvent[] {
  return [...events].sort((a, b) => eventOrder(a) - eventOrder(b) || a.seq - b.seq);
}

export const other = (side: Side): Side => (side === "home" ? "away" : "home");

/**
 * Which side each goal counts for. The provider files an own goal under one of the
 * two teams; which one is checked against the score. `reliable`: the goals add up to it.
 */
export function goalCredit(
  events: readonly MatchEvent[],
  score: Goals | null,
): { credit: Map<number, Side>; reliable: boolean } {
  const scoring = chronological(events).filter((e) => e.side !== null && isScoring(eventKind(e)));
  const attempt = (ownGoalForOther: boolean) => {
    const credit = new Map<number, Side>();
    const tally: Goals = { home: 0, away: 0 };
    for (const e of scoring) {
      const side = e.side as Side;
      const to = eventKind(e) === "ownGoal" && ownGoalForOther ? other(side) : side;
      credit.set(e.seq, to);
      tally[to] += 1;
    }
    return { credit, ok: score !== null && tally.home === score.home && tally.away === score.away };
  };
  const hasOwnGoal = scoring.some((e) => eventKind(e) === "ownGoal");
  const asFiled = attempt(false);
  if (!hasOwnGoal) return { credit: asFiled.credit, reliable: asFiled.ok };
  const flipped = attempt(true);
  if (flipped.ok && !asFiled.ok) return { credit: flipped.credit, reliable: true };
  if (asFiled.ok && !flipped.ok) return { credit: asFiled.credit, reliable: true };
  // Cannot tell: own goals are left out of any per-side count.
  const credit = new Map([...asFiled.credit].filter(([seq]) => !ownGoalSeq(scoring, seq)));
  return { credit, reliable: false };
}

function ownGoalSeq(scoring: readonly MatchEvent[], seq: number): boolean {
  return scoring.some((e) => e.seq === seq && eventKind(e) === "ownGoal");
}

/** For a substitution: is `player` the one coming on? Told by the line-ups, else unknown. */
export function subDirection(
  e: Pick<MatchEvent, "player_id">,
  lineups: readonly TeamLineup[] | null,
): "playerIn" | "playerOut" | null {
  if (e.player_id === null || !lineups) return null;
  for (const l of lineups) {
    const p = l.players.find((x) => x.player_id === e.player_id);
    if (p) return p.starter ? "playerOut" : "playerIn";
  }
  return null;
}

export type TimelineItem =
  | { kind: "event"; event: MatchEvent; running: Goals | null }
  | { kind: "divider"; label: "ht" | "et" | "ft"; score: Goals | null };

/**
 * Events in order with the half-time, extra-time and full-time marks between them.
 * The running score is only attached when the goals add up to the known score.
 */
export function timeline(
  events: readonly MatchEvent[],
  opts: {
    score: Goals | null;
    halfTime: Goals | null;
    reachedHalfTime: boolean;
    reachedExtraTime: boolean;
    finished: boolean;
    newestFirst: boolean;
  },
): TimelineItem[] {
  const { credit, reliable } = goalCredit(events, opts.score);
  const items: TimelineItem[] = [];
  const tally: Goals = { home: 0, away: 0 };
  let htDone = false;
  let etDone = false;
  const ht = (): TimelineItem => ({ kind: "divider", label: "ht", score: opts.halfTime });
  for (const e of chronological(events)) {
    if (!htDone && e.minute > 45) {
      items.push(ht());
      htDone = true;
    }
    if (!etDone && e.minute > 90) {
      items.push({ kind: "divider", label: "et", score: null });
      etDone = true;
    }
    let running: Goals | null = null;
    const to = credit.get(e.seq);
    if (to && isScoring(eventKind(e))) {
      tally[to] += 1;
      running = reliable ? { ...tally } : null;
    }
    items.push({ kind: "event", event: e, running });
  }
  if (!htDone && opts.reachedHalfTime) items.push(ht());
  if (!etDone && opts.reachedExtraTime) items.push({ kind: "divider", label: "et", score: null });
  if (opts.finished) items.push({ kind: "divider", label: "ft", score: opts.score });
  return opts.newestFirst ? items.reverse() : items;
}

/** Goal scorers per side for the header: "J. van de Haar 28'". */
export function scorers(
  events: readonly MatchEvent[],
  score: Goals | null,
): Record<Side, Array<{ seq: number; name: string; minute: string; kind: EventKind }>> {
  const { credit } = goalCredit(events, score);
  const out: Record<Side, Array<{ seq: number; name: string; minute: string; kind: EventKind }>> = {
    home: [],
    away: [],
  };
  for (const e of chronological(events)) {
    const kind = eventKind(e);
    const to = credit.get(e.seq);
    if (!isScoring(kind) || !to) continue;
    out[to].push({
      seq: e.seq,
      name: e.player ?? t("match.events.unknownPlayer"),
      minute: minuteText(e.minute, e.extra_minute),
      kind,
    });
  }
  return out;
}

export function minuteText(minute: number | null, extra: number | null): string {
  if (minute === null) return "—";
  return extra ? `${minute}+${extra}'` : `${minute}'`;
}

// ── Statistics ──────────────────────────────────────────────────────────────

export type StatFormat = "int" | "pct" | "dec2";

export interface StatDef {
  key: string;
  format: StatFormat;
  read: (l: TeamStatLine) => number | null;
}

const field =
  (k: keyof TeamStatLine) =>
  (l: TeamStatLine): number | null => {
    const v = l[k];
    if (v === null || typeof v === "boolean") return null;
    return toNumber(v);
  };

export const STAT_DEFS: readonly StatDef[] = [
  { key: "possession", format: "pct", read: field("possession_pct") },
  { key: "xg", format: "dec2", read: field("expected_goals") },
  { key: "shots", format: "int", read: field("shots") },
  { key: "shotsOnTarget", format: "int", read: field("shots_on_target") },
  { key: "shotsOffTarget", format: "int", read: field("shots_off_target") },
  { key: "shotsBlocked", format: "int", read: field("shots_blocked") },
  { key: "shotsInsideBox", format: "int", read: field("shots_inside_box") },
  { key: "shotsOutsideBox", format: "int", read: field("shots_outside_box") },
  { key: "corners", format: "int", read: field("corners") },
  { key: "fouls", format: "int", read: field("fouls") },
  { key: "offsides", format: "int", read: field("offsides") },
  { key: "yellowCards", format: "int", read: field("yellow_cards") },
  { key: "redCards", format: "int", read: field("red_cards") },
  { key: "saves", format: "int", read: field("saves") },
  { key: "passes", format: "int", read: field("passes") },
  { key: "passesAccurate", format: "int", read: field("passes_accurate") },
  {
    key: "passAccuracy",
    format: "pct",
    read: (l) =>
      l.passes && l.passes > 0 && l.passes_accurate !== null
        ? (l.passes_accurate / l.passes) * 100
        : null,
  },
];

export const KEY_STATS = ["possession", "xg", "shots", "shotsOnTarget", "corners", "yellowCards"];

export interface StatRow {
  key: string;
  format: StatFormat;
  home: number | null;
  away: number | null;
}

export function statRows(lines: readonly TeamStatLine[], keys?: readonly string[]): StatRow[] {
  const home = lines.find((l) => l.side === "home");
  const away = lines.find((l) => l.side === "away");
  const defs = keys ? STAT_DEFS.filter((d) => keys.includes(d.key)) : STAT_DEFS;
  return defs
    .map((d) => ({
      key: d.key,
      format: d.format,
      home: home ? d.read(home) : null,
      away: away ? d.read(away) : null,
    }))
    .filter((r) => r.home !== null || r.away !== null);
}

/** Season numbers from the league table, per match where that is the fair comparison. */
export function seasonRows(
  home: StandingLine | undefined,
  away: StandingLine | undefined,
): StatRow[] {
  if (!home || !away) return [];
  const per = (n: number, played: number) => (played > 0 ? n / played : null);
  return [
    {
      key: "pointsPerGame",
      format: "dec2" as const,
      home: per(home.points, home.played),
      away: per(away.points, away.played),
    },
    {
      key: "goalsForPerGame",
      format: "dec2" as const,
      home: per(home.goals_for, home.played),
      away: per(away.goals_for, away.played),
    },
    {
      key: "goalsAgainstPerGame",
      format: "dec2" as const,
      home: per(home.goals_against, home.played),
      away: per(away.goals_against, away.played),
    },
    { key: "wins", format: "int" as const, home: home.wins, away: away.wins },
    { key: "draws", format: "int" as const, home: home.draws, away: away.draws },
    { key: "losses", format: "int" as const, home: home.losses, away: away.losses },
  ].filter((r) => r.home !== null || r.away !== null);
}

// ── Form ────────────────────────────────────────────────────────────────────

export type ResultLetter = "W" | "D" | "L";

export interface FormChip {
  result: ResultLetter;
  opponent: string | null;
  venue: "H" | "A" | null;
  goalsFor: number | null;
  goalsAgainst: number | null;
  at: string | null;
  fixtureId: number | null;
}

function latestMatches(form: TeamForm | undefined, n: number) {
  if (!form) return [];
  return [...form.matches]
    .sort((a, b) => Date.parse(b.kickoff_at) - Date.parse(a.kickoff_at))
    .slice(0, n);
}

/**
 * The last five results, oldest first (the newest on the right). From the stored
 * matches; else from the table's form string, which the provider writes newest first.
 */
export function lastFive(
  form: TeamForm | undefined,
  standing: StandingLine | undefined,
): FormChip[] {
  const matches = latestMatches(form, 5);
  if (matches.length > 0) {
    return matches.reverse().map((m) => ({
      result: m.result,
      opponent: m.opponent,
      venue: m.venue,
      goalsFor: m.goals_for,
      goalsAgainst: m.goals_against,
      at: m.kickoff_at,
      fixtureId: m.fixture_id,
    }));
  }
  const letters = (standing?.form ?? "")
    .toUpperCase()
    .split("")
    .filter((x): x is ResultLetter => x === "W" || x === "D" || x === "L")
    .slice(0, 5);
  return letters.reverse().map((result) => ({
    result,
    opponent: null,
    venue: null,
    goalsFor: null,
    goalsAgainst: null,
    at: null,
    fixtureId: null,
  }));
}

// ── Head to head ────────────────────────────────────────────────────────────

export function h2hSummary(
  rows: readonly H2HMatch[],
  home: string,
  away: string,
): { homeWins: number; draws: number; awayWins: number; counted: number } {
  let homeWins = 0;
  let draws = 0;
  let awayWins = 0;
  for (const r of rows) {
    const names = [r.home, r.away];
    if (!names.includes(home) || !names.includes(away)) continue;
    if (r.goals_home === r.goals_away) draws += 1;
    else {
      const winner = r.goals_home > r.goals_away ? r.home : r.away;
      if (winner === home) homeWins += 1;
      else awayWins += 1;
    }
  }
  return { homeWins, draws, awayWins, counted: homeWins + draws + awayWins };
}

// ── Players ─────────────────────────────────────────────────────────────────

/** Players who played and were rated, best first. */
export function ratedPlayers(players: readonly PlayerLine[]): PlayerLine[] {
  return players
    .filter((p) => (p.minutes ?? 0) > 0 && (toNumber(p.rating) ?? 0) > 0)
    .sort((a, b) => (toNumber(b.rating) ?? 0) - (toNumber(a.rating) ?? 0));
}

// ── Line-ups ────────────────────────────────────────────────────────────────

export function parseGrid(grid: string | null): { row: number; col: number } | null {
  if (!grid) return null;
  const m = /^(\d+):(\d+)$/.exec(grid.trim());
  if (!m) return null;
  return { row: Number(m[1]), col: Number(m[2]) };
}

const POS_ORDER: Record<string, number> = { G: 0, D: 1, M: 2, F: 3 };

export function starters(lineup: TeamLineup): LineupPlayer[] {
  return lineup.players
    .filter((p) => p.starter)
    .sort((a, b) => {
      const ga = parseGrid(a.grid);
      const gb = parseGrid(b.grid);
      if (ga && gb) return ga.row - gb.row || ga.col - gb.col;
      return (POS_ORDER[a.position ?? ""] ?? 9) - (POS_ORDER[b.position ?? ""] ?? 9);
    });
}

export function bench(lineup: TeamLineup): LineupPlayer[] {
  return lineup.players
    .filter((p) => !p.starter)
    .sort(
      (a, b) =>
        (POS_ORDER[a.position ?? ""] ?? 9) - (POS_ORDER[b.position ?? ""] ?? 9) ||
        (a.number ?? 999) - (b.number ?? 999),
    );
}

export interface PitchSpot {
  player: LineupPlayer;
  /** 0-100, left to right as the reader sees the pitch. */
  x: number;
  /** 0-100, top to bottom. */
  y: number;
}

/**
 * Where each starter stands. The home side defends the bottom goal and attacks up; the
 * provider numbers columns from each team's own left, so the away side is mirrored.
 * Null when any starter has no grid position.
 */
export function pitchSpots(lineup: TeamLineup, half: "bottom" | "top"): PitchSpot[] | null {
  const xi = lineup.players.filter((p) => p.starter);
  if (xi.length === 0) return null;
  const placed = xi.map((p) => ({ p, g: parseGrid(p.grid) }));
  if (placed.some((x) => x.g === null)) return null;
  const rows = new Map<number, Array<{ p: LineupPlayer; col: number }>>();
  for (const { p, g } of placed) {
    if (!g) continue;
    rows.set(g.row, [...(rows.get(g.row) ?? []), { p, col: g.col }]);
  }
  const rowKeys = [...rows.keys()].sort((a, b) => a - b);
  const depth = rowKeys.length;
  const spots: PitchSpot[] = [];
  rowKeys.forEach((rowKey, ri) => {
    const line = (rows.get(rowKey) ?? []).sort((a, b) => a.col - b.col);
    const tDepth = depth > 1 ? ri / (depth - 1) : 0;
    const fromOwnGoal = 7 + tDepth * 36;
    const y = half === "bottom" ? 100 - fromOwnGoal : fromOwnGoal;
    line.forEach(({ p }, i) => {
      const across = ((i + 0.5) / line.length) * 100;
      spots.push({ player: p, x: half === "bottom" ? across : 100 - across, y });
    });
  });
  return spots;
}

/** "M. Spenkelink" -> "Spenkelink" for the small pitch labels. */
export function pitchName(name: string | null): string {
  if (!name) return "";
  return name.replace(/^(?:\p{Lu}\.\s*)+/u, "").trim() || name;
}

// ── Absences ────────────────────────────────────────────────────────────────

export type AbsenceKind = "missing" | "questionable" | "other";
export type AbsenceReason = "injury" | "suspension" | "illness" | "other";

export function absenceKind(a: Pick<Absence, "type">): AbsenceKind {
  const v = (a.type ?? "").toLowerCase();
  if (v.includes("missing")) return "missing";
  if (v.includes("question") || v.includes("doubt")) return "questionable";
  return "other";
}

export function absenceReason(reason: string | null): AbsenceReason {
  const v = (reason ?? "").toLowerCase();
  if (/suspen|card|ban/.test(v)) return "suspension";
  if (/ill|sick|virus|flu|covid/.test(v)) return "illness";
  if (
    /injur|knock|strain|sprain|fractur|broken|tear|ligament|muscle|surgery|hamstring|knee|ankle|calf|groin|thigh|foot|back|shoulder|concussion|achilles|hip/.test(
      v,
    )
  )
    return "injury";
  return "other";
}

// ── Labels ──────────────────────────────────────────────────────────────────

function slug(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "");
}

function stageLabel(s: string): string {
  const known = translateOr(`match.round.stage.${slug(s)}`, "");
  if (known) return known;
  const patterns: Array<[RegExp, string, string]> = [
    [/^Group\s+(.+)$/i, "match.round.group", "name"],
    [/^League\s+([A-Z])$/i, "match.round.league", "name"],
    [/^(\d+)(?:st|nd|rd|th)\s+Round\s+Qualifying$/i, "match.round.qualifying", "n"],
    [/^(\d+)(?:st|nd|rd|th)\s+Preliminary\s+Round$/i, "match.round.preliminary", "n"],
    [/^(\d+)(?:st|nd|rd|th)\s+Round$/i, "match.round.round", "n"],
    [/^1\/(\d+)-finals?$/i, "match.round.fraction", "n"],
  ];
  for (const [re, key, name] of patterns) {
    const m = re.exec(s);
    if (m) return t(key, { [name]: m[1] });
  }
  return s;
}

/** "Regular Season - 31" -> "Jornada 31"; "Clausura - 11" -> "Clausura · Jornada 11". */
export function roundLabel(round: string | null): string | null {
  if (!round) return null;
  const r = round.trim();
  const season = /^Regular Season\s*-\s*(\d+)$/i.exec(r);
  if (season) return t("match.round.matchday", { n: season[1] });
  const staged = /^(.+?)\s*-\s*(\d+)$/.exec(r);
  if (staged && staged[1]) {
    return `${stageLabel(staged[1])} · ${t("match.round.matchday", { n: staged[2] })}`;
  }
  return stageLabel(r);
}

/** How a selection is named in a tile: team names for 1X2, short forms where a title says the rest. */
export function tileLabel(
  market: string,
  selection: string,
  line: number | null,
  sides: { home: string; away: string },
): string {
  if (market === "1X2") {
    if (selection === "Home") return sides.home;
    if (selection === "Away") return sides.away;
    return t("common.draw");
  }
  const short = market === "BTTS" || market === "OU";
  return selectionLabel(
    { market_key: market, selection, line: line ?? 0, home: sides.home, away: sides.away },
    short,
  );
}

/** How old a price or an in-play state is, on the product's freshness scale (minutes). */
export function ageLevel(
  at: string | null,
  freshMinutes: number,
  agingMinutes: number,
  now: number = Date.now(),
): PriceFreshness {
  if (!at) return "none";
  const age = (now - Date.parse(at)) / 60_000;
  if (!Number.isFinite(age)) return "none";
  return age <= freshMinutes ? "fresh" : age <= agingMinutes ? "aging" : "stale";
}

/** A compact scorer name: "Jesse van de Haar" -> "van de Haar", "J. Nap" -> "Nap". */
export function scorerName(name: string): string {
  const full = name.trim();
  const noInitials = full.replace(/^(?:\p{Lu}\.\s*)+/u, "").trim();
  if (noInitials !== full) return noInitials || full;
  const parts = full.split(/\s+/);
  return parts.length >= 2 ? parts.slice(1).join(" ") : full;
}

/** 1,25 / 7,8 in the reader's language. */
export function fmtDecimal(value: number | null | undefined, digits: number): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat(intlTag(), {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

export function fmtStat(value: number | null, format: StatFormat): string {
  if (value === null) return "—";
  if (format === "pct") return fmtPct(value / 100, 0);
  if (format === "dec2") return fmtDecimal(value, 2);
  return fmtDecimal(value, 0);
}

export function capitalize(s: string): string {
  return s ? s.charAt(0).toLocaleUpperCase(intlTag()) + s.slice(1) : s;
}
