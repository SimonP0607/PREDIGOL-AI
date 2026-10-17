/// <reference types="bun" />
import { describe, expect, test } from "bun:test";
import type { BestOddsFixture } from "@/lib/api/v1/types_product";
import {
  NO_ODDS_FILTERS,
  bestEdge,
  competitionOptions,
  countryOptions,
  inOddsFilters,
  sortFixtures,
} from "./filters";

function fx(
  id: number,
  ko: string,
  edges: Array<[string, string, boolean?]>,
  comp: { id: number; name: string; country: string | null },
  teams: [string, string] = [`Home ${id}`, `Away ${id}`],
): BestOddsFixture {
  return {
    fixture_id: id,
    kickoff_at: ko,
    competition: { ...comp, logo_url: null, flag_url: null },
    home: { id: id * 10, name: teams[0], logo_url: null },
    away: { id: id * 10 + 1, name: teams[1], logo_url: null },
    as_of: ko,
    markets: [
      {
        market_key: "1X2",
        line: "0",
        selections: edges.map(([selection, edge, outlier]) => ({
          selection,
          best_odds: "2.00",
          bookmaker: "B",
          p_fair: "0.5",
          fair_odds: "2.00",
          price_edge: edge,
          outlier: outlier ?? false,
          n_bookmakers: 4,
          as_of: ko,
        })),
      },
    ],
  } as unknown as BestOddsFixture;
}

const LIGA = { id: 1, name: "La Liga", country: "Spain" };
const PREMIER = { id: 2, name: "Premier League", country: "England" };
const FRIENDLY = { id: 3, name: "Friendlies", country: "World" };
const BOARD = [
  fx(
    1,
    "2032-08-01T18:00:00Z",
    [
      ["Home", "-0.02"],
      ["Away", "0.03"],
    ],
    LIGA,
    ["Real Madrid", "Atlético Madrid"],
  ),
  fx(
    2,
    "2032-08-01T15:00:00Z",
    [
      ["Home", "0.30", true],
      ["Away", "-0.01"],
    ],
    PREMIER,
  ),
  fx(
    3,
    "2032-08-01T16:00:00Z",
    [
      ["Home", "0.08"],
      ["Away", "-0.04"],
    ],
    FRIENDLY,
  ),
];

describe("the Cuotas page's filters (REVIEW point 17)", () => {
  test("the widest margin over fair never counts an outlier", () => {
    expect(bestEdge(BOARD[0]!, "1X2")).toBeCloseTo(0.03);
    expect(bestEdge(BOARD[1]!, "1X2")).toBeCloseTo(-0.01);
    expect(bestEdge(BOARD[0]!, "OU")).toBeNull();
  });

  test("search, country, competition and only above fair narrow the board", () => {
    const ids = (f: typeof NO_ODDS_FILTERS) =>
      BOARD.filter((x) => inOddsFilters(x, "1X2", f)).map((x) => x.fixture_id);
    expect(ids(NO_ODDS_FILTERS)).toEqual([1, 2, 3]);
    expect(ids({ ...NO_ODDS_FILTERS, query: "atletico" })).toEqual([1]);
    expect(ids({ ...NO_ODDS_FILTERS, query: "premier" })).toEqual([2]);
    expect(ids({ ...NO_ODDS_FILTERS, country: "world" })).toEqual([3]);
    expect(ids({ ...NO_ODDS_FILTERS, competition: 1 })).toEqual([1]);
    expect(ids({ ...NO_ODDS_FILTERS, aboveFair: true })).toEqual([1, 3]);
  });

  test("by kick-off, or the widest margin over fair first", () => {
    expect(sortFixtures(BOARD, "1X2", "time").map((x) => x.fixture_id)).toEqual([2, 3, 1]);
    expect(sortFixtures(BOARD, "1X2", "edge").map((x) => x.fixture_id)).toEqual([3, 1, 2]);
  });

  test("the countries and competitions on the board, international last", () => {
    expect(countryOptions(BOARD, "1X2", "es", "Internacional").map((o) => o.key)).toEqual([
      "england",
      "spain",
      "world",
    ]);
    expect(competitionOptions(BOARD, "1X2", "spain", "es").map((o) => o.key)).toEqual([1]);
    expect(competitionOptions(BOARD, "1X2", null, "es").map((o) => o.label)).toEqual([
      "Friendlies",
      "La Liga",
      "Premier League",
    ]);
  });
});
