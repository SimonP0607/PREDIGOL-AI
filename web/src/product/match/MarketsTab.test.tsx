/// <reference types="bun" />
/**
 * «Mercados» before kick-off as it renders (plan Partidos y Match Center, F4b: M1-M4): a header with bookmakers and the
 * last update, «Destacados» first and only the categories the catalogue has prices in, one fold per market with the first
 * one open, every price with its bookmaker and age; the five settled markets go to the parlay and the catalogue's others
 * never do; the captures are not on the reader's screen.
 */
import { afterEach, describe, expect, test } from "bun:test";
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { setLocale } from "@/lib/i18n";
import type { MarketQuote } from "@/lib/api/v1/types";
import type {
  MarketCatalog,
  MarketCatalogMarket,
  MarketCatalogSelection,
} from "@/lib/api/v1/types_market_catalog";
import type { MatchMarkets } from "@/lib/api/v1/types_profile";
import type { MatchCtx } from "./context";
import { CapturesStrip } from "./CapturesStrip";
import { CategoryPanel, PrematchMarkets } from "./MarketsTab";

setLocale("es");
afterEach(() => setLocale("es"));

const ID = "7";
const KICKOFF = new Date(Date.now() + 2 * 86_400_000).toISOString();
const AT = new Date(Date.now() - 12 * 60_000).toISOString();

function quote(
  market_key: string,
  selection: string,
  line: string,
  odds: string,
  bookmaker_id = 1,
): MarketQuote {
  return {
    bookmaker_id,
    bookmaker: bookmaker_id === 1 ? "Bet365" : "Pinnacle",
    market_key,
    selection,
    line,
    odds_decimal: odds,
    implied_probability: "0.5",
    captured_at: AT,
    minutes_to_ko: 2880,
    source: "prematch",
    payload_hash: "h",
  };
}

const QUOTES: MarketQuote[] = [
  quote("1X2", "Home", "0", "2.05"),
  quote("1X2", "Draw", "0", "3.40"),
  quote("1X2", "Away", "0", "3.60"),
  quote("1X2", "Home", "0", "2.00", 2),
  quote("OU", "Over", "1.5", "1.30"),
  quote("OU", "Under", "1.5", "3.40"),
  quote("OU", "Over", "2.5", "1.95"),
  quote("OU", "Under", "2.5", "1.90"),
  quote("OU", "Over", "3.5", "3.10"),
  quote("OU", "Under", "3.5", "1.35"),
  quote("BTTS", "Yes", "0", "1.80"),
  quote("BTTS", "No", "0", "2.00"),
  quote("AH", "Home", "-0.5", "2.05"),
  quote("AH", "Away", "0.5", "1.80"),
];

function ctx(phase: MatchCtx["phase"] = "scheduled"): MatchCtx {
  return {
    fixtureId: ID,
    match: {
      id: 7,
      home: { id: 1, name: "Valencia", logo_url: null },
      away: { id: 2, name: "Real Madrid", logo_url: null },
      kickoff_at: KICKOFF,
      status_group: "scheduled",
    },
    markets: { status: "ok", data: QUOTES, reason: null },
    phase,
  } as unknown as MatchCtx;
}

const ALL: MatchMarkets = {
  fixture_id: 7,
  quotes: 397,
  captures: [
    {
      captured_at: AT,
      minutes_to_ko: 4320,
      source: "prematch",
      quotes: 397,
      bookmakers: 2,
      by_market: { "1X2": 120 },
    },
  ],
  selections: [
    {
      market_key: "1X2",
      selection: "Home",
      line: "0",
      books: [
        { bookmaker_id: 1, bookmaker: "Bet365", odds: "2.05", opening_odds: "2.10" },
        { bookmaker_id: 2, bookmaker: "Pinnacle", odds: "2.00", opening_odds: "2.00" },
      ],
    },
  ] as unknown as MatchMarkets["selections"],
};

function sel(
  selection: string,
  line: string,
  odds: Array<[string, string]>,
): MarketCatalogSelection {
  return {
    selection,
    line,
    best_odds: odds[0]![1],
    bookmaker_id: 1,
    bookmaker: odds[0]![0],
    captured_at: AT,
    bookmakers: odds.length,
    books: odds.map(([bookmaker, o], i) => ({
      bookmaker_id: i + 1,
      bookmaker,
      odds: o,
      captured_at: AT,
      bet_id: 45,
    })),
  };
}

const CORNERS: MarketCatalogMarket = {
  key: ["corners_over_under", "FT", "match"].join("."),
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
    sel("Over", "8.5", [
      ["Pinnacle", "1.45"],
      ["Bet365", "1.40"],
    ]),
    sel("Under", "8.5", [["Bet365", "2.70"]]),
    sel("Over", "9.5", [
      ["Pinnacle", "1.90"],
      ["Bet365", "1.85"],
    ]),
    sel("Under", "9.5", [
      ["Bet365", "1.95"],
      ["Pinnacle", "1.88"],
    ]),
    sel("Over", "10.5", [["Bet365", "2.50"]]),
    sel("Under", "10.5", [["Bet365", "1.50"]]),
  ],
};

const CORNERS_1X2: MarketCatalogMarket = {
  ...CORNERS,
  key: ["corners_1x2", "FT", "match"].join("."),
  code: "corners_1x2",
  kind: "one_x_two",
  has_line: false,
  bet_ids: [55],
  selections: [
    sel("Home", "0", [["Bet365", "1.70"]]),
    sel("Draw", "0", [["Bet365", "9.00"]]),
    sel("Away", "0", [["Bet365", "2.20"]]),
  ],
};

const BTTS: MarketCatalogMarket = {
  ...CORNERS,
  key: ["goals_btts", "FT", "match"].join("."),
  code: "goals_btts",
  kind: "both_teams_score",
  has_line: false,
  category: "goals",
  bet_ids: [8],
  market_key: "BTTS",
  selections: [sel("Yes", "0", [["Bet365", "1.80"]]), sel("No", "0", [["Bet365", "2.00"]])],
};

function catalog(over: Partial<MarketCatalog>): MarketCatalog {
  return {
    fixture_id: 7,
    kickoff_at: KICKOFF,
    state: "priced",
    checked_at: AT,
    newer_answer_pending: false,
    partial: false,
    category: null,
    categories: [
      { key: "result", markets: 4, selections: 12, bookmakers: 6 },
      { key: "goals", markets: 4, selections: 20, bookmakers: 5 },
      { key: "corners", markets: 2, selections: 9, bookmakers: 2 },
    ],
    markets: [],
    ...over,
  };
}

function envelope<T>(data: T) {
  return { status: "ok", data, reason: null, meta: {} };
}

function client(base: MarketCatalog | null): QueryClient {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(["v1", "match-markets", ID], envelope(ALL));
  if (base) qc.setQueryData(["v1", "match-market-catalog", ID, "categories"], envelope(base));
  return qc;
}

/** The help line links to the glossary: rendered inside a router. */
async function inRouter(node: ReactNode): Promise<string> {
  const router = createRouter({
    routeTree: createRootRoute({ component: () => node }),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  await router.load();
  return renderToStaticMarkup(<RouterProvider router={router} />);
}

function prematch(qc: QueryClient, phase: MatchCtx["phase"] = "scheduled"): Promise<string> {
  return inRouter(
    <QueryClientProvider client={qc}>
      <PrematchMarkets
        ctx={ctx(phase)}
        order={null}
        first={[]}
        onConsult={() => {}}
        follow={() => null}
      />
    </QueryClientProvider>,
  );
}

function category(qc: QueryClient, key: "corners" | "goals"): string {
  return renderToStaticMarkup(
    <QueryClientProvider client={qc}>
      <CategoryPanel
        ctx={ctx()}
        category={key}
        sides={{ home: "Valencia", away: "Real Madrid" }}
        choose={(p) => ({
          fixture_id: 7,
          market_key: p.market as "BTTS",
          selection: p.selection,
          line: p.line,
          kickoff_at: KICKOFF,
          status_group: "scheduled",
          home: "Valencia",
          away: "Real Madrid",
          odds: p.odds,
          bookmaker: p.bookmaker,
        })}
        onConsult={() => {}}
        follow={() => null}
      />
    </QueryClientProvider>,
  );
}

const between = (html: string, from: string, to: string) =>
  html.slice(html.indexOf(from), html.indexOf(to, html.indexOf(from)));

describe("«Mercados» before kick-off", () => {
  test("a header with bookmakers and the last update, never the captures", async () => {
    const html = await prematch(client(catalog({})));
    expect(html).toContain('data-testid="markets-header"');
    expect(html).toContain("6 casas");
    expect(html).not.toContain("Capturas de cuotas");
    expect(html).not.toContain("captures-strip");
    expect(html).not.toContain("T-72 h");
    expect(html).not.toContain("397");
    expect(html).not.toContain("pasen o no los filtros");
  });

  test("«Destacados» first, then only the categories with prices, in order", async () => {
    const html = await prematch(client(catalog({})));
    const chips = between(html, 'data-testid="markets-categories"', "</div>");
    const order = ["Destacados", "Resultado", "Goles", "Córners"].map((c) =>
      chips.indexOf(`>${c}<`),
    );
    expect(order.every((i) => i >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    for (const absent of ["Mitades", "Tarjetas", "Tiros"]) expect(chips).not.toContain(absent);
    expect(chips).toContain('aria-pressed="true"');
  });

  test("the highlights: 1X2, over/under and both teams score, the first fold open, each price with its age", async () => {
    const html = await prematch(client(catalog({})));
    const grid = html.slice(html.indexOf('data-testid="markets-grid"'));
    const markets = [...grid.matchAll(/data-market="([^"]+)"/g)].map((m) => m[1]);
    expect(markets).toEqual(["1X2", "OU", "BTTS"]);
    const folds = [
      ...grid.matchAll(
        /aria-expanded="(true|false)"[^>]*data-fold-toggle|data-fold-toggle[^>]*aria-expanded="(true|false)"/g,
      ),
    ];
    expect(folds.map((m) => m[1] ?? m[2])).toEqual(["true", "false", "false"]);
    // the open 1X2: its prices go to the parlay, with bookmaker and age
    expect(grid).toContain('data-testid="selectable-price"');
    expect(grid).toContain("Bet365");
    expect(grid).toContain("hace 12 min");
    expect(grid).toContain("Ver todas las casas (2)");
    expect(grid).toContain("primera cuota vista 2,10");
    expect(grid).not.toContain("abrió");
  });

  test("handicap and double chance stay among the highlights while the catalogue has no «Resultado»", async () => {
    const html = await prematch(
      client(
        catalog({ categories: [{ key: "corners", markets: 2, selections: 9, bookmakers: 2 }] }),
      ),
    );
    const grid = html.slice(html.indexOf('data-testid="markets-grid"'));
    expect([...grid.matchAll(/data-market="([^"]+)"/g)].map((m) => m[1])).toEqual([
      "1X2",
      "OU",
      "BTTS",
      "AH",
    ]);
  });

  test("after kick-off the same prices, chosen nowhere", async () => {
    const html = await prematch(client(catalog({})), "finished");
    expect(html).toContain("Cuotas antes del inicio");
    expect(html).toContain('data-testid="markets-grid"');
    expect(html).not.toContain('data-testid="selectable-price"');
  });

  test("in English", async () => {
    setLocale("en");
    const html = await prematch(client(catalog({})));
    expect(html).toContain(">Highlights<");
    expect(html).toContain(">Corners<");
    expect(html).toContain("6 bookmakers");
    expect(html).not.toContain("Destacados");
  });
});

describe("a category of the catalogue", () => {
  test("its markets folded, the first open on its main line, shown only: no parlay", () => {
    const qc = client(catalog({}));
    qc.setQueryData(
      ["v1", "match-market-catalog", ID, "corners"],
      envelope(catalog({ category: "corners", markets: [CORNERS, CORNERS_1X2] })),
    );
    const html = category(qc, "corners");
    expect(html).toContain('data-testid="markets-shown-only"');
    expect(html).toContain("Más/menos córners");
    expect(html).toContain("Más córners (1X2)");
    expect(html).toContain("90&#x27;");
    const toggles = [...html.matchAll(/aria-expanded="(true|false)"/g)].map((m) => m[1]);
    expect(toggles[0]).toBe("true");
    expect(html).toContain("9,5");
    expect(html).not.toContain("10,5");
    expect(html).toContain("Ver 2 líneas más");
    expect(html).toContain("Ver todas las casas (2)");
    expect(html).toContain("Pinnacle");
    expect(html).toContain("hace 12 min");
    expect(html).not.toContain('data-testid="selectable-price"');
    // the stable keys stay in the attributes: no text on screen is a key
    expect(html).not.toMatch(/>[^<]*corners_(over_under|1x2)/);
  });

  test("one of the five inside a category still goes to the parlay", () => {
    const qc = client(catalog({}));
    qc.setQueryData(
      ["v1", "match-market-catalog", ID, "goals"],
      envelope(catalog({ category: "goals", markets: [BTTS] })),
    );
    const html = category(qc, "goals");
    expect(html).toContain('data-market="BTTS"');
    expect(html).toContain('data-testid="selectable-price"');
    expect(html).not.toContain('data-testid="markets-shown-only"');
  });

  test("a category with nothing in force says so", () => {
    const qc = client(catalog({}));
    qc.setQueryData(
      ["v1", "match-market-catalog", ID, "corners"],
      envelope(catalog({ category: "corners", markets: [] })),
    );
    expect(category(qc, "corners")).toContain("No hay cuotas vigentes en esta categoría.");
  });
});

describe("the captures, for the owner", () => {
  test("the same strip and numbers, now drawn in Avanzado / Auditoría", () => {
    const html = renderToStaticMarkup(<CapturesStrip all={ALL} />);
    expect(html).toContain('data-testid="captures-strip"');
    expect(html).toContain("Capturas de cuotas");
    expect(html).toContain("T-72 h · 397");
  });
});
