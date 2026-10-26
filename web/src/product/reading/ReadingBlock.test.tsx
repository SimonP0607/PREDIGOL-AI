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
