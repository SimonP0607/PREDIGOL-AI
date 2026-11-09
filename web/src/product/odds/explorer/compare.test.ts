/// <reference types="bun" />
/**
 * «Comparar casas» and «Movimiento». Each bookmaker's margin only where it means something (an exhaustive market quoted in
 * full; a double chance halved first); the best price of each column marked; the row's line found in the match's book. The
 * movement: the best price per capture minute, and its change said as up, down or flat.
 */
import { describe, expect, test } from "bun:test";
import { bookLine, bookMargin, bookMarket, compareGrid } from "./compare";
import { BOOKMAKERS, fakeBook, fakeMovement } from "./fake";
import { moveSummary, movementLines } from "./history";
import type { OddsBookLine, OddsMovement } from "./model";

const fair = { key: "goals.total", fair: true };

describe("a bookmaker's margin", () => {
  test("what its prices add up to above a fair book", () => {
    expect(bookMargin(fair, ["1.90", "1.90"])).toBeCloseTo(2 / 1.9 - 1, 9);
    expect(bookMargin({ key: "result.1x2", fair: true }, ["2.50", "3.20", "3.00"])).toBeCloseTo(
      1 / 2.5 + 1 / 3.2 + 1 / 3 - 1,
      9,
    );
  });

  test("a double chance covers every outcome twice: its book is halved", () => {
    const m = bookMargin({ key: "result.double_chance", fair: true }, ["1.30", "1.28", "1.85"]);
    expect(m).toBeCloseTo((1 / 1.3 + 1 / 1.28 + 1 / 1.85) / 2 - 1, 9);
  });

  test("none for a selection it does not quote, a broken price, or a market that is not exhaustive", () => {
    expect(bookMargin(fair, ["1.90", null])).toBeNull();
    expect(bookMargin(fair, ["1.90", "1.00"])).toBeNull();
    expect(bookMargin(fair, ["1.90"])).toBeNull();
    expect(bookMargin({ key: "player.anytime_scorer", fair: false }, ["2.00", "3.00"])).toBeNull();
  });
});

describe("the grid", () => {
  const book = fakeBook(7820, "goals");
  const market = bookMarket(book, "goals.total", "FT");

  test("the row's line, else the book's main one; nothing for a market or period it does not have", () => {
    expect(bookLine(market, "4.5")?.line).toBe("4.5");
    expect(bookLine(market, "9.5")?.line).toBe(market?.main_line ?? "");
    expect(bookMarket(book, "goals.total", "2H")).toBeNull();
    expect(bookLine(null, "2.5")).toBeNull();
  });

  test("bookmakers by name, the best price of each column marked, a missing price and its margin left blank", () => {
    const line = bookLine(market, "3.5") as OddsBookLine;
    const grid = compareGrid(market!.info, line, BOOKMAKERS);
    expect(grid.rows.map((r) => r.bookmaker)).toEqual([...BOOKMAKERS.map((b) => b.name)].sort());
    grid.selections.forEach((s, i) => {
      const best = grid.rows.filter((r) => r.cells[i]?.best);
      expect(best.length).toBeGreaterThanOrEqual(1);
      expect(best.every((r) => r.cells[i]?.odds === s.best_odds)).toBe(true);
    });
    const gap = grid.rows.find((r) => r.cells.some((c) => c.odds === null));
    expect(gap?.margin).toBeNull();
    expect(grid.rows.filter((r) => r.margin !== null).every((r) => (r.margin ?? 0) > 0)).toBe(true);
  });
});

describe("the movement", () => {
  test("one series per selection, its best price per minute, in time order", () => {
    const m: OddsMovement = {
      fixture_id: 1,
      market: "goals.total",
      period: "FT",
      line: "2.5",
      available: true,
      source: "quotes",
      bookmakers: [{ id: 8, name: "Bet365" }],
      series: [
        {
          selection: "Over",
          line: "2.5",
          points: [
            { at: "2026-11-08T10:00:20Z", best_odds: "1.90", bookmaker_id: 8, n_books: 6 },
            { at: "2026-11-08T10:00:40Z", best_odds: "1.95", bookmaker_id: 8, n_books: 6 },
            { at: "2026-11-08T08:00:00Z", best_odds: "2.00", bookmaker_id: 8, n_books: 5 },
            { at: "nope", best_odds: "2.00", bookmaker_id: 8, n_books: 5 },
          ],
        },
      ],
    };
    const [over] = movementLines(m);
    expect(over?.points.map((p) => [new Date(p.t).toISOString(), p.odds, p.bookmaker])).toEqual([
      ["2026-11-08T08:00:00.000Z", 2, "Bet365"],
      ["2026-11-08T10:00:00.000Z", 1.95, "Bet365"],
    ]);
    expect(movementLines({ ...m, available: false })).toEqual([]);
    expect(movementLines(undefined)).toEqual([]);
  });

  test("the change since the first capture: up, down or flat", () => {
    const lines = movementLines(
      fakeMovement(7820, { market: "result.1x2", period: "FT", line: null }),
    );
    // the home side shortening, the others drifting
    expect(lines.map((l) => moveSummary(l.points)?.trend)).toEqual(["down", "up", "up"]);
    expect(moveSummary([{ t: 1, odds: 2, bookmaker: "x" }])).toEqual({
      first: 2,
      last: 2,
      change: null,
      trend: "flat",
    });
    expect(moveSummary([])).toBeNull();
  });
});
