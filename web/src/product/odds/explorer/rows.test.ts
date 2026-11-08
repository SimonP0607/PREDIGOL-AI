/// <reference types="bun" />
/**
 * The board's rows: each row as old as its own capture, a stale one said so; the API's filters and orders (as the fake data
 * applies them), the two the client keeps («Hoy», «Mis equipos y ligas»), the groups, the lines on offer and the prices that
 * moved between two updates.
 */
import { afterAll, afterEach, describe, expect, test } from "bun:test";
import { setLocale } from "@/lib/i18n";
import { formatRelative, setTimeZone } from "@/lib/time";
import { COMPETITIONS, FAKE_NOW, fakeRows } from "./fake";
import type { OddsBoardRow } from "./model";
import {
  clientFilter,
  groupRows,
  isMine,
  isToday,
  lineOptions,
  priceMap,
  priceMoves,
  rowEdge,
  rowFreshness,
  sameLine,
  serverFilter,
  sortRows,
} from "./rows";
import { NO_FILTERS } from "./state";

setLocale("es");
afterAll(() => setLocale("es"));
afterEach(() => setTimeZone("UTC"));

const HOUR = 3_600_000;
const dictionary = new Map(COMPETITIONS.map((c) => [c.id, c]));
const rows = fakeRows("result.1x2", "FT", "main");
const ids = (list: readonly OddsBoardRow[]) => list.map((r) => r.fixture_id);
const none = { ...NO_FILTERS };

describe("freshness", () => {
  test("a current row reads its own age; its hint says when it was captured and when the provider changed it", () => {
    const row = rows[0]!;
    const f = rowFreshness(row, FAKE_NOW);
    expect(f.stale).toBe(false);
    expect(f.text).toBe(formatRelative(row.captured_at, FAKE_NOW));
    expect(f.text).toBe("hace 2 h");
    expect(f.title).toBe("Capturado a las 10:00 · el proveedor lo cambió a las 09:30");
  });

  test("a stale row: «Antiguo», and why", () => {
    const stale = rows.find((r) => r.state === "stale")!;
    const f = rowFreshness(stale, FAKE_NOW);
    expect(f.stale).toBe(true);
    expect(f.text).toBe("Antiguo · hace 7 h");
    expect(f.title).toContain("se saltó una captura prevista");
  });

  test("without the provider's time, only the capture; in English too", () => {
    const row = { ...rows[0]!, provider_update_at: null };
    expect(rowFreshness(row, FAKE_NOW).title).toBe("Capturado a las 10:00");
    setLocale("en");
    expect(rowFreshness({ ...row, state: "stale" }, FAKE_NOW).text).toBe(
      `Old · ${formatRelative(row.captured_at, FAKE_NOW)}`,
    );
    setLocale("es");
  });
});

describe("the API's filters", () => {
  test("text: a team or the competition, every word, accents aside", () => {
    expect(ids(serverFilter(rows, { ...none, q: "atletico nacional" }, dictionary))).toEqual([
      7821,
    ]);
    expect(ids(serverFilter(rows, { ...none, q: "premier" }, dictionary))).toEqual([7819, 7822]);
    expect(ids(serverFilter(rows, { ...none, q: "premier arsenal" }, dictionary))).toEqual([7822]);
  });

  test("country (international competitions are «World») and competition", () => {
    expect(ids(serverFilter(rows, { ...none, country: "Spain" }, dictionary))).toEqual([7820]);
    expect(ids(serverFilter(rows, { ...none, country: "world" }, dictionary))).toEqual([7823]);
    expect(ids(serverFilter(rows, { ...none, competition: 39 }, dictionary))).toEqual([7819, 7822]);
  });

  test("bookmaker, minimum of bookmakers, price range, only with a fair price", () => {
    const bk = rows[0]!.selections[0]!.bookmaker_id;
    expect(serverFilter(rows, { ...none, bookmaker: bk }, dictionary).length).toBeGreaterThan(0);
    expect(serverFilter(rows, { ...none, bookmaker: 999 }, dictionary)).toEqual([]);
    expect(serverFilter(rows, { ...none, minBooks: 50 }, dictionary)).toEqual([]);
    expect(serverFilter(rows, { ...none, oddsMin: "100" }, dictionary)).toEqual([]);
    expect(
      serverFilter(rows, { ...none, oddsMin: "1.01", oddsMax: "1000" }, dictionary),
    ).toHaveLength(5);
    const scorers = fakeRows("player.anytime_scorer", "FT", "main");
    expect(serverFilter(scorers, { ...none, fairOnly: true }, dictionary)).toEqual([]);
    expect(serverFilter(rows, { ...none, fairOnly: true }, dictionary)).toHaveLength(5);
  });
});

describe("the orders", () => {
  const shuffled = [...rows].reverse();

  test("by kick-off", () => {
    expect(ids(sortRows(shuffled, "time"))).toEqual([7819, 7820, 7821, 7822, 7823]);
  });

  test("by competition: the priority order, then kick-off", () => {
    const rank = new Map([
      [239, 0],
      [39, 1],
    ]);
    expect(ids(sortRows(shuffled, "competition", rank))).toEqual([7821, 7819, 7822, 7820, 7823]);
  });

  test("by the widest difference with the fair price: only rows that have one, never a stale row nor an outlier", () => {
    const sorted = sortRows(shuffled, "edge");
    expect(ids(sorted)).not.toContain(7821);
    const edges = sorted.map((r) => rowEdge(r) ?? -9);
    expect(edges).toEqual([...edges].sort((a, b) => b - a));
    // Arsenal's home price is an outlier: its 32 % never counts
    const arsenal = rows.find((r) => r.fixture_id === 7822)!;
    expect(rowEdge(arsenal)).toBeLessThan(0.25);
    expect(rowEdge(fakeRows("player.anytime_scorer", "FT", "main")[0]!)).toBeNull();
  });
});

describe("what the client keeps", () => {
  test("«Hoy»: kick-off on the reader's day - Bogotá's, not UTC's", () => {
    const late = new Date(Date.parse("2026-11-09T03:00:00Z")).toISOString();
    expect(isToday(late, FAKE_NOW)).toBe(false);
    setTimeZone("America/Bogota");
    // 22:00 on the 8th in Bogotá
    expect(isToday(late, FAKE_NOW)).toBe(true);
    setTimeZone("UTC");
    expect(ids(clientFilter(rows, { window: "today", mine: false }, null, FAKE_NOW))).toEqual([
      7819, 7820,
    ]);
    expect(clientFilter(rows, { window: 24, mine: false }, null, FAKE_NOW)).toHaveLength(5);
  });

  test("«Mis equipos y ligas»: a followed team, or a followed league; without a follow set, everything", () => {
    const follow = { teams: new Set([541]), leagues: new Set([239]) };
    expect(ids(clientFilter(rows, { window: 24, mine: true }, follow, FAKE_NOW))).toEqual([
      7820, 7821,
    ]);
    expect(isMine(rows[0]!, follow)).toBe(false);
    expect(clientFilter(rows, { window: 24, mine: true }, null, FAKE_NOW)).toHaveLength(5);
  });
});

describe("groups", () => {
  test("by kick-off: one group per local day; by competition: one per competition in the order given", () => {
    const byDay = groupRows(rows, "time");
    expect(byDay.map((g) => [g.kind, ids(g.rows)])).toEqual([
      ["day", [7819, 7820]],
      ["day", [7821, 7822]],
      ["day", [7823]],
    ]);
    const byCompetition = groupRows(sortRows(rows, "competition"), "competition");
    expect(byCompetition.map((g) => g.competition)).toEqual([39, 140, 239, 2]);
    expect(groupRows(rows, "edge").map((g) => g.kind)).toEqual(["all"]);
    expect(groupRows([], "edge")).toEqual([]);
  });
});

describe("lines", () => {
  test("every line the rows have, low to high, each once", () => {
    const ah = fakeRows("result.asian_handicap", "FT", "main");
    expect(lineOptions(ah)).toEqual([-2, -1.5, -1, -0.75, -0.5, -0.25, 0, 0.25, 0.5, 1]);
    expect(lineOptions(rows)).toEqual([]);
  });

  test("two lines are the same whatever their text", () => {
    expect(sameLine("2.50", 2.5)).toBe(true);
    expect(sameLine("-0.25", "0.25")).toBe(false);
    expect(sameLine(null, undefined)).toBe(true);
    expect(sameLine(null, "0")).toBe(false);
  });

  test("a board asked at a line lists only the matches that have it", () => {
    expect(ids(fakeRows("goals.total", "FT", "4.5"))).toEqual([7820, 7823]);
  });
});

describe("price changes", () => {
  test("up and down between two updates; a price new to the board did not move", () => {
    const before = priceMap(rows);
    const next = rows.map((r) =>
      r.fixture_id === 7819
        ? {
            ...r,
            selections: r.selections.map((s, i) =>
              i === 0 ? { ...s, best_odds: "9.99" } : i === 1 ? { ...s, best_odds: "1.01" } : s,
            ),
          }
        : r,
    );
    const extra = { ...rows[0]!, fixture_id: 9999 };
    const moves = priceMoves(before, priceMap([...next, extra]));
    expect([...moves.entries()]).toEqual([
      ["7819|Home||", "up"],
      ["7819|Draw||", "down"],
    ]);
    expect(priceMoves(before, priceMap(rows)).size).toBe(0);
  });
});

test("the fake board's kick-offs are the hours the fixtures say", () => {
  expect(rows.map((r) => (Date.parse(r.kickoff_at) - FAKE_NOW) / HOUR)).toEqual([3, 5, 26, 30, 50]);
});
