/// <reference types="bun" />
/** The board's order, its single best-value cell, local-day groups and price freshness. */
import { afterEach, describe, expect, test } from "bun:test";
import type { BestMarket, BestPrice } from "@/lib/api/v1/types_product";
import { setTimeZone } from "@/lib/time";
import { groupByDay, priceFreshness, priceSlots } from "./board";

afterEach(() => setTimeZone("UTC"));

function price(selection: string, best_odds: string, price_edge: string): BestPrice {
  return {
    selection,
    best_odds,
    bookmaker: "Betano",
    p_fair: "0.5",
    fair_odds: "2.000",
    price_edge,
    n_bookmakers: 7,
    as_of: "2026-10-03T17:17:18Z",
  };
}

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
