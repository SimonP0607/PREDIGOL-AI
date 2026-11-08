/// <reference types="bun" />
/**
 * The URL of Cuotas (plan Cuotas, UX-069): the explorer's state as short keys, numbers as numbers so the router writes
 * `h=48` and not `h="48"`, the defaults left out, only the explorer's keys kept, and the route free of the explorer's code.
 */
import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  DEFAULT_EXPLORER_STATE,
  parseExplorerSearch,
  serializeExplorerState,
  type ExplorerState,
} from "./explorer";
import { ODDS_SEARCH_KEYS, validateOddsSearch } from "./oddsSearch";

const FULL: ExplorerState = {
  ...DEFAULT_EXPLORER_STATE,
  tab: "goals",
  market: "goals.total",
  period: "1H",
  line: "-0.25",
  window: 48,
  q: "Madrid",
  country: "Spain",
  competition: 140,
  bookmaker: 8,
  oddsMin: "1.5",
  oddsMax: "3",
  minBooks: 3,
  fairOnly: true,
  mine: true,
  sort: "edge",
};

const url = (state: ExplorerState) => validateOddsSearch(serializeExplorerState(state));

describe("the URL of Cuotas", () => {
  test("the default state is an empty search: a link to /odds carries nothing", () => {
    expect(url(DEFAULT_EXPLORER_STATE)).toEqual({});
    expect(validateOddsSearch({})).toEqual({});
  });

  test("numbers travel as numbers and words as words", () => {
    expect(url(FULL)).toEqual({
      f: "goals",
      m: "goals.total",
      p: "1H",
      l: -0.25,
      h: 48,
      q: "Madrid",
      c: "Spain",
      comp: 140,
      bk: 8,
      min: 1.5,
      max: 3,
      nb: 3,
      fair: 1,
      mine: 1,
      sort: "edge",
    });
  });

  test("what the router hands back is the same state", () => {
    expect(parseExplorerSearch(url(FULL))).toEqual(FULL);
    const today: ExplorerState = { ...DEFAULT_EXPLORER_STATE, window: "today", line: "2.5" };
    expect(parseExplorerSearch(url(today))).toEqual(today);
  });

  test("«Hoy» and a search that looks like a number stay text", () => {
    expect(url({ ...DEFAULT_EXPLORER_STATE, window: "today", q: "2026" })).toEqual({
      h: "today",
      q: "2026",
    });
  });

  test("on the way in only the explorer's keys stay; a value it cannot read changes nothing", () => {
    const search = validateOddsSearch({
      h: "72",
      comp: "140",
      fair: true,
      l: "zz",
      utm_source: "x",
    });
    expect(search).toEqual({ h: 72, comp: 140, fair: 1, l: "zz" });
    expect(parseExplorerSearch(search)).toEqual({
      ...DEFAULT_EXPLORER_STATE,
      window: 72,
      competition: 140,
      fairOnly: true,
    });
    expect(validateOddsSearch({ q: "x".repeat(500), h: Number.NaN })).toEqual({});
  });

  test("every key the explorer writes is one the route keeps", () => {
    expect(Object.keys(serializeExplorerState(FULL)).sort()).toEqual([...ODDS_SEARCH_KEYS].sort());
  });

  test("the route's helper stays out of the explorer's code (it runs in the app's first bundle)", () => {
    const text = readFileSync(join(import.meta.dir, "oddsSearch.ts"), "utf8");
    expect(text).not.toMatch(/^import /m);
  });
});
