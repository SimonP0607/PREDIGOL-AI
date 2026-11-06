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
  PublishedPick,
  Transparency,
  TransparencyParlayTally,
  TransparencyPeriodTally,
  TransparencyTally,
} from "@/lib/api/v1/types_transparency";
import { PickListView } from "./PickList";
import { TransparencyBody } from "./TransparencyPage";
import { changesOf, dayText, reasonsOf, resultTone, sampleNote, scoreText, topStop } from "./model";

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

function parlay(
  kind: TransparencyParlayTally["kind"],
  over: Partial<TransparencyTally> = {},
  partial = 0,
): TransparencyParlayTally {
  return { ...ZERO, ...over, kind, partial };
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
  parlays: [parlay("daily"), parlay("multiday")],
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
  parlays: [
    parlay("daily", { published: 4, pending: 1, won: 2, lost: 1, settled: 3 }, 1),
    parlay("multiday", { published: 1, void: 1 }),
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
      "parlays",
      "days",
      "markets",
      "line-value",
      "forecast",
      "evaluation",
      "how",
      "what-is-a-pick",
      "how-to-read",
      "definitions",
      "changes",
    ])
      expect(html).toContain(`data-testid="transparency-${block}"`);
    expect(html).toContain('data-testid="transparency-zero"');
    expect(shown).toContain("Hasta hoy no hemos publicado ningún pick");
    expect(shown).toContain("Preferimos no publicar a publicar por publicar");
    expect(text(html.slice(html.indexOf('data-testid="transparency-zero-days"')))).toContain(
      "22 de 22 días sin picks, del 4 oct 2026 al 25 oct 2026. El motivo más común: Ningún modelo había superado todavía",
    );
    expect(html).toContain('data-testid="transparency-zero-forecast"');
    expect(html).toContain('href="#transparency-days"');
    expect(html).toContain('href="#transparency-forecast"');
    expect(shown).toContain("Todavía no hemos creado ningún parlay de este tipo.");
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

  test("with a history there is no «nothing published» notice, and the parlays are counted", async () => {
    setLocale("es");
    const html = await render(<TransparencyBody data={HISTORY} />);
    const shown = text(html);
    expect(html).not.toContain('data-testid="transparency-zero"');
    expect(shown).not.toContain("Hasta hoy no hemos publicado ningún pick");
    const daily = text(html.slice(html.indexOf('data-testid="transparency-parlay-daily"')));
    expect(daily).toContain("Parlay del día");
    expect(daily).toContain("4 parlays creados · 3 liquidados");
    expect(daily).toContain("Con 3 parlays liquidados todavía no mostramos rentabilidad");
    expect(daily).toContain("1 ganado con alguna selección anulada, devuelta o a medias.");
    const multiday = text(html.slice(html.indexOf('data-testid="transparency-parlay-multiday"')));
    expect(multiday).toContain("1 parlay creado · 0 liquidados");
    expect(multiday).toContain("Anulados 1");
    expect(html).not.toContain("transparency-parlay-tally-daily-roi");
  });

  test("the words that explain: what a pick is, how to read probabilities and odds, what has changed", async () => {
    setLocale("es");
    const shown = text(await render(<TransparencyBody data={HISTORY} />));
    expect(shown).toContain("Qué es un pick");
    expect(shown).toContain("la cuota paga más de lo que dice la probabilidad");
    expect(shown).toContain("se queda como se publicó");
    expect(shown).toContain("PrediGol no recibe dinero de apuestas");
    expect(shown).toContain("Cómo leer probabilidades y cuotas");
    for (const term of ["Cuota", "PrediGol dijo", "Mercado", "Valor", "Unidades", "Resultados"])
      expect(shown).toContain(term);
    expect(shown).toContain(
      "Ejemplo ilustrativo: cuota 2,00, PrediGol dijo 55 %, el mercado 50 %.",
    );
    expect(shown).toContain("Qué ha cambiado");
    expect(shown).toContain("Explícame, la respuesta a tu duda");
    expect(shown).toContain("Valor de línea: versión clv-v1");
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

  test("published picks of qualified models while no kind of bet beat the market out of sample: no «por eso publicamos poco»", async () => {
    setLocale("es");
    const data = { ...TODAY, evaluation: { ...TODAY.evaluation, qualified: 25 } };
    const shown = text(await render(<TransparencyBody data={data} />));
    expect(shown).not.toContain("por eso hoy publicamos poco");
    expect(shown).toContain("del 4 oct 2026 al 25 oct 2026: 25.");
  });

  test("in English, the same page and the same guards", async () => {
    setLocale("en");
    const shown = text(await render(<TransparencyBody data={HISTORY} />));
    expect(shown).toContain("How a pick is decided");
    expect(shown).toContain("+2.4% ± 18 points");
    expect(shown).toContain("With 6 settled picks we do not show a return yet");
    expect(shown).toContain("What a pick is");
    expect(shown).toContain("How to read probabilities and odds");
    expect(shown).toContain("Illustrative example: odds 2.00, PrediGol said 55%, the market 50%.");
    expect(shown).toContain("Daily parlay");
    expect(shown).toContain("4 parlays created · 3 settled");
    expect(shown).toContain("What has changed");
    expect(shown).toContain("Explain, the answer to your question");
    expect(shown).not.toMatch(/transparency\.|support\.updates/);
    expect(shown).not.toMatch(NEVER.en);
    const empty = text(await render(<TransparencyBody data={TODAY} />));
    expect(empty).toContain("So far we have not published a single pick");
    expect(empty).not.toMatch(/transparency\./);
    setLocale("es");
  });
});

const PICK: PublishedPick = {
  day: "2026-11-05",
  kickoff_at: "2026-11-05T20:00:00Z",
  published_at: "2026-11-05T14:00:00Z",
  competition: "Liga Ejemplo",
  country: "Colombia",
  home: "Equipo A",
  away: "Equipo B",
  market: "OU",
  selection: "Over",
  line: "2.50",
  odds: "2.000",
  p_model: "0.550000",
  p_market: "0.500000",
  result: "WIN",
  units: "1.0000",
  score_home: 2,
  score_away: 1,
};

describe("the published picks one by one", () => {
  const noop = () => undefined;

  test("each pick with its price, the probability said, the market's and how it ended", async () => {
    setLocale("es");
    setTimeZone("America/Bogota");
    const items: PublishedPick[] = [
      PICK,
      {
        ...PICK,
        home: "Equipo C",
        away: "Equipo D",
        market: "1X2",
        selection: "Home",
        line: "0.00",
        odds: "3.000",
        result: "LOSS",
        units: "-1.0000",
        score_home: 0,
        score_away: 1,
      },
      {
        ...PICK,
        home: "Equipo E",
        away: "Equipo F",
        result: "PENDING",
        units: null,
        score_home: null,
        score_away: null,
      },
    ];
    const html = await render(
      <PickListView items={items} total={36} hasMore loadingMore={false} onMore={noop} />,
    );
    const shown = text(html);
    expect(html.match(/data-testid="published-pick"/g)).toHaveLength(3);
    expect(html).toContain('data-result="WIN"');
    expect(html).toContain('data-result="LOSS"');
    expect(html).toContain('data-result="PENDING"');
    expect(shown).toContain("Equipo A – Equipo B");
    expect(shown).toContain("Liga Ejemplo");
    expect(shown).toContain("Más de 2,5 goles");
    expect(shown).toContain("Gana Equipo C");
    expect(shown).toContain("Ganado");
    expect(shown).toContain("Perdido");
    expect(shown).toContain("Pendiente");
    expect(shown).toContain("Cuota 2,00");
    expect(shown).toContain("PrediGol dijo 55 %");
    expect(shown).toContain("Mercado 50 %");
    expect(shown).toContain("+1,00 u");
    expect(shown).toContain("−1,00 u");
    expect(shown).toContain("Marcador 2–1");
    expect(shown).toContain("Mostrando 3 de 36");
    expect(html).toContain('data-testid="transparency-picks-more"');
    expect(html).toContain("min-h-11");
    expect(shown).not.toMatch(/transparency\.|records\.status/);
    expect(shown).not.toMatch(NEVER.es);
  });

  test("the last page has no «ver más», and with nothing published it says so", async () => {
    setLocale("es");
    const last = await render(
      <PickListView items={[PICK]} total={1} hasMore={false} loadingMore={false} onMore={noop} />,
    );
    expect(last).not.toContain('data-testid="transparency-picks-more"');
    expect(text(last)).toContain("Mostrando 1 de 1");
    const none = await render(
      <PickListView items={[]} total={0} hasMore={false} loadingMore={false} onMore={noop} />,
    );
    expect(none).toContain('data-testid="transparency-picks-none"');
    expect(text(none)).toContain("Todavía no hay picks publicados que listar.");
    expect(none).not.toContain('data-testid="published-pick"');
  });

  test("in English", async () => {
    setLocale("en");
    const shown = text(
      await render(
        <PickListView items={[PICK]} total={9} hasMore loadingMore={false} onMore={noop} />,
      ),
    );
    expect(shown).toContain("Pick by pick");
    expect(shown).toContain("Over 2.5 goals");
    expect(shown).toContain("Odds 2.00");
    expect(shown).toContain("PrediGol said 55%");
    expect(shown).toContain("Showing 1 of 9");
    expect(shown).toContain("Show more picks");
    expect(shown).not.toMatch(/transparency\.|records\.status/);
    setLocale("es");
  });

  test("the tone of a result and the score", () => {
    expect(["WIN", "HALF_WIN"].map((r) => resultTone(r as PublishedPick["result"]))).toEqual([
      "positive",
      "positive",
    ]);
    expect(["LOSS", "HALF_LOSS"].map((r) => resultTone(r as PublishedPick["result"]))).toEqual([
      "negative",
      "negative",
    ]);
    expect(
      ["PUSH", "VOID", "PENDING"].map((r) => resultTone(r as PublishedPick["result"])),
    ).toEqual(["neutral", "neutral", "neutral"]);
    expect(scoreText(2, 1)).toBe("2–1");
    expect(scoreText(null, null)).toBeNull();
    expect(scoreText(0, null)).toBeNull();
  });
});

describe("the history of changes", () => {
  test("Novedades and the dated definitions together, the newest first, a Novedad before a definition of its day", () => {
    const out = changesOf(
      [
        { key: "roi", version: "flat-1u", since: "2026-10-04" },
        { key: "line_value", version: "clv-v1", since: "2026-10-27" },
      ],
      [
        { id: "2026-11-04-explicame", key: "explain" },
        { id: "2026-10-27-tu-opinion", key: "feedback" },
      ],
    );
    expect(out.map((c) => `${c.day}:${c.kind}:${c.key}`)).toEqual([
      "2026-11-04:novelty:explain",
      "2026-10-27:novelty:feedback",
      "2026-10-27:definition:line_value",
      "2026-10-04:definition:roi",
    ]);
    const mine = changesOf([{ key: "sample", version: "se-v1", since: "2026-10-26" }]);
    expect(mine.length).toBeGreaterThan(1);
    expect(mine.map((c) => c.day)).toEqual([...mine.map((c) => c.day)].sort().reverse());
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
