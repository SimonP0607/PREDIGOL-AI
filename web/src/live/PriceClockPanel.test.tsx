/// <reference types="bun" />
/**
 * PLAN F1, the price clock in the Admin Console: what it says when the structuring is under way, when a count could not be
 * made in time (a dash, never a zero), when nothing failed (no empty "failures" block) and in both languages.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { hasKey, setLocale } from "@/lib/i18n";
import { localInt } from "@/lib/i18n/format";
import type { IntelPriceClock } from "@/lib/api/v1/types_intel";
import { PriceClockBody } from "./PriceClockPanel";

const text = (html: string) => html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");

function render(d: IntelPriceClock): string {
  return text(renderToStaticMarkup(<PriceClockBody d={d} />));
}

function clock(over: Partial<IntelPriceClock> = {}): IntelPriceClock {
  return {
    extractor: "qx-1/tax-v1",
    raw: { payloads: 48210, first: "2026-09-25T04:10:00Z", last: "2026-10-22T10:00:00Z" },
    backlog: 1200,
    ledger: [
      {
        status: "ok",
        version: "qx-1/tax-v1",
        payloads: 47000,
        quotes: 31_500_000,
        refused: 85,
        last: "2026-10-22T09:50:00Z",
      },
      {
        status: "no_fixture",
        version: "qx-1/tax-v1",
        payloads: 12,
        quotes: 0,
        refused: 0,
        last: "2026-10-22T09:50:00Z",
      },
    ],
    quotes: {
      first: "2026-09-25T04:10:00Z",
      last: "2026-10-22T09:50:00Z",
      fixtures: 1480,
      quotes: 31_500_000,
      gigabytes: 3.482,
    },
    families: [
      { key: "result", label: "Result", bets: 14, extracted: 9, quotes: 9_000_000 },
      { key: "corners", label: "Corners", bets: 20, extracted: 11, quotes: 4_000_000 },
      {
        key: "brand_new",
        label: "A family the interface has no name for",
        bets: 2,
        extracted: 0,
        quotes: 0,
      },
    ],
    bets: [
      {
        bet_id: 1,
        name: "Match Winner",
        family: "result",
        period: "FT",
        subject: "match",
        status: "ACTIVE",
        schema: "legacy",
        quotes: 4_000_000,
        last: "2026-10-22T09:50:00Z",
      },
      {
        bet_id: 45,
        name: "Corners Over Under",
        family: "corners",
        period: "FT",
        subject: "match",
        status: "RESEARCH",
        schema: "ou",
        quotes: 2_000_000,
        last: "2026-10-22T09:50:00Z",
      },
    ],
    unclassified: [],
    issues: [],
    runs: [],
    ...over,
  };
}

afterEach(() => setLocale("es"));

describe("the price clock panel", () => {
  test("says what is structured, what waits and how big it is", () => {
    setLocale("es");
    const out = render(clock());
    expect(out).toContain("Cuerpos RAW de /odds");
    expect(out).toContain(localInt(48210));
    expect(out).toContain("Por leer");
    expect(out).toContain(localInt(1200));
    expect(out).toContain("Cuotas");
    expect(out).toContain(localInt(31_500_000));
    expect(out).toContain("3,48 GB");
    expect(out).toContain("qx-1/tax-v1");
    expect(out).toContain("Match Winner");
    expect(out).toContain("Corners Over Under");
  });

  test("states plainly that it only reads and decides nothing", () => {
    setLocale("es");
    expect(render(clock())).toContain("Es solo lectura");
    setLocale("en");
    expect(render(clock())).toContain("Reading only");
  });

  test("an empty backlog reads 'up to date', not zero", () => {
    setLocale("es");
    expect(render(clock({ backlog: 0 }))).toContain("Al día");
    setLocale("en");
    expect(render(clock({ backlog: 0 }))).toContain("Up to date");
  });

  test("a count the server could not make in time is a dash and says so, never a zero", () => {
    setLocale("es");
    const late = clock({
      families: [{ key: "result", label: "Result", bets: 14, extracted: 9, quotes: null }],
      bets: [
        {
          bet_id: 1,
          name: "Match Winner",
          family: "result",
          period: "FT",
          subject: "match",
          status: "ACTIVE",
          schema: "legacy",
          quotes: null,
          last: null,
        },
      ],
    });
    const out = render(late);
    expect(out).toContain("tardó más de lo permitido");
    const row = out.slice(out.indexOf("Match Winner"));
    expect(row.startsWith("Match Winner Resultado Partido Partido legacy")).toBe(true);
    expect(row.split("Activo")[1]?.trim().startsWith("—")).toBe(true);
  });

  test("a table that was counted does not apologise", () => {
    setLocale("es");
    expect(render(clock())).not.toContain("tardó más de lo permitido");
  });

  test("failures are listed with their reason; with none there is no failures block", () => {
    setLocale("es");
    expect(renderToStaticMarkup(<PriceClockBody d={clock()} />)).not.toContain(
      "intel-price-clock-issues",
    );
    const failing = clock({
      issues: [
        {
          payload: "ab12cd34ef56",
          provider_fixture_id: 1234567,
          status: "error",
          detail: "the file is not there",
          quotes_refused: 0,
          extracted_at: "2026-10-22T09:40:00Z",
        },
        {
          payload: "0f9e8d7c6b5a",
          provider_fixture_id: null,
          status: "ok",
          detail: "8 values refused",
          quotes_refused: 8,
          extracted_at: "2026-10-22T09:30:00Z",
        },
      ],
    });
    const html = renderToStaticMarkup(<PriceClockBody d={failing} />);
    expect(html).toContain("intel-price-clock-issues");
    const out = text(html);
    expect(out).toContain("ab12cd34ef56");
    expect(out).toContain("Falló");
    expect(out).toContain("the file is not there");
    expect(out).toContain("8 values refused");
  });

  test("a bet the taxonomy does not know yet is named, and says nothing is lost", () => {
    setLocale("es");
    const out = render(
      clock({
        unclassified: [
          { bet_id: 901, name: "Brand new bet", classified_at: "2026-10-22T00:00:00Z" },
        ],
      }),
    );
    expect(out).toContain("Mercados nuevos sin clasificar");
    expect(out).toContain("901");
    expect(out).toContain("Brand new bet");
    expect(out).toContain("siguen en RAW");
  });

  test("before anything is structured it says the job runs on its own", () => {
    setLocale("es");
    const out = render(
      clock({
        ledger: [],
        backlog: 48210,
        quotes: { gigabytes: 0, quotes: 0, fixtures: 0 },
        bets: [],
      }),
    );
    expect(out).toContain("Todavía no se ha estructurado ningún cuerpo");
  });

  test("a family the interface has no name for falls back to the provider's label", () => {
    setLocale("es");
    expect(render(clock())).toContain("A family the interface has no name for");
  });

  test("English reads in English", () => {
    setLocale("en");
    const out = render(clock());
    expect(out).toContain("Raw /odds bodies");
    expect(out).toContain("To read");
    expect(out).toContain("Market families");
    expect(out).toContain("Corners");
    expect(out).not.toContain("Cuerpos");
  });
});

describe("the closed vocabularies the server sends are all named in both languages", () => {
  const STATUS = ["ok", "empty", "no_fixture", "after_kickoff", "error"];
  const PERIODS = ["FT", "1H", "2H", "INTERVAL", "OTHER"];
  const SUBJECTS = ["match", "home", "away", "player", "keeper"];
  const FAMILIES = [
    "result",
    "goals",
    "goals_half",
    "corners",
    "cards",
    "shots",
    "fouls",
    "offsides",
    "tackles",
    "saves",
    "timing",
    "special",
    "advance",
    "players",
    "other_sport",
    "unclassified",
  ];
  const keys = [
    ...STATUS.map((k) => `intel.markets.clock.status.${k}`),
    ...PERIODS.map((k) => `intel.markets.clock.periodName.${k}`),
    ...SUBJECTS.map((k) => `intel.markets.clock.subjectName.${k}`),
    ...FAMILIES.map((k) => `intel.markets.clock.familyName.${k}`),
  ];

  test.each(["es", "en"] as const)("%s names every status, period, subject and family", (lang) => {
    const missing = keys.filter((k) => !hasKey(k, lang));
    expect(missing).toEqual([]);
  });
});
