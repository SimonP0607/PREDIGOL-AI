/// <reference types="bun" />
/**
 * The Mercados tab by category (plan Partidos y Match Center, F4b): the catalogue's markets in the reader's words, one row
 * per line with the most balanced one first, every bookmaker's price in force, and the five settled markets - and only
 * them - keeping their parlay key.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { setLocale } from "@/lib/i18n";
import type {
  MarketCatalogMarket,
  MarketCatalogSelection,
} from "@/lib/api/v1/types_market_catalog";
import type { SelectionQuotes } from "@/lib/api/v1/types_profile";
import {
  boardView,
  catalogSelection,
  catalogTitle,
  catalogView,
  featuredBoards,
  headerBooks,
  hiddenLines,
  later,
  periodLabel,
} from "./marketCatalog";
import type { BestPrice, MarketBoard } from "./model";

setLocale("es");
afterEach(() => setLocale("es"));

const sides = { home: "Valencia", away: "Real Madrid" };
const AT = "2026-11-08T09:00:00Z";

function sel(
  selection: string,
  line: string,
  books: Array<[string, string]>,
  at = AT,
): MarketCatalogSelection {
  const ordered = [...books].sort((a, b) => Number(b[1]) - Number(a[1]));
  const [topName, topOdds] = ordered[0] ?? ["", "0"];
  return {
    selection,
    line,
    best_odds: topOdds,
    bookmaker_id: 1,
    bookmaker: topName,
    captured_at: at,
    bookmakers: books.length,
    books: ordered.map(([name, odds], i) => ({
      bookmaker_id: i + 1,
      bookmaker: name,
      odds,
      captured_at: at,
      bet_id: 45,
    })),
  };
}

function market(over: Partial<MarketCatalogMarket>): MarketCatalogMarket {
  return {
    key: ["corners_over_under", "FT", "match"].join("."),
    code: "corners_over_under",
    period: "FT",
    subject: "match",
    kind: "over_under",
    has_line: true,
    category: "corners",
    bet_ids: [45],
    provider_name: "Corners Over Under",
    market_key: null,
    bookmakers: 2,
    selections: [],
    ...over,
  };
}

const corners = market({
  selections: [
    sel("Over", "8.5", [
      ["Bet365", "1.40"],
      ["Pinnacle", "1.45"],
    ]),
    sel("Under", "8.5", [["Bet365", "2.70"]]),
    sel("Over", "9.5", [
      ["Bet365", "1.85"],
      ["Pinnacle", "1.90"],
    ]),
    sel("Under", "9.5", [
      ["Bet365", "1.95"],
      ["Pinnacle", "1.88"],
    ]),
    sel("Over", "10.5", [["Bet365", "2.50"]]),
    sel("Under", "10.5", [["Bet365", "1.50"]]),
  ],
});

describe("a catalogue market as shown", () => {
  test("one row per line, Over and Under as columns, the most balanced line first in view", () => {
    const v = catalogView(corners, sides);
    expect(v.title).toBe("Más/menos córners");
    expect(v.period).toBe("90'");
    expect(v.lines).toBe("ou");
    expect(v.columns.map((c) => c.label)).toEqual(["Más de", "Menos de"]);
    expect(v.rows.map((r) => r.line)).toEqual([8.5, 9.5, 10.5]);
    expect(v.rows[v.main]?.line).toBe(9.5);
    expect(hiddenLines(v)).toBe(2);
  });

  test("each price says its bookmaker and since when; every bookmaker's, the best in gold", () => {
    const v = catalogView(corners, sides);
    const row = v.rows[v.main]!;
    expect(row.cells[0]).toMatchObject({
      odds: "1.90",
      bookmaker: "Pinnacle",
      books: 2,
      capturedAt: AT,
    });
    expect(row.books.map((b) => b.bookmaker)).toEqual(["Bet365", "Pinnacle"]);
    const bet365 = row.books[0]!;
    expect(bet365.cells[0]).toEqual({ odds: "1.85", since: AT, firstSeen: null, best: false });
    expect(bet365.cells[1]).toEqual({ odds: "1.95", since: AT, firstSeen: null, best: true });
  });

  test("a market that is never settled has no parlay key; one of the five keeps its own", () => {
    expect(catalogView(corners, sides).parlay).toBeNull();
    const btts = catalogView(
      market({
        key: ["goals_btts", "FT", "match"].join("."),
        code: "goals_btts",
        kind: "both_teams_score",
        has_line: false,
        category: "goals",
        market_key: "BTTS",
        selections: [sel("Yes", "0", [["Bet365", "1.80"]]), sel("No", "0", [["Bet365", "2.00"]])],
      }),
      sides,
    );
    expect(btts.parlay).toBe("BTTS");
    expect(btts.id).toBe("BTTS");
    expect(btts.lines).toBeNull();
    expect(btts.rows).toHaveLength(1);
    expect(btts.columns.map((c) => c.label)).toEqual(["Sí", "No"]);
    // what the parlay receives: the five's own key, never the catalogue's
    expect(btts.rows[0]!.cells[0]).toMatchObject({ market: "BTTS", selection: "Yes", line: 0 });
    expect(hiddenLines(btts)).toBe(0);
  });

  test("an Asian handicap's away side sits on its home line's row", () => {
    const v = catalogView(
      market({
        key: ["result_asian_handicap", "1H", "match"].join("."),
        code: "result_asian_handicap",
        period: "1H",
        kind: "asian_handicap",
        category: "goals_half",
        selections: [
          sel("Home", "-0.5", [["Bet365", "2.10"]]),
          sel("Away", "0.5", [["Bet365", "1.75"]]),
          sel("Home", "0", [["Bet365", "1.60"]]),
          sel("Away", "0", [["Bet365", "2.30"]]),
        ],
      }),
      sides,
    );
    expect(v.lines).toBe("ah");
    expect(v.period).toBe("1.ª parte");
    expect(v.columns.map((c) => c.label)).toEqual(["Valencia", "Real Madrid"]);
    expect(v.rows.map((r) => r.line)).toEqual([-0.5, 0]);
    expect(v.rows[0]!.cells.map((c: BestPrice | null) => c?.odds)).toEqual(["2.10", "1.75"]);
  });
});

describe("the words of the catalogue", () => {
  test("a team's market names the team; periods and selections are translated", () => {
    expect(catalogTitle({ code: "goals_over_under", subject: "home" }, sides)).toBe(
      "Más/menos goles · Valencia (local)",
    );
    expect(catalogTitle({ code: "yellow_cards_1x2", subject: "match" }, sides)).toBe(
      "Más amarillas (1X2)",
    );
    expect(periodLabel("2H")).toBe("2.ª parte");
    expect(catalogSelection("double_chance", "1X", null, sides, 0)).toBe("Valencia o empate");
    expect(catalogSelection("odd_even", "Even", null, sides, 1)).toBe("Par");
    expect(catalogSelection("one_x_two", "Draw", null, sides, 1)).toBe("Empate");
    expect(catalogSelection("highest_scoring_half", "2nd Half", null, sides, 1)).toBe("2.ª parte");
    expect(catalogSelection("half_time_full_time", "Home/Draw", null, sides, 0)).toBe(
      "Valencia / Empate",
    );
  });

  test("a key without a translation reads as a generic text, never the key", () => {
    expect(catalogTitle({ code: "bet_999", subject: "match" }, sides)).toBe("Otro mercado");
    expect(periodLabel("ET")).toBe("Otro período");
    expect(catalogSelection("half_time_full_time", "Home/Other", null, sides, 3)).toBe("Opción 4");
    expect(catalogSelection("mystery", "Exactly 3", null, sides, 0)).toBe("Opción 1");
  });

  test("in English", () => {
    setLocale("en");
    expect(catalogTitle({ code: "corners_over_under", subject: "away" }, sides)).toBe(
      "Corners over/under · Real Madrid (away)",
    );
    expect(periodLabel("1H")).toBe("1st half");
    expect(catalogSelection("double_chance", "X2", null, sides, 2)).toBe("Draw or Real Madrid");
    expect(catalogTitle({ code: "bet_1", subject: "match" }, sides)).toBe("Other market");
  });
});

function price(market: string, selection: string, line: number, odds: string): BestPrice {
  return { market, selection, line, odds, bookmaker: "Bet365", books: 3, capturedAt: AT };
}

function board(market: string, rows: MarketBoard["rows"], main = 0): MarketBoard {
  return { market, books: 3, rows, main, updatedAt: AT };
}

const ou = board(
  "OU",
  [1.5, 2.5, 3.5].map((l, i) => ({
    key: `OU|${l}`,
    line: l,
    cells: [price("OU", "Over", l, ["1.30", "2.05", "3.10"][i]!), price("OU", "Under", l, "1.80")],
  })),
  2,
);
const x12 = board("1X2", [
  {
    key: "1X2",
    line: null,
    cells: [price("1X2", "Home", 0, "2.05"), price("1X2", "Draw", 0, "3.40"), null],
  },
]);

describe("the highlights", () => {
  test("1X2, over/under and both teams score; handicap and double chance only while «Resultado» is missing", () => {
    const boards = ["1X2", "OU", "BTTS", "AH", "DC"].map((m) => board(m, []));
    expect(featuredBoards(boards, true).map((b) => b.market)).toEqual(["1X2", "OU", "BTTS"]);
    expect(featuredBoards(boards, null).map((b) => b.market)).toEqual(["1X2", "OU", "BTTS"]);
    expect(featuredBoards(boards, false).map((b) => b.market)).toEqual([
      "1X2",
      "OU",
      "BTTS",
      "AH",
      "DC",
    ]);
  });

  test("over/under opens on 2.5 when it is priced, with the other lines behind", () => {
    const v = boardView(ou, null, sides, 2.5);
    expect(v.rows[v.main]?.line).toBe(2.5);
    expect(v.parlay).toBe("OU");
    expect(hiddenLines(v)).toBe(2);
    expect(boardView(ou, null, sides, 4.5).main).toBe(2);
  });

  test("a five's tiles say where the best price was first seen, in the new words", () => {
    const all: SelectionQuotes[] = [
      {
        market_key: "1X2",
        selection: "Home",
        line: "0",
        books: [
          { bookmaker_id: 1, bookmaker: "Bet365", odds: "2.05", opening_odds: "2.10" },
          { bookmaker_id: 2, bookmaker: "Pinnacle", odds: "2.00", opening_odds: "2.00" },
        ],
      } as unknown as SelectionQuotes,
    ];
    const v = boardView(x12, all, sides);
    expect(v.columns.map((c) => c.label)).toEqual(["Valencia", "Empate", "Real Madrid"]);
    expect(v.rows[0]!.notes).toEqual(["primera cuota vista 2,10", null, null]);
    expect(v.rows[0]!.books.map((b) => b.bookmaker)).toEqual(["Bet365", "Pinnacle"]);
    expect(v.rows[0]!.books[0]!.cells[0]).toEqual({
      odds: "2.05",
      since: null,
      firstSeen: "2.10",
      best: true,
    });
  });
});

describe("the header", () => {
  test("the most bookmakers any source has in force, and the later update", () => {
    expect(headerBooks(4, null)).toBe(4);
    expect(
      headerBooks(4, [
        { key: "result", markets: 3, selections: 9, bookmakers: 7 },
        { key: "corners", markets: 1, selections: 2, bookmakers: 2 },
      ]),
    ).toBe(7);
    expect(later("2026-11-08T09:00:00Z", "2026-11-08T10:00:00Z")).toBe("2026-11-08T10:00:00Z");
    expect(later(null, AT)).toBe(AT);
    expect(later(AT, undefined)).toBe(AT);
  });
});
