/// <reference types="bun" />
/**
 * REVIEW PREDIGOL B1, the owner's selection funnel rendered (regressions from the P5 visual check): a stage's stop
 * reasons read count first ("3 cuota por encima del tope", never "tope 3"), a candidate stopped because PrediGol
 * Intelligence has not read it says so once (no second "sin revisar" badge), and its probabilities are labelled.
 */
import { describe, expect, test } from "bun:test";
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { setLocale } from "@/lib/i18n";
import type { FunnelItem, SelectionFunnel } from "@/lib/api/v1/types_funnel";
import { FunnelBody } from "./FunnelPanel";

setLocale("es");
const text = (html: string) => html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");

async function render(node: ReactNode): Promise<string> {
  const router = createRouter({
    routeTree: createRootRoute({ component: () => node }),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  await router.load();
  return text(renderToStaticMarkup(<RouterProvider router={router} />));
}

function item(over: Partial<FunnelItem>): FunnelItem {
  return {
    day: null,
    stage: null,
    reason: null,
    pick_id: 1,
    fixture_id: 1,
    kickoff_at: "2026-10-12T12:34:00Z",
    competition: { id: 1, name: "Primera A", country: null, logo_url: null, flag_url: null },
    home: { id: 1, name: "Villarreal", logo_url: null },
    away: { id: 2, name: "Betis", logo_url: null },
    market_key: "1X2",
    selection: "Home",
    line: "0",
    odds: "2.29",
    bookmaker: null,
    p_model: "0.537",
    p_low: "0.505",
    p_market: "0.45",
    ev: "0.23",
    growth: "0.001",
    ai_decision: null,
    evidence: {},
    day_pass: true,
    web_searched: false,
    ...over,
  };
}

const funnel: SelectionFunnel = {
  at: "2026-10-11T16:00:00Z",
  source: "evaluation",
  rule_version: "daily-set-v5",
  risk_version: "risk-v1",
  max_odds: "3.00",
  context_version: "context-v2",
  ai_mode: "shadow",
  ai_enforced: false,
  candidates: 14,
  selections: 14,
  stages: [
    { key: "value", entered: 14, passed: 12, reasons: { no_pessimistic_growth: 2 } },
    { key: "risk", entered: 12, passed: 9, reasons: { odds_above_cap: 3 } },
    { key: "context", entered: 9, passed: 0, reasons: { not_reviewed: 9 } },
  ],
  chosen: [],
  near: [
    item({ stage: "context", reason: "not_reviewed" }),
    item({
      pick_id: 2,
      fixture_id: 2,
      stage: "risk",
      reason: "odds_above_cap",
      odds: "3.33",
      home: { id: 3, name: "América de Cali", logo_url: null },
      away: { id: 4, name: "Junior", logo_url: null },
    }),
    item({
      pick_id: 3,
      fixture_id: 3,
      stage: "selection",
      reason: "day_full",
      ai_decision: "APPROVE",
      evidence: { PROBABLE: 1, RUMOR: 2 },
      web_searched: true,
      home: { id: 5, name: "Arsenal", logo_url: null },
      away: { id: 6, name: "Chelsea", logo_url: null },
    }),
  ],
  in_set: { "2026-10-11": 5 },
  days_ready: ["2026-10-11"],
};

describe("the owner's selection funnel (REVIEW B1)", () => {
  test("each stage's stop reasons read count first", async () => {
    const html = await render(<FunnelBody d={funnel} />);
    expect(html).toContain("2 no crece en el escenario prudente");
    expect(html).toContain("3 cuota por encima del tope");
    expect(html).toContain("9 PrediGol Intelligence no la ha revisado");
    expect(html).not.toContain("tope 3");
  });

  test("an unreviewed candidate says so once; a price stop still says nobody reviewed it", async () => {
    const one = await render(<FunnelBody d={{ ...funnel, near: [funnel.near[0]!] }} />);
    expect(one.match(/no la ha revisado/g)).toHaveLength(2); // the stage row and the item, not a third badge
    expect(one).not.toContain("sin revisar");
    const price = await render(<FunnelBody d={{ ...funnel, near: [funnel.near[1]!] }} />);
    expect(price).toContain("cuota por encima del tope");
    expect(price).toContain("sin revisar");
  });

  test("the probabilities are labelled; a reviewed candidate shows the AI's decision and the evidence", async () => {
    const html = await render(<FunnelBody d={funnel} />);
    expect(html).toContain("Modelo 53,7 % (prudente 50,5 %) · mercado 45,0 %");
    expect(html).toContain("1 probable");
    expect(html).toContain("2 rumor");
    expect(html).toContain("IA");
  });

  test("daily-set-v5: whether PrediGol Intelligence has read the day, and each candidate's pass and news search", async () => {
    const read = await render(<FunnelBody d={funnel} />);
    expect(read).toContain("Día leído por PrediGol Intelligence: 2026-10-11");
    expect(read).toContain("pasada del día");
    expect(read).toContain("noticias buscadas");
    expect(read).toContain("sin búsqueda de noticias");
    const waiting = await render(
      <FunnelBody
        d={{
          ...funnel,
          days_ready: [],
          stages: [{ key: "context", entered: 9, passed: 0, reasons: { day_not_ready: 9 } }],
          near: [item({ stage: "context", reason: "day_not_ready", day_pass: false })],
        }}
      />,
    );
    expect(waiting).toContain("aún no termina la primera pasada del día");
    expect(waiting).toContain("9 PrediGol Intelligence aún no lee el día completo");
    expect(waiting.match(/pasada del día/g)).toHaveLength(1); // the day's note only: no "pasada del día" badge
  });
});
