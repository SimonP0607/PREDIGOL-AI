/// <reference types="bun" />
/**
 * A day without picks, told honestly (plan UX, A9; section 24): the exact sentence of the plan, the reason in the reader's
 * words - its own sentence, else its stage's, else nothing (never a raw code) -, «todavía estamos revisando» with no hour,
 * a failure that never reads as a reason, and none of the words the plan keeps out of an empty day («valor», certainty).
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import esRecords from "@/locales/es/records.json";
import enRecords from "@/locales/en/records.json";
import esHome from "@/locales/es/home.json";
import enHome from "@/locales/en/home.json";
import type { NoPick } from "@/lib/api/v1/types_today";
import { noPickView, reasonText } from "./noPick";
import { NoPickState } from "./NoPickState";

setLocale("es");
afterEach(() => setLocale("es"));

const day = (over: Partial<NoPick>): NoPick => ({
  day: "2026-10-24",
  state: "none",
  stage: null,
  reason: null,
  matches: 12,
  ...over,
});

function text(html: string): string {
  return html
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/\s+/g, " ")
    .trim();
}

function strings(node: unknown): string[] {
  if (typeof node === "string") return [node];
  if (node && typeof node === "object") return Object.values(node).flatMap(strings);
  return [];
}

describe("the reason in the reader's words", () => {
  test("the plan's own example, for a day no market beat", () => {
    expect(reasonText({ stage: "value", reason: "non_positive_ev" })).toBe(
      "Ningún mercado mostró ventaja frente al precio del mercado.",
    );
    setLocale("en");
    expect(reasonText({ stage: "value", reason: "non_positive_ev" })).toBe(
      "No market showed an edge over the market price.",
    );
  });

  test("a reason this page has no sentence for falls back on its stage, then on nothing", () => {
    expect(reasonText({ stage: "risk", reason: "a_reason_from_the_future" })).toBe(
      "Las selecciones pagaban cuotas por encima de nuestro límite de riesgo.",
    );
    expect(reasonText({ stage: "a_stage_from_the_future", reason: "nor_this" })).toBeNull();
    expect(reasonText({ stage: "selection", reason: "day_full" })).toBeNull();
    expect(reasonText({ stage: null, reason: null })).toBeNull();
  });

  test("the states: published, being read, no matches, none with its reason", () => {
    expect(noPickView(null)).toEqual({ kind: "generic" });
    expect(noPickView(day({ state: "picks" }))).toEqual({ kind: "generic" });
    expect(noPickView(day({ state: "reviewing" }))).toEqual({ kind: "reviewing" });
    expect(noPickView(day({ reason: "no_matches", matches: 0 }))).toEqual({ kind: "no_matches" });
    expect(noPickView(day({ reason: "no_qualified_candidates" }))).toEqual({
      kind: "none",
      why: "Ninguno de los modelos con los que PrediGol publica tenía selecciones para los partidos de hoy.",
    });
  });
});

describe("what the page says", () => {
  test("none: the plan's sentence, word for word, and the reason under it", () => {
    const html = renderToStaticMarkup(
      <NoPickState
        load={{ status: "ok", value: day({ stage: "value", reason: "non_positive_ev" }) }}
      />,
    );
    expect(text(html)).toContain(
      "Hoy ningún partido cumplió las condiciones para publicar un pick. Preferimos no publicar a publicar por publicar.",
    );
    expect(text(html)).toContain(
      "Motivo: Ningún mercado mostró ventaja frente al precio del mercado.",
    );
    expect(html).toContain('data-state="none"');
    expect(html).toContain('data-reason="non_positive_ev"');
  });

  test("a decided empty day carries what the caller adds (the way to «Cómo le va a PrediGol», A12); a day being read does not", () => {
    const more = <a data-testid="more-link">más</a>;
    for (const value of [
      day({ stage: "value", reason: "non_positive_ev" }),
      day({ reason: "no_matches", matches: 0 }),
    ])
      expect(
        renderToStaticMarkup(<NoPickState load={{ status: "ok", value }} more={more} />),
      ).toContain('data-testid="more-link"');
    expect(
      renderToStaticMarkup(
        <NoPickState load={{ status: "ok", value: day({ state: "reviewing" }) }} more={more} />,
      ),
    ).not.toContain('data-testid="more-link"');
  });

  test("the set not chosen yet: «todavía estamos revisando», and no hour is promised", () => {
    const html = text(
      renderToStaticMarkup(
        <NoPickState load={{ status: "ok", value: day({ state: "reviewing" }) }} />,
      ),
    );
    expect(html).toContain("Todavía estamos revisando los partidos de hoy");
    expect(html).not.toMatch(/\d{1,2}[:.]\d{2}|\d+ ?h\b/);
  });

  test("a failure to load the reason is said, with a retry - never as a reason", () => {
    const html = text(
      renderToStaticMarkup(
        <NoPickState load={{ status: "error", error: new Error("x"), retry: () => {} }} />,
      ),
    );
    expect(html).toContain("No pudimos cargar el motivo.");
    expect(html).toContain("Reintentar");
    expect(html).not.toContain("Preferimos no publicar");
  });
});

describe("what an empty day never says (plan section 24)", () => {
  const VETOED_ES = /\b(valor|seguro|segura|fijo|fija|garantizad[oa]s?|apuesta)\b/i;
  const VETOED_EN = /\b(value|sure|guaranteed|lock|bet)\b/i;
  test("no «valor» and no certainty in Spanish", () => {
    for (const s of strings({ noPick: esRecords.noPick, home: esHome })) {
      expect(s).not.toMatch(VETOED_ES);
    }
  });
  test("no «value» and no certainty in English", () => {
    for (const s of strings({ noPick: enRecords.noPick, home: enHome })) {
      expect(s).not.toMatch(VETOED_EN);
    }
  });
});
