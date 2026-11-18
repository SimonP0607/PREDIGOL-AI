/// <reference types="bun" />
/** Mi parlay with the catalogue's markets (plan EA, EA-503): only what the server marks parlayable goes in, the five as always. */
import { describe, expect, test } from "bun:test";
import { setLocale } from "@/lib/i18n";
import type { MarketProbs } from "@/lib/api/v1/types_stats";
import { parlayBlock } from "@/product/odds/parlay";
import { parseSlip } from "@/product/records/model";
import { isCatalogueKey, marketName, selectionLabel } from "@/product/shared/markets";
import fixture from "@/components/analytics/stats/fixtures/c14_match.json";
import {
  catalogChooser,
  catalogParlayOf,
  NO_CATALOG_PARLAY,
  selectionId,
  settlesWith,
  withCatalogParlay,
} from "./catalogParlay";
import type { Choose } from "./choose";
import type { MarketView } from "./marketCatalog";

setLocale("es");
const LATER = "2034-05-01T20:00:00Z";
const NOW = Date.parse("2034-05-01T12:00:00Z");
const KEY = "corners_over_under.FT.match";

function probs(allowed: boolean): MarketProbs {
  const base = { data: fixture as unknown as MarketProbs };
  const m = {
    ...base.data.markets.items[0]!,
    key: KEY,
    rule_key: "corners_ft@v1",
    selections: [
      {
        ...base.data.markets.items[0]!.selections[0]!,
        selection: "Over",
        line: 9.5,
        parlay: { allowed, reason: allowed ? "ok" : "interruptor_apagado" },
      },
    ],
  };
  return { ...base.data, markets: { ...base.data.markets, items: [m] } } as MarketProbs;
}

function view(): MarketView {
  return {
    id: KEY,
    key: KEY,
    title: "Más/menos córners",
    period: "90'",
    parlay: null,
    lines: "ou",
    columns: [
      { selection: "Over", label: "Más de" },
      { selection: "Under", label: "Menos de" },
    ],
    rows: [],
    main: 0,
    books: 5,
  };
}

const choose: Choose = (p) => ({
  fixture_id: 9,
  market_key: p.market as "OU",
  selection: p.selection,
  line: p.line,
  kickoff_at: LATER,
  home: "Valencia",
  away: "Betis",
  odds: p.odds,
  bookmaker: p.bookmaker,
});

const price = (selection: string) => ({
  market: KEY,
  selection,
  line: 9.5,
  odds: "1.90",
  bookmaker: "Casa",
  books: 5,
  capturedAt: LATER,
});

describe("catalogue markets in Mi parlay", () => {
  test("a key of the catalogue reads as one, the five do not", () => {
    expect(isCatalogueKey(KEY)).toBe(true);
    expect(isCatalogueKey("OU")).toBe(false);
    expect(isCatalogueKey("corners.XX.match")).toBe(false);
  });

  test("only the selections the server marks allowed are taken", () => {
    const cp = catalogParlayOf(probs(true));
    expect(cp.allowed.has(selectionId(KEY, "Over", 9.5))).toBe(true);
    expect(cp.settles.get(KEY)).toBe("stats");
    expect(catalogParlayOf(probs(false))).toEqual({ allowed: new Set(), settles: new Map() });
  });

  test("with nothing allowed the views are as they were", () => {
    const v = [view()];
    expect(withCatalogParlay(v, NO_CATALOG_PARLAY)).toBe(v);
    expect(withCatalogParlay(v, catalogParlayOf(probs(true)))[0]?.catalogParlay).toBe("stats");
  });

  test("a chosen price carries the catalogue's key, the server's verdict and the page's words", () => {
    const cp = catalogParlayOf(probs(true));
    const v = withCatalogParlay([view()], cp)[0]!;
    const c = catalogChooser(choose, v, cp)!;
    const over = c(price("Over"));
    expect(over.market_key).toBe(KEY);
    expect(over.parlay_allowed).toBe(true);
    expect(over.label).toBe("Más de 9,5");
    expect(over.market_label).toBe("Más/menos córners");
    expect(c(price("Under")).parlay_allowed).toBe(false);
    expect(catalogChooser(choose, view(), cp)).toBe(choose);
  });

  test("the parlay refuses a catalogue market unless the server allowed it", () => {
    const sel = { market_key: KEY, odds: "1.9", line: 9.5, kickoff_at: LATER };
    expect(parlayBlock(sel, NOW)).toBe("market");
    expect(parlayBlock({ ...sel, parlay_allowed: false }, NOW)).toBe("market");
    expect(parlayBlock({ ...sel, parlay_allowed: true }, NOW)).toBeNull();
    expect(parlayBlock({ ...sel, parlay_allowed: true, line: 9.25 }, NOW)).toBe("quarter");
    expect(
      parlayBlock({ market_key: "OU", odds: "1.9", line: 2.5, kickoff_at: LATER }, NOW),
    ).toBeNull();
  });

  test("a slip keeps a catalogue leg with its words, and drops an unknown market", () => {
    const raw = JSON.stringify([
      {
        fixture_id: 9,
        market_key: KEY,
        selection: "Over",
        line: "9.5",
        kickoff_at: LATER,
        label: "Más de 9,5",
        market_label: "Córners",
      },
      { fixture_id: 10, market_key: "nothing", selection: "Over", line: "1", kickoff_at: LATER },
    ]);
    const legs = parseSlip(raw);
    expect(legs).toHaveLength(1);
    expect(legs[0]).toMatchObject({
      market_key: KEY,
      label: "Más de 9,5",
      market_label: "Córners",
    });
  });

  test("a saved catalogue leg read back without its page still reads in words", () => {
    expect(marketName("corners_over_under.1H.home")).toContain("1.ª parte");
    expect(selectionLabel({ market_key: KEY, selection: "Over", line: "9.5" })).toBe("Más de 9,5");
    expect(selectionLabel({ market_key: "OU", selection: "Over", line: "2.5" })).toBe(
      "Más de 2,5 goles",
    );
  });

  test("what settles a rule", () => {
    expect(settlesWith("goals_ft@v1")).toBe("score");
    expect(settlesWith("corners_ft@v1")).toBe("stats");
    expect(settlesWith("player_shots@v1")).toBe("player");
  });
});
