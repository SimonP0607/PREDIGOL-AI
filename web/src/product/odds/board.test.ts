/// <reference types="bun" />
/**
 * The board's order, each selection's line, its single best-value cell, the rows only to look at, local-day groups and
 * price freshness - a row's own and the range of the rows on show.
 */
import { afterEach, describe, expect, test } from "bun:test";
import type { BestMarket, BestPrice } from "@/lib/api/v1/types_product";
import { setTimeZone } from "@/lib/time";
import {
  GOLD_MIN_BOOKS,
  groupByDay,
  lookupOnly,
  priceAges,
  priceFreshness,
  priceSlots,
  rowAsOf,
  selectionLine,
} from "./board";

afterEach(() => setTimeZone("UTC"));

function price(
  selection: string,
  best_odds: string,
  price_edge: string,
  extra: Partial<BestPrice> = {},
): BestPrice {
  return {
    selection,
    best_odds,
    bookmaker: "Betano",
    p_fair: "0.5",
    fair_odds: "2.000",
    price_edge,
    n_bookmakers: 7,
    as_of: "2026-10-03T17:17:18Z",
    ...extra,
  };
}

describe("selectionLine: each selection at its own line", () => {
  test("an Asian handicap's row carries the home line; its away side is the other face of the bet, at -h", () => {
    expect(selectionLine("AH", "Home", "-0.25")).toBe(-0.25);
    expect(selectionLine("AH", "Away", "-0.25")).toBe(0.25);
    expect(selectionLine("AH", "Away", "1.50")).toBe(-1.5);
    // a level handicap is 0 on both sides, never "-0"
    expect(Object.is(selectionLine("AH", "Away", "0.00"), 0)).toBe(true);
  });

  test("every other market keeps the row's line", () => {
    expect(selectionLine("OU", "Under", "2.50")).toBe(2.5);
    expect(selectionLine("1X2", "Away", "0.00")).toBe(0);
    expect(selectionLine("AH", "Away", null)).toBe(null);
  });
});

describe("priceSlots", () => {
  test("home, draw, away - whatever order the API used", () => {
    const market: BestMarket = {
      market_key: "1X2",
      line: "0.00",
      selections: [price("Away", "19.5", "-0.12"), price("Draw", "7.75", "-0.04")],
    };
    const slots = priceSlots(market);
    expect(slots.map((s) => s.selection)).toEqual(["Home", "Draw", "Away"]);
    // A selection nobody quotes keeps its slot, empty: nothing is invented.
    expect(slots[0]?.price).toBe(null);
  });

  test("gold marks the highest edge, and only when it pays above fair", () => {
    const above = priceSlots({
      market_key: "OU",
      line: "2.5",
      selections: [price("Under", "2.55", "0.0102"), price("Over", "1.55", "0.031")],
    });
    expect(above.map((s) => [s.selection, s.best])).toEqual([
      ["Over", true],
      ["Under", false],
    ]);
    const below = priceSlots({
      market_key: "BTTS",
      line: "0.00",
      selections: [price("Yes", "2.4", "-0.0561"), price("No", "1.62", "-0.0171")],
    });
    expect(below.some((s) => s.best)).toBe(false);
  });

  test("gold needs as many bookmakers as a highlight: three (plan Cuotas, E13)", () => {
    expect(GOLD_MIN_BOOKS).toBe(3);
    const thin = priceSlots({
      market_key: "OU",
      line: "2.5",
      selections: [
        price("Over", "2.20", "0.08", { n_bookmakers: 2 }),
        price("Under", "1.80", "0.01", { n_bookmakers: 3 }),
      ],
    });
    // Over pays more above fair, but only two books quote it: the gold goes to Under, quoted by three.
    expect(thin.map((s) => [s.selection, s.best])).toEqual([
      ["Over", false],
      ["Under", true],
    ]);
    const lonely = priceSlots({
      market_key: "BTTS",
      line: "0",
      selections: [price("Yes", "2.4", "0.05", { n_bookmakers: 1 })],
    });
    expect(lonely.some((s) => s.best)).toBe(false);
  });

  test("an outlier is never the gold, whatever its edge", () => {
    const slots = priceSlots({
      market_key: "1X2",
      line: "0",
      selections: [price("Home", "3.10", "0.40", { outlier: true }), price("Away", "2.10", "0.02")],
    });
    expect(slots.filter((s) => s.best).map((s) => s.selection)).toEqual(["Away"]);
  });
});

describe("lookupOnly: a row whose line never goes in a parlay", () => {
  test("a quarter line (.25 / .75), for both faces of a handicap; never a whole or half line", () => {
    expect(lookupOnly({ line: "-0.25" })).toBe(true);
    expect(lookupOnly({ line: "0.75" })).toBe(true);
    expect(lookupOnly({ line: "2.75" })).toBe(true);
    expect(lookupOnly({ line: "-0.50" })).toBe(false);
    expect(lookupOnly({ line: "0" })).toBe(false);
    expect(lookupOnly({ line: "2.5" })).toBe(false);
  });
});

describe("how old the prices on show are (plan Cuotas, E3)", () => {
  const T = (iso: string) => `2026-10-03T${iso}:00Z`;
  const market = (key: string, ...ages: string[]): BestMarket => ({
    market_key: key,
    line: "0",
    selections: ages.map((at, i) => price(`S${i}`, "2.00", "0", { as_of: T(at) })),
  });

  test("a row is as old as the OLDEST price it shows", () => {
    expect(rowAsOf(market("1X2", "17:00", "15:10", "16:30"))).toBe(T("15:10"));
    expect(rowAsOf(market("1X2"))).toBe(null);
    expect(rowAsOf(undefined)).toBe(null);
  });

  test("the range runs from the newest row to the oldest, in the chosen market only", () => {
    const fixtures = [
      { markets: [market("1X2", "17:00", "16:50"), market("OU", "17:30", "17:30")] },
      { markets: [market("1X2", "15:00", "17:20")] },
      { markets: [market("1X2", "17:10", "17:12")] },
      { markets: [market("OU", "12:00", "12:00")] },
    ];
    expect(priceAges(fixtures, "1X2")).toEqual({ newest: T("17:10"), oldest: T("15:00") });
    expect(priceAges(fixtures, "OU")).toEqual({ newest: T("17:30"), oldest: T("12:00") });
    expect(priceAges(fixtures.slice(2, 3), "1X2")).toEqual({
      newest: T("17:10"),
      oldest: T("17:10"),
    });
    expect(priceAges(fixtures, "BTTS")).toBe(null);
    expect(priceAges([], "1X2")).toBe(null);
  });
});

describe("groupByDay", () => {
  const fixtures = [
    { id: 3, kickoff_at: "2026-10-04T17:00:00Z" },
    { id: 1, kickoff_at: "2026-10-03T20:00:00Z" },
    { id: 2, kickoff_at: "2026-10-04T00:30:00Z" },
  ];

  test("by the reader's own day: a late UTC kick-off is still Saturday in Bogotá", () => {
    setTimeZone("America/Bogota");
    expect(groupByDay(fixtures).map((g) => [g.key, g.items.map((f) => f.id)])).toEqual([
      ["2026-10-03", [1, 2]],
      ["2026-10-04", [3]],
    ]);
  });

  test("and already Sunday in Madrid", () => {
    setTimeZone("Europe/Madrid");
    expect(groupByDay(fixtures).map((g) => [g.key, g.items.map((f) => f.id)])).toEqual([
      ["2026-10-03", [1]],
      ["2026-10-04", [2, 3]],
    ]);
  });
});

describe("priceFreshness", () => {
  const now = Date.parse("2026-10-03T19:00:00Z");
  test("fresh within the hour, aging up to three, then stale", () => {
    expect(priceFreshness("2026-10-03T18:30:00Z", now)).toBe("fresh");
    expect(priceFreshness("2026-10-03T17:00:00Z", now)).toBe("aging");
    expect(priceFreshness("2026-10-03T02:00:00Z", now)).toBe("stale");
    expect(priceFreshness(null, now)).toBe("none");
  });
});
