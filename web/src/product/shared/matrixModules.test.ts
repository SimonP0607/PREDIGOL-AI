/// <reference types="bun" />
/**
 * Cuotas, Picks, Noticias and Mi parlay read C-16 (plan PM, PM-14-04): off changes nothing, show only says, on replaces the module's own
 * check where it is written to (Cuotas' book, Mi parlay's flag). The ONE rule these tests keep: off and show hand back exactly what the
 * module had - same object, same flags.
 */
import { describe, expect, test } from "bun:test";
import { setLocale } from "@/lib/i18n";
import type {
  BlockAvailability,
  MarketAvailability,
  MatchAvailability,
  ModuleVerdict,
} from "@/lib/api/v1/types_availability";
import type { MatchOddsBook, OddsBookMarket } from "@/lib/api/v1/types_odds_explorer";
import type { MarketProbs } from "@/lib/api/v1/types_stats";
import fixture from "@/components/analytics/stats/fixtures/c14_match.json";
import { catalogParlayOf, selectionId } from "@/product/match/catalogParlay";
import {
  blockEntries,
  bookWithMatrix,
  hiddenMarkets,
  marketEntries,
  matrixMarketOf,
  parlayAllowed,
  parlayRefusal,
  verdictState,
} from "./matrixModules";

setLocale("es");

const OU = "goals_over_under.FT.match";
const CARDS = "cards_over_under.FT.match";

function verdicts(cuotas: boolean, parlay: boolean, picks = true): ModuleVerdict[] {
  return [
    { module: "cuotas", ok: cuotas, reason: cuotas ? "ok" : "menos_de_3_casas" },
    { module: "mi_parlay", ok: parlay, reason: parlay ? "ok" : "SIN_PROBABILIDAD" },
    { module: "picks", ok: picks, reason: picks ? "ok" : "MERCADO_NO_EVALUABLE" },
  ];
}

function market(key: string, modules: ModuleVerdict[]): MarketAvailability {
  return {
    key,
    matrix_market: key,
    exists: true,
    coverage_ok: true,
    level: "B",
    price_in_force: true,
    prob_computed: true,
    prob_authorised: true,
    settleable: true,
    reason: "ninguno",
    modules,
  };
}

function availability(
  markets: MarketAvailability[],
  blocks: BlockAvailability[] = [],
): MatchAvailability {
  return {
    fixture_id: 1,
    kickoff_at: "2034-05-01T20:00:00Z",
    competition_season_id: 1,
    blocks,
    markets,
    notes: [],
  };
}

function bookMarket(key: string, period: "FT" | "1H" = "FT"): OddsBookMarket {
  return {
    info: { key, subject: "match" } as OddsBookMarket["info"],
    period,
    main_line: null,
    lines: [],
  };
}

function book(): MatchOddsBook {
  return {
    fixture_id: 1,
    kickoff_at: "2034-05-01T20:00:00Z",
    captured_at: null,
    provider_update_at: null,
    state: "fresh",
    families: [
      { key: "goals", markets: [bookMarket("goals.total")] },
      { key: "cards", markets: [bookMarket("cards.total")] },
    ],
    bookmakers: [],
  } as unknown as MatchOddsBook;
}

describe("a module's verdict, in words", () => {
  const m = market(OU, verdicts(false, false, false));

  test("Cuotas fails at the price, Mi parlay and Picks at the rules", () => {
    expect(verdictState(m, "cuotas")).toMatchObject({ kind: "pendiente", step: "cuota" });
    expect(verdictState(m, "mi_parlay")).toMatchObject({ kind: "en_revision", step: "reglas" });
    expect(verdictState(m, "picks")).toMatchObject({ kind: "en_revision", step: "reglas" });
  });

  test("a market the module takes, or one without a verdict, says nothing", () => {
    expect(verdictState(market(OU, verdicts(true, true)), "cuotas")).toBeNull();
    expect(verdictState(market(OU, []), "cuotas")).toBeNull();
  });

  test("the notes list only what the module refuses", () => {
    const av = availability([m, market(CARDS, verdicts(true, true))]);
    const entries = marketEntries(av, "cuotas", (x) => x.key);
    expect(entries.map((e) => e.subject)).toEqual([OU]);
    expect(marketEntries(null, "cuotas", (x) => x.key)).toEqual([]);
  });

  test("Noticias says the blocks it leans on only when they are not complete", () => {
    const blocks: BlockAvailability[] = [
      { key: "lineups", exists: true, level: "A", n: 50, provisional: false, reason: "ninguno" },
      {
        key: "referee",
        exists: false,
        level: "D",
        n: 0,
        provisional: false,
        reason: "no_entregado",
      },
      { key: "xg", exists: false, level: "D", n: 0, provisional: false, reason: "no_entregado" },
    ];
    const out = blockEntries(blocks, (k) => k);
    expect(out.map((e) => e.subject)).toEqual(["referee"]);
    expect(blockEntries(null, (k) => k)).toEqual([]);
  });
});

describe("Cuotas with the matrix", () => {
  const av = availability([market(OU, verdicts(true, true)), market(CARDS, verdicts(false, true))]);

  test("a market of Cuotas finds its market of C-16 by the catalogue's key", () => {
    expect(matrixMarketOf(av, "goals.total", "FT")?.key).toBe(OU);
    expect(matrixMarketOf(av, "no.such.market", "FT")).toBeNull();
    expect(matrixMarketOf(null, "goals.total", "FT")).toBeNull();
  });

  test("off and show hand back the same book", () => {
    const b = book();
    expect(bookWithMatrix(b, av, "off")).toBe(b);
    expect(bookWithMatrix(b, av, "show")).toBe(b);
    expect(hiddenMarkets(av, "off").size).toBe(0);
    expect(hiddenMarkets(av, "show").size).toBe(0);
  });

  test("on without an answer from C-16 hands back the same book", () => {
    const b = book();
    expect(bookWithMatrix(b, null, "on")).toBe(b);
    expect(bookWithMatrix(undefined, av, "on")).toBeUndefined();
  });

  test("on leaves out the markets C-16 lists with no price in force, and only those", () => {
    const hidden = hiddenMarkets(av, "on");
    expect([...hidden]).toEqual([CARDS]);
    const b = book();
    const seen = bookWithMatrix(b, av, "on");
    expect(seen?.families.map((f) => f.key)).toEqual(["goals"]);
    // the book that came is not touched, and a market C-16 does not list stays
    expect(b.families.length).toBe(2);
    const unknown = availability([market("something.else", verdicts(false, false))]);
    expect(bookWithMatrix(b, unknown, "on")?.families.length).toBe(2);
  });
});

describe("Mi parlay with the matrix", () => {
  const refused = market(OU, verdicts(true, false));
  const taken = market(OU, verdicts(true, true));

  test("a flag C-14 refuses stays refused, whatever the matrix says", () => {
    expect(parlayAllowed(false, taken, "on")).toBe(false);
    expect(parlayAllowed(false, null, "off")).toBe(false);
  });

  test("off and show leave C-14's flag as it is", () => {
    expect(parlayAllowed(true, refused, "off")).toBe(true);
    expect(parlayAllowed(true, refused, "show")).toBe(true);
  });

  test("on takes it away only when C-16 refuses the market, and keeps it when C-16 is silent", () => {
    expect(parlayAllowed(true, refused, "on")).toBe(false);
    expect(parlayAllowed(true, taken, "on")).toBe(true);
    expect(parlayAllowed(true, null, "on")).toBe(true);
    expect(parlayAllowed(true, market(OU, []), "on")).toBe(true);
    expect(parlayRefusal(refused)).toBe("SIN_PROBABILIDAD");
    expect(parlayRefusal(taken)).toBeNull();
  });

  function probs(): MarketProbs {
    const base = fixture as unknown as MarketProbs;
    const first = base.markets.items[0]!;
    const m = {
      ...first,
      key: OU,
      rule_key: "goals_ft@v1",
      selections: [
        {
          ...first.selections[0]!,
          selection: "Over",
          line: 2.5,
          parlay: { allowed: true, reason: "ok" },
        },
      ],
    };
    return { ...base, markets: { ...base.markets, items: [m] } } as MarketProbs;
  }
  const id = selectionId(OU, "Over", 2.5);

  test("catalogParlayOf: off, show and no matrix give the same flags", () => {
    const plain = catalogParlayOf(probs());
    expect(plain.allowed.has(id)).toBe(true);
    for (const mode of ["off", "show"] as const) {
      const cp = catalogParlayOf(probs(), { mode, availability: availability([refused]) });
      expect([...cp.allowed]).toEqual([...plain.allowed]);
    }
  });

  test("catalogParlayOf: on drops the selections of a market C-16 refuses, with its reason", () => {
    const cp = catalogParlayOf(probs(), { mode: "on", availability: availability([refused]) });
    expect(cp.allowed.size).toBe(0);
    expect(cp.reasons?.get(id)).toBe("SIN_PROBABILIDAD");
    const ok = catalogParlayOf(probs(), { mode: "on", availability: availability([taken]) });
    expect(ok.allowed.has(id)).toBe(true);
    const silent = catalogParlayOf(probs(), { mode: "on", availability: null });
    expect(silent.allowed.has(id)).toBe(true);
  });
});
