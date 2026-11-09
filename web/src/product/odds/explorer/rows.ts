/**
 * The board's rows: how old a row's prices are, the filters and orders the API applies (the in-memory data reproduces them
 * with these), the two the API does not have («Hoy», «Mis equipos y ligas»: kept on the client, over the pages loaded),
 * the groups the list is drawn in, the lines on offer, and which prices moved since the last update. Pure.
 */
import { t } from "@/lib/i18n";
import { toNumber } from "@/lib/i18n/format";
import { dayKey, formatRelative, formatTime } from "@/lib/time";
import { fold } from "@/product/matches/model";
import type { ExplorerFilters } from "./state";
import type {
  BoardSort,
  CompetitionBadge,
  ExplorerFollow,
  OddsBoardRow,
  OddsSelectionPrice,
} from "./model";

// ── freshness ─────────────────────────────────────────────────────────────────────────────────────────────────────────

export interface Freshness {
  /** A scheduled capture was missed (the shared rule, decided by the API): dimmed, out of the parlay. */
  stale: boolean;
  /** The chip: «hace 2 h», «Antiguo · hace 7 h». */
  text: string;
  /** Its hint: when it was captured, and when the provider last changed it. */
  title: string;
}

/** A row's age, from its own capture - never the newest price of the board (plan Cuotas, E3). */
export function rowFreshness(
  row: Pick<OddsBoardRow, "captured_at" | "provider_update_at" | "state">,
  now: number = Date.now(),
): Freshness {
  const stale = row.state === "stale";
  const age = formatRelative(row.captured_at, now);
  const text = stale ? t("explorer.fresh.stale", { age }) : age;
  const captured = t("explorer.fresh.captured", { time: formatTime(row.captured_at) });
  const provider = row.provider_update_at
    ? ` · ${t("explorer.fresh.provider", { time: formatTime(row.provider_update_at) })}`
    : "";
  const rule = stale ? ` · ${t("explorer.fresh.staleHelp")}` : "";
  return { stale, text, title: `${captured}${provider}${rule}` };
}

// ── what the API filters and orders (reproduced in memory by the fake data) ────────────────────────────────────────

/** The widest difference with the market's fair price among a row's prices; null without fair prices, or a stale row. */
export function rowEdge(row: Pick<OddsBoardRow, "selections" | "state">): number | null {
  if (row.state === "stale") return null;
  let best: number | null = null;
  for (const s of row.selections) {
    if (s.outlier) continue;
    const e = toNumber(s.price_edge);
    if (e !== null && (best === null || e > best)) best = e;
  }
  return best;
}

function countryKey(country: string | null | undefined): string {
  const name = (country ?? "").trim().toLowerCase();
  return name || "world";
}

/** Every word in a team's or the competition's name, accents and case aside. */
export function matchesText(
  row: Pick<OddsBoardRow, "home" | "away">,
  competition: Pick<CompetitionBadge, "name"> | undefined,
  query: string,
): boolean {
  const words = fold(query.trim()).split(/\s+/).filter(Boolean);
  if (words.length === 0) return true;
  const hay = fold(`${row.home.name} ${row.away.name} ${competition?.name ?? ""}`);
  return words.every((w) => hay.includes(w));
}

function inOddsRange(s: OddsSelectionPrice, min: number | null, max: number | null): boolean {
  const odds = toNumber(s.best_odds);
  if (odds === null) return false;
  return (min === null || odds >= min) && (max === null || odds <= max);
}

/**
 * The API's filters (`GET /odds/board`): text, country, competition, bookmaker (it quotes a best price of the row), at least
 * N bookmakers, a price in the range, only rows with a fair price. «Hoy» and «Mis equipos y ligas» are the client's.
 */
export function serverFilter(
  rows: readonly OddsBoardRow[],
  f: Omit<ExplorerFilters, "window" | "mine">,
  competitions: ReadonlyMap<number, CompetitionBadge>,
): OddsBoardRow[] {
  const min = toNumber(f.oddsMin);
  const max = toNumber(f.oddsMax);
  return rows.filter((row) => {
    const comp = competitions.get(row.competition_id);
    if (f.country !== null && countryKey(comp?.country) !== countryKey(f.country)) return false;
    if (f.competition !== null && row.competition_id !== f.competition) return false;
    if (!matchesText(row, comp, f.q)) return false;
    const sels = row.selections;
    if (f.bookmaker !== null && !sels.some((s) => s.bookmaker_id === f.bookmaker)) return false;
    if (f.minBooks !== null && !sels.some((s) => s.n_books >= (f.minBooks ?? 0))) return false;
    if ((min !== null || max !== null) && !sels.some((s) => inOddsRange(s, min, max))) return false;
    if (f.fairOnly && !sels.some((s) => toNumber(s.fair_odds) !== null)) return false;
    return true;
  });
}

const byKickoff = (a: OddsBoardRow, b: OddsBoardRow) =>
  Date.parse(a.kickoff_at) - Date.parse(b.kickoff_at) || a.fixture_id - b.fixture_id;

/**
 * The three orders: by kick-off; by competition (the PrediGol priority order, given as the competitions' ranks), then
 * kick-off; by the widest difference with the fair price - only rows that have one, never a stale row.
 */
export function sortRows(
  rows: readonly OddsBoardRow[],
  sort: BoardSort,
  rank: ReadonlyMap<number, number> = new Map(),
): OddsBoardRow[] {
  if (sort === "time") return [...rows].sort(byKickoff);
  if (sort === "competition") {
    const r = (row: OddsBoardRow) => rank.get(row.competition_id) ?? Number.MAX_SAFE_INTEGER;
    return [...rows].sort((a, b) => r(a) - r(b) || byKickoff(a, b));
  }
  return rows
    .filter((row) => rowEdge(row) !== null)
    .sort((a, b) => (rowEdge(b) ?? 0) - (rowEdge(a) ?? 0) || byKickoff(a, b));
}

// ── what only the client can filter ───────────────────────────────────────────────────────────────────────────────────

/** «Hoy»: kick-off on the reader's calendar day. */
export function isToday(kickoff: string, now: number = Date.now()): boolean {
  return dayKey(kickoff) === dayKey(now);
}

/** «Mis equipos y ligas»: a followed team plays, or it is a followed league. */
export function isMine(
  row: Pick<OddsBoardRow, "home" | "away" | "competition_id">,
  follow: ExplorerFollow,
): boolean {
  return (
    follow.teams.has(row.home.id) ||
    follow.teams.has(row.away.id) ||
    follow.leagues.has(row.competition_id)
  );
}

export function clientFilter(
  rows: readonly OddsBoardRow[],
  f: Pick<ExplorerFilters, "window" | "mine">,
  follow: ExplorerFollow | null,
  now: number = Date.now(),
): OddsBoardRow[] {
  return rows.filter(
    (row) =>
      (f.window !== "today" || isToday(row.kickoff_at, now)) &&
      (!f.mine || !follow || isMine(row, follow)),
  );
}

// ── groups ────────────────────────────────────────────────────────────────────────────────────────────────────────────

export interface RowGroup {
  key: string;
  kind: "day" | "competition" | "all";
  /** The day's first kick-off, or the competition's id. */
  at: string | null;
  competition: number | null;
  rows: OddsBoardRow[];
}

/** By kick-off: one group per local day; by competition: one per competition, in the order given; by difference: one. */
export function groupRows(rows: readonly OddsBoardRow[], sort: BoardSort): RowGroup[] {
  if (sort === "edge") {
    return rows.length
      ? [{ key: "all", kind: "all", at: null, competition: null, rows: [...rows] }]
      : [];
  }
  const groups: RowGroup[] = [];
  const index = new Map<string, RowGroup>();
  for (const row of rows) {
    const key =
      sort === "time" ? `day:${dayKey(row.kickoff_at)}` : `competition:${row.competition_id}`;
    let group = index.get(key);
    if (!group) {
      group = {
        key,
        kind: sort === "time" ? "day" : "competition",
        at: row.kickoff_at,
        competition: sort === "time" ? null : row.competition_id,
        rows: [],
      };
      index.set(key, group);
      groups.push(group);
    }
    group.rows.push(row);
  }
  return groups;
}

// ── lines ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

/** Two lines are the same line (decimals as text or numbers; none and none too). */
export function sameLine(
  a: string | number | null | undefined,
  b: string | number | null | undefined,
): boolean {
  const x = toNumber(a);
  const y = toNumber(b);
  if (x === null || y === null) return x === y;
  return Math.abs(x - y) < 1e-9;
}

/** Every line the rows on show have, low to high (each once): the chips beside «Principal». */
export function lineOptions(rows: readonly Pick<OddsBoardRow, "lines" | "line">[]): number[] {
  const seen = new Set<number>();
  for (const row of rows) {
    for (const l of [...row.lines, row.line]) {
      const n = toNumber(l);
      if (n !== null) seen.add(n === 0 ? 0 : n);
    }
  }
  return [...seen].sort((a, b) => a - b);
}

// ── price changes ─────────────────────────────────────────────────────────────────────────────────────────────────────

export type Move = "up" | "down";

/** One price of the board, whatever the page it came in: match, selection, player, line. */
export function priceKey(
  row: Pick<OddsBoardRow, "fixture_id">,
  s: Pick<OddsSelectionPrice, "selection" | "player" | "line">,
): string {
  return `${row.fixture_id}|${s.selection}|${s.player ?? ""}|${toNumber(s.line) ?? ""}`;
}

export function priceMap(rows: readonly OddsBoardRow[]): Map<string, number> {
  const out = new Map<string, number>();
  for (const row of rows) {
    for (const s of row.selections) {
      const odds = toNumber(s.best_odds);
      if (odds !== null) out.set(priceKey(row, s), odds);
    }
  }
  return out;
}

/** The prices that moved between two updates (a price new to the board did not move). */
export function priceMoves(
  before: ReadonlyMap<string, number>,
  after: ReadonlyMap<string, number>,
): Map<string, Move> {
  const out = new Map<string, Move>();
  for (const [key, odds] of after) {
    const was = before.get(key);
    if (was === undefined || Math.abs(was - odds) < 1e-9) continue;
    out.set(key, odds > was ? "up" : "down");
  }
  return out;
}
