/// <reference types="bun" />
/**
 * PLAN UX A12, «Cómo le va a PrediGol» rendered: the page as production would show it today (nothing published, every day
 * without picks for want of a qualified model, the forecast calibrated only in total goals), and with a history (units and
 * the return only with their margin, the small sample said, never a conclusion below 100); the seven blocks, the figures
 * with their n, and never a streak, a star pick or a promise.
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
import { setTimeZone } from "@/lib/time";
import type {
  Transparency,
  TransparencyPeriodTally,
  TransparencyTally,
} from "@/lib/api/v1/types_transparency";
import { TransparencyBody } from "./TransparencyPage";
import { dayText, reasonsOf, sampleNote, topStop } from "./model";

const text = (html: string) => html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");

async function render(node: ReactNode): Promise<string> {
  const router = createRouter({
    routeTree: createRootRoute({ component: () => node }),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  await router.load();
  return renderToStaticMarkup(<RouterProvider router={router} />);
}

const ZERO: TransparencyTally = {
  published: 0,
  pending: 0,
  won: 0,
  lost: 0,
  half_won: 0,
  half_lost: 0,
  push: 0,
  void: 0,
  settled: 0,
  units: null,
  roi: null,
  margin: null,
  conclusive: false,
};

function period(p: TransparencyPeriodTally["period"], over: Partial<TransparencyTally> = {}) {
  return {
    ...ZERO,
    ...over,
    period: p,
    since: p === "all" ? null : p === "7d" ? "2026-10-20" : "2026-09-27",
    until: "2026-10-26",
  };
}

/** What production holds on 26 Oct 2026 (the A12 baseline). */
const TODAY: Transparency = {
  timezone: "America/Bogota",
  min_sample: 25,
  conclusive: 100,
  min_calibration: 300,
  min_bin: 30,
  calibration_days: 90,
  periods: [period("7d"), period("30d"), period("all")],
  days: {
    since: "2026-10-04",
    until: "2026-10-25",
    days: 22,
    with_picks: 0,
    without: 22,
    reasons: { no_qualified_candidates: 22 },
    measured: 37000,
    stops: { calibration: 14, market: 8 },
    items: [
      {
        day: "2026-10-25",
        reason: "no_qualified_candidates",
        matches: 199,
        measured: 4912,
        stop: "calibration",
      },
    ],
  },
  markets: [],
  line_value: {
    version: "clv-v1",
    since: "2026-10-22",
    n: 0,
    mean: null,
    positive: null,
    minutes: null,
  },
  forecasts: [
    {
      market: "1X2",
      line: "0.00",
      state: "UNCALIBRATED",
      matches: 585,
      calibrated: 0,
      selection: null,
      bins: [],
      omitted: 0,
    },
    {
      market: "OU",
      line: "2.50",
      state: "CALIBRATED",
      matches: 585,
      calibrated: 569,
      selection: "Over",
      bins: [
        { low: "0.4", high: "0.5", predicted: "0.452", observed: "0.441", n: 220 },
        { low: "0.5", high: "0.6", predicted: "0.548", observed: "0.560", n: 250 },
      ],
      omitted: 99,
    },
    {
      market: "BTTS",
      line: "0.00",
      state: "UNCALIBRATED",
      matches: 585,
      calibrated: 0,
      selection: "Yes",
      bins: [],
      omitted: 0,
    },
  ],
  evaluation: {
    markets: 5,
    pairs: 11,
    passed_markets: 0,
    passed_pairs: 0,
    since: "2026-10-13",
    qualified: 0,
  },
  definitions: [
    { key: "roi", version: "flat-1u", since: "2026-10-04" },
    { key: "line_value", version: "clv-v1", since: "2026-10-22" },
  ],
  data_as_of: null,
};

const HISTORY: Transparency = {
  ...TODAY,
  periods: [
    period("7d", {
      published: 8,
      pending: 1,
      won: 2,
      lost: 1,
      half_won: 1,
      half_lost: 1,
      push: 1,
      void: 1,
      settled: 6,
    }),
    period("30d", {
      published: 33,
      pending: 1,
      won: 15,
      lost: 13,
      settled: 31,
      units: "0.75",
      roi: "0.0242",
      margin: "0.1796",
    }),
    period("all", {
      published: 140,
      won: 70,
      lost: 60,
      settled: 130,
      units: "5.20",
      roi: "0.0400",
      margin: "0.0877",
      conclusive: true,
    }),
  ],
  markets: [
    {
      ...ZERO,
      market: "OU",
      published: 100,
      won: 52,
      lost: 48,
      settled: 100,
      units: "-0.30",
      roi: "-0.0030",
      margin: "0.1000",
      conclusive: true,
    },
    { ...ZERO, market: "other", published: 11, won: 5, lost: 4, settled: 9 },
  ],
  line_value: {
    version: "clv-v1",
    since: "2026-10-22",
    n: 25,
    mean: "0.0260",
    positive: "0.8000",
    minutes: 176,
  },
  evaluation: { ...TODAY.evaluation, passed_markets: 1, passed_pairs: 1, qualified: 4 },
  data_as_of: "2026-10-26T04:00:00Z",
};

const NEVER = {
  es: /racha|estrella|garantiz|seguro que|ganar[áa]s|recupera|apuesta segura/i,
  en: /streak|star pick|guarantee|sure bet|you will win|recover your/i,
};

describe("«Cómo le va a PrediGol»", () => {
  test("today in production: nothing published, every day without picks said why, counts only", async () => {
    setLocale("es");
    setTimeZone("America/Bogota");
    const html = await render(<TransparencyBody data={TODAY} />);
    const shown = text(html);
    for (const block of [
      "published",
      "days",
      "markets",
      "line-value",
      "forecast",
      "evaluation",
      "how",
      "definitions",
    ])
      expect(html).toContain(`data-testid="transparency-${block}"`);
    expect(shown).toContain("Todavía no hemos publicado ningún pick.");
    expect(shown).toContain("22 de 22 días sin picks, del 4 oct 2026 al 25 oct 2026.");
    expect(shown).toContain("Ningún modelo había superado todavía al mercado en su prueba");
    expect(shown).toContain("La parada más común: sin una calibración validada para ese mercado.");
    expect(shown).toContain("Reconstruido con las decisiones guardadas de cada día.");
    expect(shown).toContain("Sin picks publicados todavía.");
    expect(shown).toContain("Todavía no hay picks publicados con su referencia de cierre.");
    expect(shown).toContain("Definición clv-v1, vigente desde el 22 oct 2026.");
    expect(shown).toContain("Sin calibrar");
    expect(html).toContain('data-testid="transparency-bins-OU"');
    expect(html).not.toContain('data-testid="transparency-bins-1X2"');
    expect(shown).toContain(
      "De 5 tipos de apuesta que medimos frente al mercado (11 combinaciones de modelo y mercado), 0",
    );
    expect(shown).toContain("por eso hoy publicamos poco");
    expect(shown).not.toMatch(/transparency\./);
    expect(shown).not.toMatch(NEVER.es);
  });

  test("with a history: units and the return only with their margin, the small sample and no conclusion below 100", async () => {
    setLocale("es");
    const html = await render(<TransparencyBody data={HISTORY} />);
    const shown = text(html);
    expect(html).not.toContain('data-testid="transparency-tally-7d-roi"');
    expect(shown).toContain(
      "Con 6 picks liquidados todavía no mostramos rentabilidad: la muestra es demasiado pequeña",
    );
    expect(shown).toContain("+2,4 % ± 18 puntos");
    expect(shown).toContain(
      "Con menos de 100 picks liquidados la muestra todavía no permite concluir.",
    );
    expect(shown).toContain("+4,0 % ± 9 puntos");
    expect(shown).toContain("Otros");
    expect(shown).toContain("+2,6 %");
    expect(shown).toContain("176 minutos antes del inicio");
    expect(shown).not.toMatch(NEVER.es);
  });

  test("in English, the same page and the same guards", async () => {
    setLocale("en");
    const shown = text(await render(<TransparencyBody data={HISTORY} />));
    expect(shown).toContain("How a pick is decided");
    expect(shown).toContain("+2.4% ± 18 points");
    expect(shown).toContain("With 6 settled picks we do not show a return yet");
    expect(shown).not.toMatch(/transparency\./);
    expect(shown).not.toMatch(NEVER.en);
    setLocale("es");
  });
});

describe("the page's words", () => {
  test("a day is never moved by the reader's time zone", () => {
    setLocale("es");
    setTimeZone("America/Bogota");
    expect(dayText("2026-10-04")).toBe("4 oct 2026");
    setTimeZone("Asia/Tokyo");
    expect(dayText("2026-10-04")).toBe("4 oct 2026");
    setTimeZone("America/Bogota");
  });

  test("the commonest stop: a tie goes to the earlier filter", () => {
    expect(topStop({ market: 3, calibration: 3 })).toBe("market");
    expect(topStop({})).toBeNull();
  });

  test("the reasons, the most telling first", () => {
    expect(
      reasonsOf({
        ...TODAY.days,
        reasons: { no_matches: 2, not_chosen: 1, no_qualified_candidates: 5 },
      }),
    ).toEqual([
      ["no_qualified_candidates", 5],
      ["not_chosen", 1],
      ["no_matches", 2],
    ]);
  });

  test("the sample's note", () => {
    setLocale("es");
    expect(sampleNote(ZERO, 25, 100)).toBe("Todavía no hemos publicado ningún pick.");
    expect(sampleNote({ ...ZERO, published: 3, pending: 3 }, 25, 100)).toBeNull();
    expect(sampleNote({ ...ZERO, published: 1, won: 1, settled: 1 }, 25, 100)).toContain(
      "Con 1 pick liquidado",
    );
    expect(
      sampleNote(
        {
          ...ZERO,
          published: 200,
          settled: 150,
          units: "1",
          roi: "0.0066",
          margin: "0.0816",
          conclusive: true,
        },
        25,
        100,
      ),
    ).toBeNull();
  });
});
