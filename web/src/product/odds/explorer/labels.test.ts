/// <reference types="bun" />
/**
 * Markets and selections in words. Every tax-v3 market has a name in both languages (one name: the five classic ones keep
 * the product's); an Asian handicap reads «Local -0,25 · Visitante +0,25», each side at its own signed line (plan Cuotas,
 * E1); a European handicap's away side at the opposite of the home handicap; the price figures never mix and the difference
 * with the fair price is said in grey words, «sobre» or «bajo» la justa.
 */
import { afterAll, describe, expect, test } from "bun:test";
import { setLocale } from "@/lib/i18n";
import {
  MARKET_ORDER,
  chipTitle,
  classicMarket,
  isClassic,
  marketTitle,
  parseMarketKey,
  shapeOf,
} from "./markets";
import type { OddsMarketInfo, OddsSelectionPrice } from "./model";
import { edgeText, ownLine, priceDescription, selectionLabel } from "./selections";

setLocale("es");
afterAll(() => setLocale("es"));

const sides = { home: "Brighton", away: "Brentford" };

function market(key: string, kind = "", extra: Partial<OddsMarketInfo> = {}): OddsMarketInfo {
  return {
    key,
    family: "result",
    kind,
    subject: "match",
    periods: ["FT"],
    has_line: false,
    fair: true,
    parlay: false,
    fixtures: 1,
    max_books: 8,
    ...extra,
  };
}

function sel(selection: string, line: string | null = null, player: string | null = null) {
  return { selection, line, player };
}

const label = (key: string, s: ReturnType<typeof sel>, rowLine: string | null = null, kind = "") =>
  selectionLabel(market(key, kind), s, rowLine, sides);
const full = (key: string, s: ReturnType<typeof sel>, rowLine: string | null = null, kind = "") =>
  selectionLabel(market(key, kind), s, rowLine, sides, "full");

describe("market keys", () => {
  test("the parts: the base, an interval and a team, whatever else the key keeps", () => {
    expect(parseMarketKey("corners.total")).toEqual({
      base: "corners.total",
      minutes: null,
      team: null,
    });
    expect(parseMarketKey("goals.total.1h.home")).toEqual({
      base: "goals.total",
      minutes: null,
      team: "home",
    });
    expect(parseMarketKey("result.1x2.m0_15")).toEqual({
      base: "result.1x2",
      minutes: [0, 15],
      team: null,
    });
  });

  test("the shape: the API's kind when it names a reader, else the key's", () => {
    expect(shapeOf(market("result.asian_handicap", "signed_line"))).toBe("ah");
    expect(shapeOf(market("corners.asian_handicap", "anything"))).toBe("ah");
    expect(shapeOf(market("cards.european_handicap"))).toBe("eh");
    expect(shapeOf(market("corners.race", "line"))).toBe("race");
    expect(shapeOf(market("goals.correct_score.1h"))).toBe("exact_score");
    expect(shapeOf(market("player.shots"))).toBe("player_count");
    expect(shapeOf(market("player.first_scorer"))).toBe("player");
    expect(shapeOf(market("goals.total.home"))).toBe("line");
    expect(shapeOf(market("special.own_goal"))).toBe("plain");
  });

  test("the slip's market: only the five classic ones, for the match and the full time, when the API says parlay", () => {
    const parlay = { parlay: true };
    expect(classicMarket(market("result.1x2", "plain", parlay), "FT")).toBe("1X2");
    expect(classicMarket(market("goals.total", "line", parlay), "FT")).toBe("OU");
    expect(classicMarket(market("goals.btts", "plain", parlay), "FT")).toBe("BTTS");
    expect(classicMarket(market("result.asian_handicap", "signed_line", parlay), "FT")).toBe("AH");
    expect(classicMarket(market("result.double_chance", "plain", parlay), "FT")).toBe("DC");
    expect(classicMarket(market("result.1x2", "plain", parlay), "1H")).toBeNull();
    expect(classicMarket(market("result.1x2", "plain"), "FT")).toBeNull();
    expect(
      classicMarket(market("goals.total.home", "line", { ...parlay, subject: "home" }), "FT"),
    ).toBeNull();
    expect(classicMarket(market("corners.total", "line", parlay), "FT")).toBeNull();
    expect(isClassic(market("result.1x2.m0_15"))).toBe(false);
  });
});

describe("market names", () => {
  test("every market of tax-v3 has its own name, in Spanish and in English", () => {
    for (const locale of ["es", "en"] as const) {
      setLocale(locale);
      const unknown = locale === "es" ? "Otro mercado" : "Another market";
      const missing = MARKET_ORDER.filter((base) => marketTitle(market(base)) === unknown);
      expect(missing).toEqual([]);
      const names = MARKET_ORDER.map((base) => marketTitle(market(base)));
      expect(new Set(names).size).toBe(names.length);
    }
    setLocale("es");
  });

  test("the five keep the product's one name; a team, an interval and a key never seen", () => {
    expect(marketTitle(market("result.asian_handicap"))).toBe("Hándicap asiático");
    expect(marketTitle(market("goals.total"))).toBe("Más/Menos goles");
    expect(marketTitle(market("goals.total.home"))).toBe("Más/Menos goles · Local");
    expect(marketTitle(market("corners.total", "line", { subject: "away" }))).toBe(
      "Córners: más/menos · Visitante",
    );
    expect(marketTitle(market("result.1x2.m0_15"))).toBe("Resultado final (1X2) · 0–15 min");
    expect(marketTitle(market("weird.thing"))).toBe("Otro mercado");
  });

  test("a chip in its own family's tab does not repeat the family", () => {
    expect(chipTitle(market("corners.total"), true)).toBe("Más/menos");
    expect(chipTitle(market("corners.total"), false)).toBe("Córners: más/menos");
    expect(chipTitle(market("result.1x2"), true)).toBe("1X2");
    expect(chipTitle(market("player.anytime_scorer"), true)).toBe("Goleador en cualquier momento");
  });
});

describe("an Asian handicap (E1)", () => {
  const AH = "result.asian_handicap";
  test("reads «Local -0,25 · Visitante +0,25»: each side at its own signed line", () => {
    expect([
      label(AH, sel("Home", "-0.25"), "-0.25"),
      label(AH, sel("Away", "0.25"), "-0.25"),
    ]).toEqual(["Local -0,25", "Visitante +0,25"]);
    expect(full(AH, sel("Away", "0.25"), "-0.25")).toBe("Brentford +0,25");
  });

  test("without the selection's own line, the away side is the opposite of the row's home line; a level line is 0", () => {
    expect(label(AH, sel("Away"), "-1.5")).toBe("Visitante +1,5");
    expect(label(AH, sel("Away"), "0")).toBe("Visitante 0");
    expect(ownLine("ah", sel("Away"), "0")).toBe(0);
    expect(Object.is(ownLine("ah", sel("Away"), "0"), -0)).toBe(false);
  });

  test("the corners' and the cards' read the same way", () => {
    expect(label("corners.asian_handicap", sel("Away", "1.5"), "-1.5")).toBe("Visitante +1,5");
  });
});

describe("a European handicap", () => {
  const EH = "result.european_handicap";
  test("three ways at the home handicap, the away side at its opposite, whatever the selection carries", () => {
    expect([
      label(EH, sel("Home", "-1"), "-1"),
      label(EH, sel("Draw", "-1"), "-1"),
      label(EH, sel("Away", "-1"), "-1"),
    ]).toEqual(["Local -1", "Empate (-1)", "Visitante +1"]);
    expect(full(EH, sel("Away", "-1"), "-1")).toBe("Brentford +1");
  });
});

describe("the other shapes", () => {
  test("1X2: 1, X, 2 in a cell; the teams for a screen reader", () => {
    expect(["Home", "Draw", "Away"].map((s) => label("result.1x2", sel(s)))).toEqual([
      "1",
      "X",
      "2",
    ]);
    expect(["Home", "Draw", "Away"].map((s) => full("result.1x2", sel(s)))).toEqual([
      "Brighton",
      "Empate",
      "Brentford",
    ]);
  });

  test("over/under at its line; double chance; both score; odd/even", () => {
    expect(label("goals.total", sel("Over", "2.5"), "2.5")).toBe("Más 2,5");
    expect(label("corners.total_3way", sel("Exactly", "10"), "10")).toBe("Exactamente 10");
    expect(label("result.double_chance", sel("1X"))).toBe("1X");
    expect(full("result.double_chance", sel("X2"))).toBe("Empate o Brentford");
    expect(label("goals.btts", sel("No"))).toBe("No");
    expect(label("goals.odd_even", sel("Even"))).toBe("Par");
  });

  test("scores, counts, bands, half-time/full-time, result and total, margins, a race", () => {
    expect(label("goals.correct_score", sel("2:1"))).toBe("2:1");
    expect(label("goals.exact_total", sel("6+"))).toBe("6+");
    expect(label("corners.total_bands", sel("6-8"))).toBe("6–8");
    expect(label("halves.ht_ft", sel("Home/Draw"))).toBe("1/X");
    expect(full("halves.ht_ft", sel("Home/Draw"))).toBe("Brighton / Empate");
    expect(label("goals.result_total", sel("Away/Over", "2.5"), "2.5")).toBe("2 / Más 2,5");
    expect(label("goals.total_btts", sel("Over/Yes", "2.5"), "2.5")).toBe("Más 2,5 / Sí");
    expect(label("goals.result_btts", sel("Draw/No"))).toBe("X / No");
    expect(label("goals.winning_margin", sel("2 by 4+"))).toBe("Visitante por 4+");
    expect(full("goals.winning_margin", sel("1 by 2"))).toBe("Brighton por 2");
    expect(label("goals.winning_margin", sel("No goal"))).toBe("Sin goles");
    expect(label("corners.race", sel("Home", "5"), "5", "line")).toBe("Local primero a 5");
    expect(label("corners.race", sel("Draw", "5"), "5", "line")).toBe("Nadie llega a 5");
    expect(label("halves.highest_scoring", sel("Draw"))).toBe("Igual");
    expect(label("cards.first_card", sel("Draw"))).toBe("Ninguno");
    expect(label("special.first_goal_method", sel("FreeKick"))).toBe("Falta directa");
  });

  test("players: the name, the outcomes that are not players, a count to reach", () => {
    expect(label("player.anytime_scorer", sel("Danny Welbeck", null, "Danny Welbeck"))).toBe(
      "Danny Welbeck",
    );
    expect(label("player.first_scorer", sel("No Goalscorer"))).toBe("Sin goleador");
    expect(label("keeper.saves", sel("Bart Verbruggen", "3", "Bart Verbruggen"))).toBe(
      "Bart Verbruggen · 3+",
    );
  });

  test("in English", () => {
    setLocale("en");
    expect(label("result.asian_handicap", sel("Away", "0.25"), "-0.25")).toBe("Away +0.25");
    expect(label("goals.total", sel("Under", "2.5"), "2.5")).toBe("Under 2.5");
    setLocale("es");
  });
});

describe("the price figures", () => {
  test("the difference with the market's fair price: «sobre», «bajo» or «igual a» la justa", () => {
    expect(edgeText("0.014")).toBe("+1,4\u00a0% sobre la justa");
    expect(edgeText("-0.021")).toBe("-2,1\u00a0% bajo la justa");
    expect(edgeText("0.0001")).toBe("Igual a la justa");
    expect(edgeText(null)).toBeNull();
  });

  test("a screen reader hears the best price, its bookmaker and how many quote it; the fair price only where there is one", () => {
    const price: Pick<OddsSelectionPrice, "best_odds" | "n_books" | "fair_odds" | "price_edge"> = {
      best_odds: "1.95",
      n_books: 8,
      fair_odds: "1.92",
      price_edge: "0.0156",
    };
    expect(priceDescription("Más 2,5", price, "Bet365")).toBe(
      "Más 2,5: mejor cuota 1,95 en Bet365, entre 8 casas. Justa del mercado 1,92. +1,6\u00a0% sobre la justa.",
    );
    expect(
      priceDescription(
        "Welbeck",
        { ...price, n_books: 1, fair_odds: null, price_edge: null },
        "Bet365",
      ),
    ).toBe("Welbeck: mejor cuota 1,95 en Bet365, la única casa que la cotiza.");
  });
});
