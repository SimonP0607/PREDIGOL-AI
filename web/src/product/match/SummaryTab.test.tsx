/// <reference types="bun" />
/**
 * The Resumen before kick-off (plan de cierre UX, 2.2): what is read to go deeper - form, table, head to head, calendar,
 * absences and line-ups - is folded under «Profundizar» and closed until the reader opens it: the page opens on what
 * helps to understand the match. Folded is not deleted: the section is there, named, with its subtitle.
 *
 * Its order (plan Partidos y Match Center, R1): PrediGol Intelligence, the forecast, «Profundizar» and the best prices - four
 * blocks, full width; the analysed markets' cards are no longer drawn there (they are the owner's, in Avanzado).
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import type { MatchCtx } from "./context";
import { readFileSync } from "node:fs";
import { BEFORE_KICKOFF_ORDER, BeforeKickoffLayout, DeepenSection } from "./SummaryTab";

setLocale("es");
afterEach(() => setLocale("es"));

// The closed section reads nothing from the match: its blocks are not drawn until it is opened.
const ctx = {
  fixtureId: "21676",
  match: {
    id: 21676,
    home: { id: 1, name: "Livyi Bereh", logo_url: null },
    away: { id: 2, name: "Zorya Luhansk", logo_url: null },
    competition: { id: 177, name: "Premier League" },
  },
  goTo: () => {},
} as unknown as MatchCtx;

describe("«Profundizar»", () => {
  test("closed on arrival: a 44 px button that says what is inside, and none of it drawn", () => {
    const html = renderToStaticMarkup(<DeepenSection ctx={ctx} />);
    expect(html).toContain('data-testid="match-deepen"');
    expect(html).toContain("Profundizar");
    expect(html).toContain("Forma, tabla, cara a cara, calendario, bajas y alineaciones");
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain("min-h-11");
    expect(html).not.toContain("aria-controls");
    expect(html).not.toContain("Zorya Luhansk");
  });

  test("in English", () => {
    setLocale("en");
    const html = renderToStaticMarkup(<DeepenSection ctx={ctx} />);
    expect(html).toContain("Go deeper");
    expect(html).toContain("Form, table, head to head, calendar, absences and line-ups");
    expect(html).not.toContain("Profundizar");
  });
});

describe("the Resumen before kick-off (plan Partidos y Match Center, R1)", () => {
  const stub = (id: string) => <section data-testid={`stub-${id}`} />;
  const blocks = {
    prices: stub("prices"),
    deepen: stub("deepen"),
    forecast: stub("forecast"),
    intelligence: stub("intelligence"),
  };

  test("four blocks, in this order: Intelligence, the forecast, Profundizar, the best prices", () => {
    expect([...BEFORE_KICKOFF_ORDER]).toEqual(["intelligence", "forecast", "deepen", "prices"]);
    const html = renderToStaticMarkup(<BeforeKickoffLayout blocks={blocks} />);
    const at = BEFORE_KICKOFF_ORDER.map((k) => html.indexOf(`data-testid="stub-${k}"`));
    expect(at.every((i) => i >= 0)).toBe(true);
    expect([...at].sort((a, b) => a - b)).toEqual(at);
  });

  test("full width: no two columns, no narrowed block", () => {
    const html = renderToStaticMarkup(<BeforeKickoffLayout blocks={blocks} />);
    expect(html).not.toContain("grid-cols");
    expect(html).not.toContain("max-w-");
  });

  test("before kick-off it draws Intelligence, never the analysed markets' cards nor a picks block of its own", () => {
    // the source of the phase's layout: the blocks it hands to the layout, and nothing else
    const source = readFileSync(new URL("./SummaryTab.tsx", import.meta.url), "utf8");
    const before = source.slice(
      source.indexOf("function BeforeKickoff("),
      source.indexOf("function InPlay("),
    );
    expect(before).toContain("<IntelligenceBlock ctx={ctx} />");
    expect(before).toContain("<ForecastBlock ctx={ctx} />");
    expect(before).toContain("<DeepenSection ctx={ctx} />");
    expect(before).toContain("<QuickPricesBlock ctx={ctx} />");
    expect(before).not.toContain("AnalysisBlock");
    expect(before).not.toContain("PicksTab");
    expect(before).not.toContain("ReadingHighlights");
  });
});
