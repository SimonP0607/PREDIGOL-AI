/// <reference types="bun" />
/**
 * REVIEW PREDIGOL, point 15, rendered: every leg says why it is there, and an empty builder says why there is no
 * parlay and what to change - never a padded parlay.
 */
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import type { BuiltParlay } from "@/lib/api/v1/types_builder";
import { LegWhy } from "./LegWhy";
import { NoParlay } from "./BuilderResult";

setLocale("es");
const text = (html: string) => html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");

describe("why a leg is in the parlay (REVIEW point 15)", () => {
  test("PrediGol against the market, the prudent end, the price against fair, EV and books", () => {
    const html = text(
      renderToStaticMarkup(
        <LegWhy
          frozen={false}
          why={{
            p_model: "0.55",
            p_low: "0.50",
            p_market: "0.45",
            odds: "2.30",
            ev: "0.265",
            books: 4,
          }}
        />,
      ),
    );
    expect(html).toContain("PrediGol le da 55,0 %");
    expect(html).toContain("al menos 50,0 %");
    expect(html).toContain("el mercado, 45,0 %");
    expect(html).toContain("Cuota 2,30 frente a un precio justo de 2,22");
    expect(html).toContain("+3,5 % frente al justo");
    expect(html).toContain("a la cuota de ahora");
    expect(html).toContain("4 casas");
  });

  test("a recorded leg: the price it was taken at; the AI's decision only where the reader may see it", () => {
    const hidden = text(
      renderToStaticMarkup(
        <LegWhy
          frozen
          why={{
            p_model: "0.55",
            p_market: "0.45",
            odds: "2.30",
            ev: "0.265",
            ai: { decision: null, mode: "shadow", enforced: false, by_llm: false },
          }}
        />,
      ),
    );
    expect(hidden).toContain("con la cuota con que se tomó");
    expect(hidden).not.toContain("confirmado");
    expect(hidden).not.toContain("casas");
    const shown = text(
      renderToStaticMarkup(
        <LegWhy
          frozen
          why={{
            p_model: "0.55",
            p_market: "0.45",
            odds: "2.30",
            ev: "0.265",
            ai: {
              decision: "APPROVE",
              mode: "shadow",
              enforced: false,
              by_llm: true,
              reason: "Bajas confirmadas.",
            },
          }}
        />,
      ),
    );
    expect(shown).toContain("confirmado");
    expect(shown).toContain("Bajas confirmadas.");
  });
});

function empty(reason: BuiltParlay["reason"], extra: Partial<BuiltParlay> = {}): BuiltParlay {
  return {
    status: "no_valid_parlay",
    reason,
    source: "qualified",
    rule_version: "builder-v1",
    parlay_rule: "parlay-v4",
    filters: {
      hours: 24,
      min_legs: 3,
      max_legs: 4,
      markets: [],
      competition_ids: [],
      min_odds: null,
      max_odds: null,
      max_total_odds: "4",
    },
    legs: [],
    combined_odds: null,
    p_all_low: null,
    p_all_market: null,
    expected_log_growth: null,
    risk: null,
    correlated_pairs: 0,
    funnel: { passing: 14, risk: 14, reviewed: 14, matching: 14, combinable: 14, matches: 2 },
    competitions: [],
    markets: [],
    prices_as_of: null,
    generated_at: "2032-08-01T15:00:00Z",
    ...extra,
  };
}

describe("no parlay: why, and what to change (REVIEW point 15)", () => {
  test("the cap on the total odds", () => {
    const html = text(renderToStaticMarkup(<NoParlay body={empty("total_odds_cap")} />));
    expect(html).toContain("cuota total máxima de 4");
    expect(html).toContain("Prueba subiendo la cuota total máxima");
    expect(html).toContain("Nunca rellenamos");
  });

  test("too few matches, counted", () => {
    const html = text(renderToStaticMarkup(<NoParlay body={empty("too_few_legs")} />));
    expect(html).toContain("en 2 partidos");
    expect(html).toContain("mínimo de 3");
  });

  test("nothing passes the rules: no funnel to show, come back later", () => {
    const html = text(
      renderToStaticMarkup(
        <NoParlay
          body={empty("no_candidates", {
            funnel: { passing: 0, risk: 0, reviewed: 0, matching: 0, combinable: 0, matches: 0 },
          })}
        />,
      ),
    );
    expect(html).toContain("no hay selecciones que pasen las reglas");
    expect(html).toContain("Vuelve más tarde");
    expect(html).not.toContain("De 0 selecciones");
  });
});

describe("the risk and context stages, said (REVIEW B1)", () => {
  test("everything above the cap", () => {
    const html = text(
      renderToStaticMarkup(
        <NoParlay
          body={empty("risk_cap", {
            funnel: {
              passing: 9,
              risk: 0,
              reviewed: 0,
              matching: 0,
              combinable: 0,
              matches: 0,
              max_odds: "3.00",
            },
          })}
        />,
      ),
    );
    expect(html).toContain("pagan más de 3,00");
    expect(html).toContain("las cuotas altas pierden dinero");
  });

  test("not reviewed by PrediGol Intelligence yet", () => {
    const html = text(renderToStaticMarkup(<NoParlay body={empty("not_reviewed")} />));
    expect(html).toContain("aún no han pasado por PrediGol Intelligence");
    expect(html).toContain("Vuelve más tarde");
  });
});
