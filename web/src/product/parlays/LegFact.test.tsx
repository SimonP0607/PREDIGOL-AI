/// <reference types="bun" />
/**
 * The line of why under a leg of a recorded parlay (plan de Inicio, 2.4b): a fact of the match's reading in the reading's own
 * words, nothing for a leg without one or with a fact this page cannot word.
 */
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import type { ReadingFact } from "@/lib/api/v1/types_reading";
import type { ParlayRecordLeg } from "@/lib/api/v1/types_records";
import { LegFact } from "./LegFact";
import { viewOfRecord } from "./legs";

setLocale("es");
const text = (html: string) =>
  html
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();

const streak: ReadingFact = {
  code: "streak_unbeaten",
  params: { side: "home", team: "Nacional", n: 6 },
  ref: "packet:dossier.teams.home",
};

function leg(why: ReadingFact | null | undefined): ParlayRecordLeg {
  return {
    leg_no: 1,
    pick_id: 9,
    match: {
      fixture_id: 5,
      kickoff_at: "2026-11-07T20:00:00Z",
      status_group: "scheduled",
      competition: {
        id: 1,
        name: "Liga BetPlay",
        country: "Colombia",
        logo_url: null,
        flag_url: null,
      },
      home: { id: 1, name: "Nacional", logo_url: null },
      away: { id: 2, name: "Millonarios", logo_url: null },
      score_home: null,
      score_away: null,
    },
    market_key: "1X2",
    selection: "Home",
    line: "0",
    odds: "2.30",
    bookmaker: null,
    p_model: "0.5",
    p_low: "0.45",
    p_market: "0.43",
    ev: "0.1",
    status: "PENDING",
    ...(why === undefined ? {} : { why }),
  } as unknown as ParlayRecordLeg;
}

describe("LegFact", () => {
  test("the fact of the reading, in the reading's words", () => {
    const html = renderToStaticMarkup(<LegFact fact={streak} />);
    expect(text(html)).toBe("Nacional suma 6 partidos sin perder.");
    expect(html).toContain('data-testid="leg-fact"');
  });

  test("no fact, or one this page cannot word: no line", () => {
    expect(renderToStaticMarkup(<LegFact fact={null} />)).toBe("");
    expect(renderToStaticMarkup(<LegFact fact={undefined} />)).toBe("");
    expect(
      renderToStaticMarkup(
        <LegFact fact={{ code: "no_such_code", params: {}, ref: "packet:x" }} />,
      ),
    ).toBe("");
  });

  test("a recorded leg's view carries it; an API from before 2.4b has none", () => {
    expect(viewOfRecord(leg(streak)).fact).toEqual(streak);
    expect(viewOfRecord(leg(null)).fact).toBeNull();
    expect(viewOfRecord(leg(undefined)).fact).toBeNull();
  });
});
