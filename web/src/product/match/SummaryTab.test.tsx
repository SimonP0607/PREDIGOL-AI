/// <reference types="bun" />
/**
 * The Resumen before kick-off (plan de cierre UX, 2.2): what is read to go deeper - form, table, head to head, calendar,
 * absences and line-ups - is folded under «Profundizar» and closed until the reader opens it: the page opens on what
 * helps to understand the match. Folded is not deleted: the section is there, named, with its subtitle.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import type { MatchCtx } from "./context";
import { DeepenSection } from "./SummaryTab";

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
