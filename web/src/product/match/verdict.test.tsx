/// <reference types="bun" />
/**
 * "Recomendado" says that the AI's review of context has not acted yet (plan UX, A1, defect F48): every published pick
 * read "Recomendado" while the review of context ran in shadow. Until it is applied, a recommended card carries
 * «Revisión de contexto aún no aplicada» beside its verdict; the other verdicts, and an applied review, do not.
 */
import { afterAll, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import type { AnalysisCard } from "@/lib/api/v1/types_ai_layer";
import { setLocale } from "@/lib/i18n";
import { AnalysisCardView } from "./AnalysisBlock";

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

const render = (c: AnalysisCard, contextPending: boolean) =>
  renderToStaticMarkup(
    <AnalysisCardView
      card={c}
      home="Millonarios"
      away="Santa Fe"
      contextPending={contextPending}
    />,
  );

afterAll(() => setLocale("es"));

describe("a recommended card while the review of context is not applied", () => {
  test("says so beside «Recomendado», in Spanish and English", () => {
    setLocale("es");
    const es = render(card(), true);
    expect(es).toContain("Recomendado");
    expect(es).toContain('data-testid="verdict-context-pending"');
    expect(es).toContain("Revisión de contexto aún no aplicada");
    setLocale("en");
    expect(render(card(), true)).toContain("Context review not applied yet");
  });

  test("an applied review, or another verdict, carries no such line", () => {
    setLocale("es");
    expect(render(card(), false)).not.toContain("verdict-context-pending");
    for (const verdict of ["caution", "not_recommended", "no_market"] as const) {
      expect(render(card({ verdict }), true)).not.toContain("verdict-context-pending");
    }
  });
});
