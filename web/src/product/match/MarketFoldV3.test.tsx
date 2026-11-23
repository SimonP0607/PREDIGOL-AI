/// <reference types="bun" />
/**
 * AP-P08 (FBI_MARKETS_V3): «Mercados» as a bookmaker lays them out - the families in a fixed order, a market's selections in
 * rows with the bookmaker and the age of the best price, the price chosen the same way as ever (Mi parlay is not touched),
 * one line of what PrediGol says under the market, no «Seguir» on a row - and what the old layout keeps when the switch is off.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setLocale } from "@/lib/i18n";
import type { MarketMarks, SelectionMarks } from "@/lib/api/v1/types_stats";
import type { MarketCatalogMarket } from "@/lib/api/v1/types_market_catalog";
import { catalogView, type MarketView, type MarketsView } from "./marketCatalog";
import { familyViews } from "./marketFamilies";
import { markLine, marksOf } from "./marketMarks";
import { MarketFoldV3, MarksLine } from "./MarketFoldV3";
import { lookupReasonOf, NO_CATALOG_PARLAY, selectionId } from "./catalogParlay";

setLocale("es");
afterEach(() => setLocale("es"));

const SIDES = { home: "Valencia", away: "Real Madrid" };
const AT = new Date(Date.now() - 12 * 60_000).toISOString();

function sel(selection: string, line: string, odds: string, bookmaker = "Bet365") {
  return {
    selection,
    line,
    best_odds: odds,
    bookmaker_id: 1,
    bookmaker,
    captured_at: AT,
    bookmakers: 2,
    books: [{ bookmaker_id: 1, bookmaker, odds, captured_at: AT, bet_id: 45 }],
  };
}

const CORNERS = {
  key: "corners_over_under.FT.match",
  code: "corners_over_under",
  period: "FT",
  subject: "match",
  kind: "over_under",
  has_line: true,
  category: "corners",
  bet_ids: [45],
  provider_name: "Corners Over Under",
  market_key: null,
  bookmakers: 2,
  selections: [
    sel("Over", "8.5", "1.45", "Pinnacle"),
    sel("Under", "8.5", "2.70"),
    sel("Over", "9.5", "1.90", "Pinnacle"),
    sel("Under", "9.5", "1.95"),
    sel("Over", "10.5", "2.50"),
    sel("Under", "10.5", "1.50"),
  ],
} as unknown as MarketCatalogMarket;

const probability = (pct: number, calibration: "calibrada" | "sin_calibrar" = "calibrada") => ({
  value: pct / 100,
  pct,
  interval_pct: { low: pct - 5, high: pct + 5 },
  calibration,
  as_of: AT,
  evaluation: "x",
  evaluation_version: 1,
  origin: "champion",
});

function marks(
  over: Partial<SelectionMarks> & { selection: string; line: number },
): SelectionMarks {
  return {
    best_odds: 1.9,
    bookmaker: "Bet365",
    model: { missing_reason: "sin_datos" } as never,
    implied: { missing_reason: "sin_datos" } as never,
    history: { missing_reason: "sin_datos" } as never,
    parlay: { allowed: false, reason: "market_not_settleable" } as never,
    ...over,
  } as SelectionMarks;
}

const IMPLIED = (pct: number) => ({
  value: pct / 100,
  pct,
  books: 5,
  as_of: AT,
  method: "proporcional_media_casas" as const,
});
const HISTORY = (hits: number, n: number) => ({
  hits,
  n,
  pct: Math.round((100 * hits) / n),
  wilson_low: 30,
  wilson_high: 80,
  window: "u10_contexto" as const,
  rule_key: "r",
});

const CORNERS_MARKS = {
  key: CORNERS.key,
  unit: "CORNERS_OU",
  category: "corners",
  kind: "over_under",
  period: "FT",
  subject: "match",
  state: "evaluable",
  state_reason: "",
  rule_key: "r",
  model_origin: "champion",
  distribution: null,
  selections: [
    marks({
      selection: "Over",
      line: 9.5,
      model: probability(57),
      implied: IMPLIED(51),
      history: HISTORY(7, 20),
    }),
    marks({ selection: "Under", line: 9.5, model: probability(43), implied: IMPLIED(49) }),
    marks({ selection: "Over", line: 8.5, model: probability(70), implied: IMPLIED(66) }),
  ],
} as unknown as MarketMarks;

const view = (): MarketView => catalogView(CORNERS, SIDES);

function client(withMarks: boolean): QueryClient {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  if (withMarks) {
    qc.setQueryData(["v1", "match-market-probs", "7", false], {
      status: "ok",
      reason: null,
      meta: {},
      data: { markets: { items: [CORNERS_MARKS] } },
    });
  }
  return qc;
}

function fold(
  withMarks = false,
  choose = undefined as undefined,
  lookupReason: string | null = null,
) {
  return renderToStaticMarkup(
    <QueryClientProvider client={client(withMarks)}>
      <MarketFoldV3
        view={view()}
        fixtureId="7"
        choose={choose}
        lookupReason={lookupReason}
        defaultOpen
      />
    </QueryClientProvider>,
  );
}

describe("the families", () => {
  test("Populares, Goles, Mitades, Córners, Tarjetas, Tiros and Más, whatever order the catalogue came in", () => {
    const given: MarketsView[] = ["shots", "result", "featured", "cards", "goals", "corners"];
    expect(familyViews(given)).toEqual([
      "featured",
      "goals",
      "corners",
      "cards",
      "shots",
      "result",
    ]);
    expect(familyViews(["goals_half", "featured"])).toEqual(["featured", "goals_half"]);
  });
});

describe("what PrediGol says under a market", () => {
  test("the main line's selection PrediGol rates highest, with the houses and the history", () => {
    const line = markLine(view(), [CORNERS_MARKS], (s, l) => `${s} ${l}`);
    expect(line?.selection).toContain("Over");
    expect(line).toMatchObject({
      model: 57,
      houses: 51,
      history: { hits: 7, n: 20 },
      preliminary: false,
    });
  });

  test("an uncalibrated model figure is a preliminary estimate", () => {
    const m = {
      ...CORNERS_MARKS,
      selections: [marks({ selection: "Over", line: 9.5, model: probability(57, "sin_calibrar") })],
    } as unknown as MarketMarks;
    expect(markLine(view(), [m], (s) => s)?.preliminary).toBe(true);
  });

  test("a market the model does not cover says what the houses say, and nothing of PrediGol", () => {
    const m = {
      ...CORNERS_MARKS,
      selections: [marks({ selection: "Over", line: 9.5, implied: IMPLIED(51) })],
    } as unknown as MarketMarks;
    const line = markLine(view(), [m], (s) => s);
    expect(line?.model).toBeNull();
    expect(line?.preliminary).toBe(false);
    expect(line?.houses).toBe(51);
  });

  test("with no figure at all, no line; with no marks for the market, none either", () => {
    const empty = {
      ...CORNERS_MARKS,
      selections: [marks({ selection: "Over", line: 9.5 })],
    } as unknown as MarketMarks;
    expect(markLine(view(), [empty], (s) => s)).toBeNull();
    expect(marksOf(view(), [])).toBeNull();
  });

  test("it is said in one line, and «Estimación preliminar» only when it applies", () => {
    const ok = renderToStaticMarkup(
      <MarksLine
        line={{
          selection: "Más de 9,5",
          model: 57,
          preliminary: false,
          houses: 51,
          history: { hits: 7, n: 20 },
        }}
      />,
    );
    expect(ok).toContain("PrediGol 57 %");
    expect(ok).toContain("Casas 51 %");
    expect(ok).toContain("Últimos 20: 7 veces");
    expect(ok).not.toContain("Estimación preliminar");
    const prelim = renderToStaticMarkup(
      <MarksLine
        line={{ selection: "Sí", model: 49, preliminary: true, houses: null, history: null }}
      />,
    );
    expect(prelim).toContain("Estimación preliminar");
    expect(prelim).not.toContain("Casas");
  });
});

describe("the market as rows", () => {
  test("selections in rows with their line, the bookmaker and the age; the main line only, the rest a tap away", () => {
    const html = fold();
    expect(html).toContain('data-testid="market-rows"');
    expect(html).toContain("Más de 9,5");
    expect(html).toContain("Menos de 9,5");
    expect(html).toContain("Pinnacle");
    expect(html).toContain("hace 12 min");
    expect(html).not.toContain("10,5");
    expect(html).toContain("Ver 2 líneas más");
    expect(html).toContain("Comparar casas");
  });

  test("no «Seguir» on the row, and no capture or version text", () => {
    const html = fold();
    expect(html).not.toContain("Seguir");
    expect(html).not.toMatch(/forecast-v|Consenso sin margen|sello/i);
  });

  test("PrediGol's line shows when the marks are there, and only then", () => {
    expect(fold(true)).toContain('data-testid="market-marks"');
    expect(fold(true)).toContain("PrediGol 57 %");
    expect(fold(false)).not.toContain('data-testid="market-marks"');
  });
});

describe("a market only for consulting (AP-P09)", () => {
  test("every price shows, and the page says it is only for consulting, with the server's motive in words", () => {
    const html = fold(false, undefined, "sin_regla");
    expect(html).toContain("1,90");
    expect(html).toContain('data-testid="market-lookup"');
    expect(html).toContain("Solo consulta");
    expect(html).toContain("Sin regla de liquidación");
  });

  test("with no motive known it still says so, in plain words", () => {
    const html = fold();
    expect(html).toContain("Solo consulta");
    expect(html).toContain("Este mercado no entra en Mi parlay.");
  });

  test("the motive is the one the server gives for most of the market's selections", () => {
    const reasons = new Map([
      [selectionId(CORNERS.key, "Over", 9.5), "sin_cobertura"],
      [selectionId(CORNERS.key, "Under", 9.5), "sin_cobertura"],
      [selectionId(CORNERS.key, "Over", 8.5), "sin_regla"],
      [selectionId("other.FT.match", "Over", 1.5), "empezado"],
    ]);
    const cp = { ...NO_CATALOG_PARLAY, reasons };
    expect(lookupReasonOf(view(), cp)).toBe("sin_cobertura");
    expect(lookupReasonOf(view(), NO_CATALOG_PARLAY)).toBeNull();
  });

  test("a market the server takes shows no «solo consulta»", () => {
    const taken = { ...view(), catalogParlay: "stats" as const };
    const html = renderToStaticMarkup(
      <QueryClientProvider client={client(false)}>
        <MarketFoldV3 view={taken} fixtureId="7" defaultOpen />
      </QueryClientProvider>,
    );
    expect(html).not.toContain('data-testid="market-lookup"');
    expect(html).toContain('data-testid="market-settles"');
  });
});
