/// <reference types="bun" />
/** PREDIGOL INTELLIGENCE in words: full titles, percentage points, why / what could go wrong, the brief. */
import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import type { AiClaim, AnalysisCard, CardAi } from "@/lib/api/v1/types_ai_layer";
import { setLocale } from "@/lib/i18n";
import {
  analysisUpdatedAt,
  briefAuthor,
  briefReason,
  cardLeg,
  cardTitle,
  failsInTen,
  injuryLine,
  injuryStatus,
  marketTitle,
  ppParts,
  riskLines,
  whyLines,
} from "./intelligence";

const SIDES = { home: "Millonarios", away: "Independiente Santa Fe" };

function card(over: Partial<AnalysisCard> = {}): AnalysisCard {
  return {
    market: "1X2",
    selection: "Home",
    line: "0.00",
    kind: "value",
    odds: "2.10",
    bookmaker: "Betplay",
    p_model: "0.58",
    p_low: "0.53",
    p_market: "0.51",
    fair_odds: "1.724",
    minimum_odds: "1.95",
    edge: "0.07",
    ev: "0.218",
    model: "dc-v3",
    qualified: true,
    verdict: "recommended",
    verdict_reason: "value",
    ai: null,
    notes: null,
    ...over,
  };
}

const claim = (text: string): AiClaim => ({ text, type: "DATA" });

function review(over: Partial<CardAi> = {}): CardAi {
  return {
    decision: "APPROVE",
    review_id: 7,
    confidence: 0.72,
    reason: "Sin bajas relevantes.",
    positives: [],
    risks: [],
    engines: ["rules"],
    ...over,
  };
}

/** Intl puts a no-break space before "%" in Spanish: compare words, not space characters. */
const plain = (lines: string[]) => lines.map((s) => s.replace(/\u00a0/g, " "));

beforeEach(() => setLocale("es"));
afterEach(() => setLocale("es"));

describe("the card's full title", () => {
  test("market title — selection phrase, in Spanish", () => {
    expect(cardTitle(card(), SIDES)).toBe("Resultado final (1X2) — Gana Millonarios");
    expect(cardTitle(card({ selection: "Draw" }), SIDES)).toBe("Resultado final (1X2) — Empate");
    expect(cardTitle(card({ market: "OU", selection: "Over", line: "2.50" }), SIDES)).toBe(
      "Goles: más/menos de 2,5 — Más de 2,5",
    );
    expect(cardTitle(card({ market: "OU", selection: "Under", line: "3.5" }), SIDES)).toBe(
      "Goles: más/menos de 3,5 — Menos de 3,5",
    );
    expect(cardTitle(card({ market: "BTTS", selection: "Yes" }), SIDES)).toBe("Ambos marcan — Sí");
    expect(cardTitle(card({ market: "DC", selection: "1X" }), SIDES)).toBe(
      "Doble oportunidad — Millonarios o empate",
    );
    expect(cardTitle(card({ market: "AH", selection: "Away", line: "0.5" }), SIDES)).toBe(
      "Hándicap asiático — Independiente Santa Fe +0,5",
    );
  });

  test("never cut: a long team name is there whole", () => {
    const title = cardTitle(card({ selection: "Away" }), SIDES);
    expect(title).toBe("Resultado final (1X2) — Gana Independiente Santa Fe");
    expect(title).not.toContain("…");
  });

  test("in English", () => {
    setLocale("en");
    expect(cardTitle(card(), SIDES)).toBe("Full-time result (1X2) — Millonarios to win");
    expect(cardTitle(card({ market: "OU", selection: "Over", line: "2.5" }), SIDES)).toBe(
      "Goals: over/under 2.5 — Over 2.5",
    );
    expect(cardTitle(card({ market: "BTTS", selection: "No" }), SIDES)).toBe(
      "Both teams to score — No",
    );
  });

  test("an unknown market or a missing line falls back to what is known", () => {
    expect(marketTitle("XYZ", null)).toBe("XYZ");
    expect(marketTitle("OU", null)).toBe("Más/Menos goles");
  });
});

describe("the edge in percentage points", () => {
  test("times 100, signed, one decimal, with its unit apart", () => {
    expect(ppParts("0.07")).toEqual({ value: "+7,0", unit: "pp" });
    expect(ppParts(-0.021)).toEqual({ value: "-2,1", unit: "pp" });
    expect(ppParts(0)).toEqual({ value: "0,0", unit: "pp" });
    setLocale("en");
    // 0.0745 * 100 is 7.4499... in binary: a half still rounds up.
    expect(ppParts("0.0745")).toEqual({ value: "+7.5", unit: "pp" });
  });

  test("nothing without an edge (the figure shows a dash)", () => {
    expect(ppParts(null)).toBe(null);
    expect(ppParts(undefined)).toBe(null);
    expect(ppParts("not a number")).toBe(null);
  });
});

describe("why", () => {
  test("from the numbers alone when nobody wrote anything", () => {
    expect(plain(whyLines(card()))).toEqual([
      "PrediGol estima 58,0 % frente a 51,0 % del mercado",
      "Ventaja de 7,0 pp sobre el precio justo del mercado",
    ]);
  });

  test("no edge line without a positive edge", () => {
    expect(plain(whyLines(card({ edge: "-0.02", verdict: "not_recommended" })))).toEqual([
      "PrediGol estima 58,0 % frente a 51,0 % del mercado",
    ]);
    expect(plain(whyLines(card({ edge: null })))).toHaveLength(1);
  });

  test("the brief's notes first, then the review's positives - never mixed with the numbers", () => {
    const withBoth = card({
      notes: { why: [claim(" Llega invicto en casa "), claim("  ")], risks: [] },
      ai: review({ positives: [claim("Mejor forma reciente")] }),
    });
    expect(whyLines(withBoth)).toEqual(["Llega invicto en casa"]);
    const reviewOnly = card({
      notes: { why: [], risks: [] },
      ai: review({ positives: [claim("Mejor forma reciente")] }),
    });
    expect(whyLines(reviewOnly)).toEqual(["Mejor forma reciente"]);
  });

  test("without a market: PrediGol's estimate and the price it would take, never an edge", () => {
    const unpriced = card({
      kind: "no_market",
      verdict: "no_market",
      odds: null,
      bookmaker: null,
      p_market: null,
      edge: "0.05",
    });
    expect(plain(whyLines(unpriced))).toEqual([
      "PrediGol estima una probabilidad de 58,0 % para esta selección",
      "Solo tendría valor con una cuota de 1,95 o más",
    ]);
  });

  test("an honest line when there are no figures at all", () => {
    expect(whyLines(card({ p_model: null, p_market: null, edge: null }))).toEqual([
      "Todavía no hay cifras suficientes para explicarlo.",
    ]);
  });
});

describe("what could go wrong", () => {
  test("variance from PrediGol's own probability", () => {
    expect(riskLines(card())).toEqual([
      "Aun así, esta selección falla aproximadamente 4 de cada 10 veces",
    ]);
    setLocale("en");
    expect(riskLines(card())).toEqual(["Even so, this selection loses about 4 times in 10"]);
  });

  test("without a market it says value cannot be confirmed", () => {
    expect(riskLines(card({ kind: "no_market", verdict: "no_market", odds: null }))).toEqual([
      "Sin un precio observado no se puede confirmar que tenga valor.",
      "Aun así, esta selección falla aproximadamente 4 de cada 10 veces",
    ]);
  });

  test("the brief's risks first, then the review's", () => {
    const both = card({
      notes: { why: [], risks: [claim("Rotaciones por la Copa")] },
      ai: review({ risks: [claim("Árbitro estricto")] }),
    });
    expect(riskLines(both)).toEqual(["Rotaciones por la Copa"]);
    expect(riskLines(card({ ai: review({ risks: [claim("Árbitro estricto")] }) }))).toEqual([
      "Árbitro estricto",
    ]);
  });

  test("never silent", () => {
    expect(riskLines(card({ p_model: null }))).toEqual([
      "Ninguna selección es segura: también puede fallar.",
    ]);
  });

  test("failsInTen: round((1 − p) × 10) half up, at least 1, at most 9", () => {
    expect(failsInTen("0.58")).toBe(4);
    expect(failsInTen(0.55)).toBe(5);
    expect(failsInTen(0.65)).toBe(4);
    expect(failsInTen(0.97)).toBe(1);
    expect(failsInTen(0.999)).toBe(1);
    expect(failsInTen(0.1)).toBe(9);
    expect(failsInTen(0.02)).toBe(9);
    expect(failsInTen(null)).toBe(null);
    expect(failsInTen("abc")).toBe(null);
    expect(failsInTen(1.4)).toBe(null);
  });
});

describe("the day's reading (L1)", () => {
  test("who wrote it", () => {
    expect(briefAuthor({ engine: "llm", model: "gpt-5-mini" })).toBe("Escrito por gpt-5-mini (L1)");
    expect(briefAuthor({ engine: "llm", model: null })).toBe("Escrito por PrediGol AI (L1)");
    expect(briefAuthor({ engine: "rules", model: null })).toBe("Escrito por las reglas");
    setLocale("en");
    expect(briefAuthor({ engine: "rules", model: "x" })).toBe("Written by the rules");
  });

  test("escalation reasons in words; an unknown one reads as its words", () => {
    expect(briefReason("model_market_gap")).toBe("Brecha entre modelo y mercado");
    expect(briefReason("candidate")).toBe("Candidato a pick");
    expect(briefReason("brand_new_reason")).toBe("brand new reason");
  });

  test("injuries: team · player · status", () => {
    expect(injuryLine({ side: "home", player: "D. Ruiz", status: "Doubtful" }, SIDES)).toBe(
      "Millonarios · D. Ruiz · duda",
    );
    expect(injuryLine({ side: "away", player: "H. Rodallega", status: "" }, SIDES)).toBe(
      "Independiente Santa Fe · H. Rodallega",
    );
    expect(injuryStatus("out")).toBe("baja");
    expect(injuryStatus("rodilla (2 semanas)")).toBe("rodilla (2 semanas)");
    expect(injuryStatus(null)).toBe("");
  });

  test("updated: the newest of the analysis and its brief", () => {
    expect(
      analysisUpdatedAt({ built_at: "2026-10-08T10:00:00Z", updated_at: "2026-10-08T11:00:00Z" }),
    ).toBe("2026-10-08T11:00:00Z");
    expect(analysisUpdatedAt({ built_at: "2026-10-08T10:00:00Z" })).toBe("2026-10-08T10:00:00Z");
    expect(analysisUpdatedAt({ built_at: null, updated_at: null })).toBe(null);
  });
});

describe("the leg a card adds to the parlay", () => {
  const match = { fixture_id: 812, kickoff_at: "2032-08-01T18:00:00Z", status_group: "scheduled" };

  test("its best price, the match's kick-off and PrediGol's probability", () => {
    expect(cardLeg(card({ market: "OU", selection: "Over", line: "2.50" }), match, SIDES)).toEqual({
      fixture_id: 812,
      market_key: "OU",
      selection: "Over",
      line: "2.5",
      home: "Millonarios",
      away: "Independiente Santa Fe",
      kickoff_at: "2032-08-01T18:00:00Z",
      odds: "2.10",
      bookmaker: "Betplay",
      p_model: "0.58",
    });
  });

  test("nothing for an unpriced market or one a parlay does not take", () => {
    expect(cardLeg(card({ kind: "no_market", odds: null }), match, SIDES)).toBe(null);
    expect(cardLeg(card({ market: "CORNERS" }), match, SIDES)).toBe(null);
  });
});
