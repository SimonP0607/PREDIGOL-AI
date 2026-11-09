/// <reference types="bun" />
/**
 * The explorer's state in the URL: family, market, period, line, filters and order as one serializable object; a round trip
 * gives it back (through a query string too), a malformed value reads as its default, and every choice does what the plan
 * says to the rest (another tab: its own period and main line; another market: the period kept where it can).
 */
import { describe, expect, test } from "bun:test";
import {
  DEFAULT_EXPLORER_STATE,
  activeFilters,
  boardQuery,
  clearFilters,
  familiesQuery,
  filtersOf,
  normalizeLine,
  normalizeOdds,
  parseExplorerSearch,
  serializeExplorerState,
  withFilters,
  withLine,
  withMarket,
  withPeriod,
  withTab,
  type ExplorerState,
} from "./state";
import { buildTabs, resolveView } from "./tabs";
import { fakeFamilies } from "./fake";

const FULL: ExplorerState = {
  tab: "corners",
  market: "corners.total",
  period: "1H",
  line: "4.5",
  window: "today",
  q: "Brighton",
  country: "England",
  competition: 39,
  bookmaker: 8,
  oddsMin: "1.5",
  oddsMax: "3.25",
  minBooks: 3,
  fairOnly: true,
  mine: true,
  sort: "edge",
};

/** Through a real query string, as a browser would carry it. */
function viaUrl(state: ExplorerState): ExplorerState {
  const qs = new URLSearchParams(serializeExplorerState(state)).toString();
  return parseExplorerSearch(Object.fromEntries(new URLSearchParams(qs)));
}

describe("round trips", () => {
  test("the default state is the empty search, and back", () => {
    expect(serializeExplorerState(DEFAULT_EXPLORER_STATE)).toEqual({});
    expect(parseExplorerSearch({})).toEqual(DEFAULT_EXPLORER_STATE);
  });

  test("every field survives, through the object and through a query string", () => {
    expect(parseExplorerSearch(serializeExplorerState(FULL))).toEqual(FULL);
    expect(viaUrl(FULL)).toEqual(FULL);
    expect(serializeExplorerState(FULL)).toEqual({
      f: "corners",
      m: "corners.total",
      p: "1H",
      l: "4.5",
      h: "today",
      q: "Brighton",
      c: "England",
      comp: "39",
      bk: "8",
      min: "1.5",
      max: "3.25",
      nb: "3",
      fair: "1",
      mine: "1",
      sort: "edge",
    });
  });

  test("a handicap line keeps its sign, a level one is 0", () => {
    for (const line of ["-0.25", "0", "1.75", "-2"]) {
      expect(viaUrl({ ...DEFAULT_EXPLORER_STATE, line }).line).toBe(line);
    }
  });

  test("each window and each order", () => {
    for (const window of ["today", 24, 48, 72] as const) {
      expect(viaUrl({ ...DEFAULT_EXPLORER_STATE, window }).window).toBe(window);
    }
    for (const sort of ["time", "competition", "edge"] as const) {
      expect(viaUrl({ ...DEFAULT_EXPLORER_STATE, sort }).sort).toBe(sort);
    }
  });

  test("a router that hands numbers and booleans (a JSON search) reads the same", () => {
    expect(
      parseExplorerSearch({
        h: 48,
        comp: 39,
        bk: 8,
        nb: 5,
        l: -0.25,
        fair: true,
        mine: 1,
        min: 1.5,
      }),
    ).toEqual({
      ...DEFAULT_EXPLORER_STATE,
      window: 48,
      competition: 39,
      bookmaker: 8,
      minBooks: 5,
      line: "-0.25",
      fairOnly: true,
      mine: true,
      oddsMin: "1.5",
    });
    // a repeated key: the first value
    expect(parseExplorerSearch({ f: ["goals", "cards"] }).tab).toBe("goals");
  });
});

describe("a malformed URL reads as the defaults, never an error", () => {
  test("unknown tab, period, order and window; a market key with odd characters", () => {
    expect(
      parseExplorerSearch({ f: "casino", p: "3H", sort: "value", h: "12", m: "<script>" }),
    ).toEqual(DEFAULT_EXPLORER_STATE);
  });

  test("a line off the quarter grid, or absurd, is the main line; text lines are normalised", () => {
    expect(normalizeLine("2.3")).toBeNull();
    expect(normalizeLine("5000")).toBeNull();
    expect(normalizeLine("abc")).toBeNull();
    expect(normalizeLine("")).toBeNull();
    expect(normalizeLine("2.50")).toBe("2.5");
    expect(normalizeLine("-0.250")).toBe("-0.25");
    expect(normalizeLine("-0")).toBe("0");
    expect(parseExplorerSearch({ l: "2.3" }).line).toBe("main");
  });

  test("a price bound must be a price: above 1, two decimals, a comma read as the decimal mark", () => {
    expect(normalizeOdds("1")).toBeNull();
    expect(normalizeOdds("0.5")).toBeNull();
    expect(normalizeOdds("1,5")).toBe("1.5");
    expect(normalizeOdds("2.345")).toBe("2.35");
    expect(normalizeOdds("x")).toBeNull();
    // the range upside down is put the right way round
    const s = parseExplorerSearch({ min: "4", max: "1.8" });
    expect([s.oddsMin, s.oddsMax]).toEqual(["1.8", "4"]);
  });

  test("ids are positive integers; the minimum of bookmakers is at most 50", () => {
    const s = parseExplorerSearch({ comp: "-3", bk: "8.5", nb: "99" });
    expect([s.competition, s.bookmaker, s.minBooks]).toEqual([null, null, null]);
  });

  test("the search is kept as typed, up to 80 characters", () => {
    expect(parseExplorerSearch({ q: "x".repeat(200) }).q).toHaveLength(80);
    expect(serializeExplorerState({ ...DEFAULT_EXPLORER_STATE, q: "   " })).toEqual({});
  });
});

describe("what each choice does to the state", () => {
  const base: ExplorerState = { ...FULL, sort: "time" };

  test("another tab: the market the caller chose (its last used), its own period, the main line", () => {
    expect(withTab(base, "goals", "goals.btts")).toEqual({
      ...base,
      tab: "goals",
      market: "goals.btts",
      period: null,
      line: "main",
    });
  });

  test("another market: the period stays when the new one has it, the line goes back to main", () => {
    const kept = withMarket(base, "corners", "corners.asian_handicap", ["FT", "1H"]);
    expect([kept.market, kept.period, kept.line]).toEqual(["corners.asian_handicap", "1H", "main"]);
    const lost = withMarket(base, "corners", "corners.asian_handicap", ["FT"]);
    expect(lost.period).toBeNull();
  });

  test("another period: the main line; another line: normalised, or main", () => {
    expect(withPeriod(base, "FT")).toEqual({ ...base, period: "FT", line: "main" });
    expect(withLine(base, "3.50").line).toBe("3.5");
    expect(withLine(base, "nope").line).toBe("main");
  });

  test("«Borrar filtros»: every filter off, the window, tab, market, period, line and order kept", () => {
    const cleared = clearFilters(base);
    expect(activeFilters(filtersOf(cleared))).toBe(0);
    expect([cleared.tab, cleared.market, cleared.period, cleared.line, cleared.window]).toEqual([
      "corners",
      "corners.total",
      "1H",
      "4.5",
      "today",
    ]);
  });

  test("the filters on are counted once each (the price range is one)", () => {
    expect(activeFilters(filtersOf(base))).toBe(8);
    expect(activeFilters(filtersOf(withFilters(base, { oddsMax: null })))).toBe(8);
    expect(activeFilters(filtersOf(DEFAULT_EXPLORER_STATE))).toBe(0);
  });
});

describe("what the API is asked for", () => {
  const tabs = buildTabs(fakeFamilies().families);

  test("«Hoy» asks for the next 24 h; the board names the market, period and line on show", () => {
    const view = resolveView(tabs, FULL);
    expect(familiesQuery(FULL)).toEqual({ hours: 24, country: "England", competition: 39 });
    expect(boardQuery(FULL, view)).toEqual({
      hours: 24,
      country: "England",
      competition: 39,
      market: "corners.total",
      period: "1H",
      line: "4.5",
      q: "Brighton",
      bookmaker: 8,
      min_books: 3,
      odds_min: "1.5",
      odds_max: "3.25",
      fair_only: true,
      sort: "edge",
    });
    expect(familiesQuery({ ...FULL, window: 72 }).hours).toBe(72);
  });
});
