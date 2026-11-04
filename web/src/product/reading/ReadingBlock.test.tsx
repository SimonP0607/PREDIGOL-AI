/// <reference types="bun" />
/**
 * ANÁLISIS PREDIGOL (plan UX, A9): the structured reading with every state shown - a skeleton while it loads, the error with
 * its retry, the owner having turned it off (said), a partial reading without the match's context - and the conclusion's
 * caveat. The Resumen's highlights: the summary and the two main risks, with the way to the whole analysis.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import type { Envelope } from "@/lib/api/v1/types";
import type { MatchReading } from "@/lib/api/v1/types_reading";
import { ReadingHighlightsView, ReadingView } from "./ReadingBlock";
import type { ReadingLoad } from "./useReading";

setLocale("es");
afterEach(() => setLocale("es"));

function envelope(
  data: MatchReading | null,
  status: Envelope<null>["status"] = "ok",
): Envelope<MatchReading | null> {
  return {
    status,
    data,
    reason: status === "ok" ? null : "off",
    meta: { generated_at: "2026-10-25T12:00:00Z", api_version: "v1" },
  } as Envelope<MatchReading | null>;
}

const READING: MatchReading = {
  fixture_id: 7,
  version: "reading-v1",
  complete: true,
  data_at: "2026-10-25T10:30:00Z",
  forecast_at: "2026-10-25T09:00:00Z",
  sections: [
    {
      key: "summary",
      facts: [
        { code: "match_intro", params: { competition: "Liga BetPlay" }, ref: "packet:fixture" },
        {
          code: "expected_result",
          params: { outcome: "home", team: "Nacional", probability: 0.48, calibrated: false },
          ref: "forecast:1X2",
        },
      ],
    },
    { key: "market", facts: [{ code: "market_unpriced", params: {}, ref: "packet:market" }] },
    {
      key: "risks",
      facts: [
        { code: "lineups_unconfirmed", params: {}, ref: "packet:lineups" },
        { code: "rumours", params: { count: 2 }, ref: "packet:evidence" },
        { code: "no_external_info", params: {}, ref: "packet:evidence" },
        { code: "a_code_from_the_future", params: {}, ref: "packet:x" },
      ],
    },
    {
      key: "conclusion",
      facts: [
        {
          code: "likely",
          params: {
            market: "1X2",
            outcome: "home",
            team: "Nacional",
            probability: 0.48,
            calibrated: false,
          },
          ref: "forecast:1X2",
        },
      ],
    },
  ],
};

const ok = (data: MatchReading = READING): ReadingLoad => ({
  status: "success",
  envelope: envelope(data),
});

describe("the reading's states", () => {
  test("loading: a skeleton, never a blank", () => {
    const html = renderToStaticMarkup(<ReadingView load={{ status: "pending" }} />);
    expect(html).toContain('aria-busy="true"');
    expect(html).toContain("Análisis PrediGol");
  });

  test("an error: said, with its retry", () => {
    const html = renderToStaticMarkup(
      <ReadingView load={{ status: "error", error: new Error("boom"), retry: () => undefined }} />,
    );
    expect(html).toContain('role="alert"');
  });

  test("the owner turned it off: said, not hidden", () => {
    const html = renderToStaticMarkup(
      <ReadingView load={{ status: "success", envelope: envelope(null, "not_available") }} />,
    );
    expect(html).toContain('data-testid="reading-unavailable"');
    expect(html).toContain("La lectura de este partido no está disponible.");
  });

  test("the sections in order with their sentences, the data's time, the caveat - and an unknown code left out", () => {
    const html = renderToStaticMarkup(<ReadingView load={ok()} />);
    expect(html).toContain("Lectura automática con los datos de PrediGol");
    expect(html).toContain('data-testid="reading-data-at"');
    const order = ["summary", "market", "risks", "conclusion"].map((k) =>
      html.indexOf(`data-testid="reading-section-${k}"`),
    );
    expect(order.every((i) => i >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    expect(html).toContain("Hay 2 rumores sin confirmar: no cuentan como hechos.");
    expect(html).not.toContain("a_code_from_the_future");
    expect(html).toContain('data-testid="reading-caveat"');
    expect(html).not.toContain("La probabilidad implícita es la cuota sin el margen"); // the market had no price
    expect(html).not.toContain('data-testid="reading-partial"');
  });

  test("a match without its context: a partial reading that says so", () => {
    const html = renderToStaticMarkup(
      <ReadingView load={ok({ ...READING, complete: false, data_at: null })} />,
    );
    expect(html).toContain('data-testid="reading-partial"');
  });
});

const NARRATIVE: MatchReading["narrative"] = {
  version: "user-narrative-v1",
  written_at: "2026-10-25T10:40:00Z",
  data_at: "2026-10-25T10:30:00Z",
  es: [
    {
      key: "summary",
      sentences: [{ text: "Partido de la Liga BetPlay en Medellín.", refs: ["P:fixture"] }],
    },
    {
      key: "risks",
      sentences: [{ text: "Las alineaciones aún no están confirmadas.", refs: ["P:lineups"] }],
    },
    {
      key: "conclusion",
      sentences: [
        {
          text: "Lo más probable según PrediGol es la victoria de Nacional (48 %, sin calibrar).",
          refs: ["P:forecast.1X2"],
        },
      ],
    },
  ],
  en: [
    {
      key: "summary",
      sentences: [{ text: "A Liga BetPlay match in Medellín.", refs: ["P:fixture"] }],
    },
    {
      key: "risks",
      sentences: [{ text: "The line-ups are not confirmed yet.", refs: ["P:lineups"] }],
    },
    {
      key: "conclusion",
      sentences: [
        {
          text: "PrediGol's most likely outcome is a Nacional win (48 %, uncalibrated).",
          refs: ["P:forecast.1X2"],
        },
      ],
    },
  ],
};

describe("the narrative (A11)", () => {
  test("shown instead of the facts, labelled as written with AI and checked, with the time of its data", () => {
    const html = renderToStaticMarkup(
      <ReadingView load={ok({ ...READING, narrative: NARRATIVE })} />,
    );
    expect(html).toContain('data-testid="reading-narrative"');
    expect(html).toContain("Redactado con IA y validado contra los datos de PrediGol");
    expect(html).not.toContain("Lectura automática con los datos de PrediGol");
    expect(html).toContain("Escrito con datos de");
    expect(html).toContain(
      "Lo más probable según PrediGol es la victoria de Nacional (48 %, sin calibrar).",
    );
    expect(html).not.toContain('data-testid="reading-fact"');
    expect(html).toContain('data-refs="P:forecast.1X2"');
    expect(html).toContain('data-testid="reading-caveat"');
  });

  test("the conclusion first, never folded; the other sections fold, the summary open on a phone", () => {
    const html = renderToStaticMarkup(
      <ReadingView load={ok({ ...READING, narrative: NARRATIVE })} />,
    );
    const conclusion = html.indexOf('data-testid="narrative-section-conclusion"');
    const summary = html.indexOf('data-testid="narrative-section-summary"');
    const risks = html.indexOf('data-testid="narrative-section-risks"');
    expect(conclusion).toBeGreaterThan(-1);
    expect(conclusion).toBeLessThan(summary);
    expect(summary).toBeLessThan(risks);
    expect(html).toMatch(/<details open=""[^>]*data-testid="narrative-section-summary"/);
    expect(html).toMatch(/<details[^>]*data-testid="narrative-section-risks"/);
    expect(html).not.toMatch(/<details open=""[^>]*data-testid="narrative-section-risks"/);
    expect(html).not.toMatch(/<details[^>]*data-testid="narrative-section-conclusion"/);
  });

  test("in the page's language", () => {
    setLocale("en");
    const html = renderToStaticMarkup(
      <ReadingView load={ok({ ...READING, narrative: NARRATIVE })} />,
    );
    expect(html).toContain("Written with AI and checked against PrediGol&#x27;s data");
    expect(html).toContain(
      "PrediGol&#x27;s most likely outcome is a Nacional win (48 %, uncalibrated).",
    );
    expect(html).not.toContain("sin calibrar");
  });

  test("without a narrative - or with null - the facts, as A9 shows them", () => {
    for (const reading of [{ ...READING, narrative: null }, READING]) {
      const html = renderToStaticMarkup(<ReadingView load={ok(reading)} />);
      expect(html).not.toContain('data-testid="reading-narrative"');
      expect(html).toContain("Lectura automática con los datos de PrediGol");
      expect(html).toContain('data-testid="reading-fact"');
    }
  });
});

describe("once the match is over (plan UX, B4)", () => {
  test("the reading and its highlights end with the way to the Postpartido - and only then", () => {
    const to = 'data-testid="reading-to-postmatch"';
    expect(
      renderToStaticMarkup(<ReadingView load={ok()} afterMatch={() => undefined} />),
    ).toContain(to);
    expect(renderToStaticMarkup(<ReadingView load={ok()} />)).not.toContain(to);
    const highlights = renderToStaticMarkup(
      <ReadingHighlightsView load={ok()} onMore={() => undefined} afterMatch={() => undefined} />,
    );
    expect(highlights).toContain(to);
    expect(highlights).toContain("Qué pasó en el partido: ver el Postpartido");
    expect(
      renderToStaticMarkup(<ReadingHighlightsView load={ok()} onMore={() => undefined} />),
    ).not.toContain(to);
  });
});

describe("the Resumen's highlights", () => {
  test("the summary and the two main risks, with the way to the whole analysis", () => {
    const html = renderToStaticMarkup(
      <ReadingHighlightsView load={ok()} onMore={() => undefined} />,
    );
    expect(html).toContain("Partido de Liga BetPlay.");
    expect(html).toContain("Las alineaciones aún no están confirmadas.");
    expect(html).toContain("Hay 2 rumores sin confirmar");
    expect(html).not.toContain("No encontramos información externa"); // only the first two
    expect(html).toContain('data-testid="reading-see-all"');
  });

  test("nothing while the owner has turned the reading off; a skeleton while it loads", () => {
    expect(
      renderToStaticMarkup(
        <ReadingHighlightsView
          load={{ status: "success", envelope: envelope(null, "not_available") }}
          onMore={() => undefined}
        />,
      ),
    ).toBe("");
    expect(
      renderToStaticMarkup(
        <ReadingHighlightsView load={{ status: "pending" }} onMore={() => undefined} />,
      ),
    ).toContain('aria-busy="true"');
  });
});
