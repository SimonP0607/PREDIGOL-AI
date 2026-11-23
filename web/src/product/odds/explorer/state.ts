/**
 * The explorer's state as it lives in the URL (plan Cuotas, section 5: «familia, mercado, periodo, línea y filtros viven en
 * la URL: se comparten y "atrás" funciona»). One serializable object, short keys, defaults left out; parsing is lenient - a
 * value that does not read is its default, never an error - and a round trip gives the same object back. Pure.
 *
 * The route wiring comes later: its `validateSearch` is `parseExplorerSearch`, and the explorer's `onStateChange` navigates
 * with `serializeExplorerState`.
 */
import { isTabKey, type ExplorerView, type TabKey } from "./tabs";
import type { BoardQuery, BoardSort, DayKey, FamiliesQuery } from "./model";

/**
 * «Día»: Hoy, Mañana or Pasado mañana, cut by the server on the Bogota calendar (AP-C01). The next 48 or 72 hours stay only
 * so a link written before them still opens; no chip offers them.
 */
export type ExplorerWindow = DayKey | 48 | 72;
export const DAY_KEYS: readonly DayKey[] = ["today", "tomorrow", "day_after"];
export const WINDOWS: readonly ExplorerWindow[] = DAY_KEYS;
export const SORTS: readonly BoardSort[] = ["time", "competition", "edge"];
const PERIODS = ["FT", "1H", "2H", "INTERVAL"];

export interface ExplorerFilters {
  window: ExplorerWindow;
  /** Team or competition names (the market names a search finds are a jump, never a filter). */
  q: string;
  /** A competition's country as the badges name it ("England", "World"). */
  country: string | null;
  competition: number | null;
  bookmaker: number | null;
  /** «Rango de cuota»: decimals as text ("1.5"). */
  oddsMin: string | null;
  oddsMax: string | null;
  minBooks: number | null;
  /** «Solo con cuota justa». */
  fairOnly: boolean;
  /** «Mis equipos y ligas». */
  mine: boolean;
}

export interface ExplorerState extends ExplorerFilters {
  /** Null: the first tab with data. */
  tab: TabKey | null;
  market: string | null;
  period: string | null;
  /** "main" (each match at its main line) or a decimal: "2.5", "-0.25". */
  line: string;
  sort: BoardSort;
}

export const NO_FILTERS: ExplorerFilters = {
  window: "today",
  q: "",
  country: null,
  competition: null,
  bookmaker: null,
  oddsMin: null,
  oddsMax: null,
  minBooks: null,
  fairOnly: false,
  mine: false,
};

export const DEFAULT_EXPLORER_STATE: ExplorerState = {
  ...NO_FILTERS,
  tab: null,
  market: null,
  period: null,
  line: "main",
  sort: "time",
};

/** A URL value as a router hands it: text, a number or a boolean (JSON search), or a list (a repeated key). */
function scalar(value: unknown): string | null {
  const v = Array.isArray(value) ? value[0] : value;
  if (typeof v === "string") return v;
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  if (typeof v === "boolean") return v ? "1" : "0";
  return null;
}

function text(value: unknown, max: number): string | null {
  const s = scalar(value)?.trim();
  return s ? s.slice(0, max) : null;
}

function positiveInt(value: unknown, max = 1e9): number | null {
  const s = scalar(value);
  if (s === null || !/^\d+$/.test(s)) return null;
  const n = Number(s);
  return n >= 1 && n <= max ? n : null;
}

function flag(value: unknown): boolean {
  const s = scalar(value);
  return s === "1" || s === "true";
}

/** A line: a multiple of 0.25 under 1000 either way, as its shortest text ("2.5", "-0.25", "0"); null otherwise. */
export function normalizeLine(value: unknown): string | null {
  const s = scalar(value);
  if (s === null || s.trim() === "") return null;
  const n = Number(s);
  if (!Number.isFinite(n) || Math.abs(n) >= 1000 || Math.round(n * 4) !== n * 4) return null;
  return String(n === 0 ? 0 : n);
}

/** A price bound: above 1 and up to 1000, to two decimals ("1.5"); null otherwise. */
export function normalizeOdds(value: unknown): string | null {
  const s = scalar(value);
  if (s === null || s.trim() === "") return null;
  const n = Number(s.replace(",", "."));
  if (!Number.isFinite(n) || n <= 1 || n > 1000) return null;
  return String(Math.round(n * 100) / 100);
}

function windowOf(value: unknown): ExplorerWindow {
  const s = scalar(value);
  if (s === "today" || s === "tomorrow" || s === "day_after") return s;
  const n = Number(s);
  return n === 48 || n === 72 ? n : "today"; // an old h=24 was the default: it is «Hoy» now
}

/** The URL's search -> the state. Anything unknown or malformed reads as its default. */
export function parseExplorerSearch(search: Readonly<Record<string, unknown>>): ExplorerState {
  const tab = scalar(search["f"]);
  const market = text(search["m"], 80);
  const period = scalar(search["p"]);
  const sort = scalar(search["sort"]);
  let oddsMin = normalizeOdds(search["min"]);
  let oddsMax = normalizeOdds(search["max"]);
  if (oddsMin !== null && oddsMax !== null && Number(oddsMin) > Number(oddsMax)) {
    [oddsMin, oddsMax] = [oddsMax, oddsMin];
  }
  return {
    tab: isTabKey(tab) ? tab : null,
    market: market !== null && /^[a-z0-9_.]+$/.test(market) ? market : null,
    period: period !== null && PERIODS.includes(period) ? period : null,
    line: normalizeLine(search["l"]) ?? "main",
    window: windowOf(search["h"]),
    q: (scalar(search["q"]) ?? "").slice(0, 80),
    country: text(search["c"], 60),
    competition: positiveInt(search["comp"]),
    bookmaker: positiveInt(search["bk"]),
    oddsMin,
    oddsMax,
    minBooks: positiveInt(search["nb"], 50),
    fairOnly: flag(search["fair"]),
    mine: flag(search["mine"]),
    sort: SORTS.includes(sort as BoardSort) ? (sort as BoardSort) : "time",
  };
}

/** The state -> the URL's search: short keys, in a fixed order, the defaults left out (an empty object is the default state). */
export function serializeExplorerState(state: ExplorerState): Record<string, string> {
  const out: Record<string, string> = {};
  if (state.tab) out["f"] = state.tab;
  if (state.market) out["m"] = state.market;
  if (state.period) out["p"] = state.period;
  const line = normalizeLine(state.line);
  if (line !== null) out["l"] = line;
  if (state.window !== "today") out["h"] = String(state.window);
  if (state.q.trim()) out["q"] = state.q.trim();
  if (state.country) out["c"] = state.country;
  if (state.competition !== null) out["comp"] = String(state.competition);
  if (state.bookmaker !== null) out["bk"] = String(state.bookmaker);
  if (state.oddsMin) out["min"] = state.oddsMin;
  if (state.oddsMax) out["max"] = state.oddsMax;
  if (state.minBooks !== null) out["nb"] = String(state.minBooks);
  if (state.fairOnly) out["fair"] = "1";
  if (state.mine) out["mine"] = "1";
  if (state.sort !== "time") out["sort"] = state.sort;
  return out;
}

/** The hours the API is asked for: a day asks for none (it names the day), an old link's 48 or 72 asks for them. */
export function windowHours(window: ExplorerWindow): number {
  return typeof window === "number" ? window : 24;
}

/** The day the API is asked for, or null for an old link's hours. */
export function windowDay(window: ExplorerWindow): DayKey | null {
  return typeof window === "number" ? null : window;
}

export function familiesQuery(state: ExplorerState): FamiliesQuery {
  return {
    hours: windowHours(state.window),
    day: windowDay(state.window),
    country: state.country,
    competition: state.competition,
  };
}

export function boardQuery(state: ExplorerState, view: ExplorerView | null): BoardQuery {
  return {
    ...familiesQuery(state),
    market: view?.market.key ?? "",
    period: view?.period ?? "FT",
    line: view?.line ?? "main",
    q: state.q.trim(),
    bookmaker: state.bookmaker,
    min_books: state.minBooks,
    odds_min: state.oddsMin,
    odds_max: state.oddsMax,
    fair_only: state.fairOnly,
    sort: state.sort,
  };
}

// ── what a choice does to the state (the URL changes with it; the route only writes it down) ─────────────────────────

/** Another tab: it opens on `market` (its last used, chosen by the caller), its own period and its main line. */
export function withTab(state: ExplorerState, tab: TabKey, market: string | null): ExplorerState {
  return { ...state, tab, market, period: null, line: "main" };
}

/** Another market of the tab: the period stays where it can (the first half of one market, then of the next), the main line. */
export function withMarket(
  state: ExplorerState,
  tab: TabKey,
  market: string,
  periods: readonly string[],
): ExplorerState {
  const period = state.period !== null && periods.includes(state.period) ? state.period : null;
  return { ...state, tab, market, period, line: "main" };
}

export function withPeriod(state: ExplorerState, period: string): ExplorerState {
  return { ...state, period, line: "main" };
}

export function withLine(state: ExplorerState, line: string): ExplorerState {
  return { ...state, line: normalizeLine(line) ?? "main" };
}

export function withFilters(
  state: ExplorerState,
  filters: Partial<ExplorerFilters>,
): ExplorerState {
  return { ...state, ...filters };
}

/** «Borrar filtros»: every filter back to its default; the tab, market, period, line and order stay. */
export function clearFilters(state: ExplorerState): ExplorerState {
  return { ...state, ...NO_FILTERS, window: state.window };
}

/** How many filters are on (the window is not one: it is always set). */
export function activeFilters(f: ExplorerFilters): number {
  return (
    (f.q.trim() ? 1 : 0) +
    (f.country !== null ? 1 : 0) +
    (f.competition !== null ? 1 : 0) +
    (f.bookmaker !== null ? 1 : 0) +
    (f.oddsMin !== null || f.oddsMax !== null ? 1 : 0) +
    (f.minBooks !== null ? 1 : 0) +
    (f.fairOnly ? 1 : 0) +
    (f.mine ? 1 : 0)
  );
}

export function filtersOf(state: ExplorerState): ExplorerFilters {
  return {
    window: state.window,
    q: state.q,
    country: state.country,
    competition: state.competition,
    bookmaker: state.bookmaker,
    oddsMin: state.oddsMin,
    oddsMax: state.oddsMax,
    minBooks: state.minBooks,
    fairOnly: state.fairOnly,
    mine: state.mine,
  };
}
