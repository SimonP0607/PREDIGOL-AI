/// <reference types="bun" />
/** "Mi parlay" from a price: what can go in, the leg each source adds, and one leg per match. */
import { describe, expect, test } from "bun:test";
import type { BestHighlight, BestOddsFixture, BestPrice } from "@/lib/api/v1/types_product";
import { setLocale } from "@/lib/i18n";
import { selectionKey, slipReduce, type SlipLeg } from "@/product/records/model";
import { priceSlots } from "./board";
import { highlightLeg, parlayBlock, slotLeg, type NewLeg } from "./parlay";
import { blockedText, isToggleable, type ParlayLegState } from "./useParlayLeg";

const NOW = Date.parse("2026-10-08T12:00:00Z");
const LATER = "2026-10-08T20:00:00Z";
const EARLIER = "2026-10-08T11:00:00Z";

function price(selection: string, best_odds = "2.10"): BestPrice {
  return {
    selection,
    best_odds,
    bookmaker: "Betplay",
    p_fair: "0.47",
    fair_odds: "2.128",
    price_edge: "-0.013",
    n_bookmakers: 6,
    as_of: "2026-10-08T11:50:00Z",
  };
}

const team = (id: number, name: string) => ({ id, name, logo_url: null });

const fixture: BestOddsFixture = {
  fixture_id: 812,
  kickoff_at: LATER,
  competition: { id: 1, name: "Liga BetPlay", country: "Colombia", logo_url: null, flag_url: null },
  home: team(10, "Millonarios"),
  away: team(11, "Santa Fe"),
  markets: [],
  as_of: "2026-10-08T11:50:00Z",
};

describe("parlayBlock: the 'can add to parlay' rule", () => {
  const ok = { market_key: "1X2", odds: "2.10", line: "0", kickoff_at: LATER };

  test("a priced selection on a whole or half line, before kick-off", () => {
    expect(parlayBlock(ok, NOW)).toBe(null);
    expect(parlayBlock({ ...ok, market_key: "AH", line: "-0.5" }, NOW)).toBe(null);
    expect(parlayBlock({ ...ok, market_key: "OU", line: "2.50" }, NOW)).toBe(null);
  });

  test("not without a real price", () => {
    expect(parlayBlock({ ...ok, odds: null }, NOW)).toBe("no_price");
    expect(parlayBlock({ ...ok, odds: "1.00" }, NOW)).toBe("no_price");
    expect(parlayBlock({ ...ok, odds: "abc" }, NOW)).toBe("no_price");
  });

  test("never a quarter line", () => {
    expect(parlayBlock({ ...ok, market_key: "AH", line: "-0.25" }, NOW)).toBe("quarter");
    expect(parlayBlock({ ...ok, market_key: "OU", line: "2.75" }, NOW)).toBe("quarter");
  });

  test("nothing after kick-off", () => {
    expect(parlayBlock({ ...ok, kickoff_at: EARLIER }, NOW)).toBe("started");
    expect(parlayBlock({ ...ok, status_group: "live" }, NOW)).toBe("started");
    expect(parlayBlock({ ...ok, status_group: "scheduled" }, NOW)).toBe(null);
  });

  test("only the markets a parlay takes", () => {
    expect(parlayBlock({ ...ok, market_key: "CORNERS" }, NOW)).toBe("market");
  });

  test("a tap does something when the selection can be added, or is in the slip", () => {
    const state = (block: ParlayLegState["block"], inSlip: boolean): ParlayLegState => ({
      inSlip,
      block,
      replaces: false,
      toggle: () => undefined,
    });
    expect(isToggleable(null)).toBe(false);
    expect(isToggleable(state(null, false))).toBe(true);
    expect(isToggleable(state("quarter", false))).toBe(false);
    // In the slip already: it can always be taken out.
    expect(isToggleable(state("started", true))).toBe(true);

    // And when it cannot be added, the reader is told why (a quarter line, kicked off).
    setLocale("es");
    expect(blockedText(state("quarter", false))).toBe(
      "Las líneas de cuarto (.25 / .75) no van en un parlay",
    );
    expect(blockedText(state("started", false))).toBe("El partido ya empezó");
    expect(blockedText(state("started", true))).toBe(null);
    expect(blockedText(state("market", false))).toBe(null);
    expect(blockedText(null)).toBe(null);
  });
});

describe("legs from the Odds page", () => {
  test("a board price: the fixture, the market's line (as a number) and the best price", () => {
    const market = {
      market_key: "OU",
      line: "2.50",
      selections: [price("Over", "1.85"), price("Under", "2.05")],
    };
    const [over] = priceSlots(market);
    expect(over && slotLeg(fixture, market, over)).toEqual({
      fixture_id: 812,
      market_key: "OU",
      selection: "Over",
      line: "2.5",
      home: "Millonarios",
      away: "Santa Fe",
      kickoff_at: LATER,
      odds: "1.85",
      bookmaker: "Betplay",
      p_model: null,
    });
  });

  test("nothing for an empty slot or an unknown market", () => {
    const market = { market_key: "1X2", line: "0.00", selections: [price("Away")] };
    const [home] = priceSlots(market);
    expect(home && slotLeg(fixture, market, home)).toBe(null);
    const corners = { market_key: "CORNERS", line: "9.5", selections: [price("Over")] };
    const [slot] = priceSlots(corners);
    expect(slot && slotLeg(fixture, corners, slot)).toBe(null);
  });

  test("a highlight", () => {
    const h: BestHighlight = {
      fixture_id: 812,
      kickoff_at: LATER,
      competition: fixture.competition,
      home: fixture.home,
      away: fixture.away,
      market_key: "1X2",
      line: "0.00",
      price: price("Home", "2.40"),
    };
    expect(highlightLeg(h)).toMatchObject({
      fixture_id: 812,
      market_key: "1X2",
      selection: "Home",
      line: "0",
      odds: "2.40",
    });
    expect(highlightLeg({ ...h, market_key: "CORNERS" })).toBe(null);
  });

  test("one leg per match: a second price of the same match replaces the first, a tap again removes it", () => {
    const market = {
      market_key: "1X2",
      line: "0.00",
      selections: [price("Home"), price("Draw", "3.30"), price("Away", "3.60")],
    };
    const [home, draw] = priceSlots(market).map((s) => slotLeg(fixture, market, s)) as NewLeg[];
    let legs: SlipLeg[] = slipReduce([], { type: "toggle", leg: home as NewLeg }).legs;
    const replaced = slipReduce(legs, { type: "toggle", leg: draw as NewLeg });
    expect(replaced.effect).toBe("replaced");
    expect(replaced.legs.map((l) => l.selection)).toEqual(["Draw"]);
    legs = replaced.legs;
    const removed = slipReduce(legs, { type: "toggle", leg: draw as NewLeg });
    expect(removed.effect).toBe("removed");
    expect(removed.legs).toEqual([]);
    expect(selectionKey(draw as NewLeg)).toBe("812|1X2|Draw|0");
  });
});
