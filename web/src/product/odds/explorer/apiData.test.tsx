/// <reference types="bun" />
/**
 * The explorer's data layer on the API (plan Cuotas, UX-069): the explorer's choices become the API's parameters with the
 * empty ones left out (one choice, one cache entry), and each hook reads the shared react-query cache with the envelopes
 * opened - the board as its pages, the book and the movement only once a row opens them.
 */
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider, type InfiniteData } from "@tanstack/react-query";
import { live } from "@/lib/api/v1/queries";
import type { Envelope } from "@/lib/api/v1/types";
import type { OddsBoardPage as ApiBoardPage } from "@/lib/api/v1/types_odds_explorer";
import {
  API_EXPLORER_DATA,
  boardParams,
  familiesParams,
  movementParams,
  REFRESH_MS,
} from "./apiData";
import { BOOKMAKERS, COMPETITIONS, fakeFamilies, fakeMovement, fakeRows, MARKETS } from "./fake";
import type { BoardQuery, FamiliesQuery, OddsBoardPage } from "./model";

function envelope<T>(data: T): Envelope<T> {
  return { status: "ok", data, reason: null, meta: {} } as unknown as Envelope<T>;
}

const FAMILIES: FamiliesQuery = { hours: 24, country: null, competition: null };

const BOARD: BoardQuery = {
  ...FAMILIES,
  market: "result.1x2",
  period: "FT",
  line: "main",
  q: "",
  bookmaker: null,
  min_books: null,
  odds_min: null,
  odds_max: null,
  fair_only: false,
  sort: "time",
};

function page(rows: OddsBoardPage["rows"], next: string | null): ApiBoardPage {
  return {
    market: MARKETS["result"]![0]!,
    period: "FT",
    rows,
    total: 5,
    next_cursor: next,
    competitions: COMPETITIONS,
    bookmakers: BOOKMAKERS,
    generated_at: "2026-11-08T11:59:00Z",
  } as ApiBoardPage;
}

describe("the API's parameters", () => {
  test("families: the window, and a country or competition only when one is chosen", () => {
    expect(familiesParams(FAMILIES)).toEqual({
      hours: 24,
      country: undefined,
      competition: undefined,
    });
    expect(familiesParams({ hours: 72, country: "Spain", competition: 140 })).toEqual({
      hours: 72,
      country: "Spain",
      competition: 140,
    });
  });

  test("the board: the explorer's own names, the empty ones left out, a period the API knows", () => {
    expect(JSON.parse(JSON.stringify(boardParams(BOARD)))).toEqual({
      hours: 24,
      market: "result.1x2",
      period: "FT",
      line: "main",
      sort: "time",
    });
    const full = boardParams({
      ...BOARD,
      period: "1H",
      line: "-0.25",
      q: "  Madrid ",
      bookmaker: 8,
      min_books: 3,
      odds_min: "1.5",
      odds_max: "3",
      fair_only: true,
      sort: "edge",
    });
    expect(full).toMatchObject({
      period: "1H",
      line: "-0.25",
      q: "Madrid",
      bookmaker: 8,
      min_books: 3,
      odds_min: "1.5",
      odds_max: "3",
      fair_only: true,
      sort: "edge",
    });
    expect(boardParams({ ...BOARD, period: "3H" }).period).toBeUndefined();
  });

  test("the movement: without a line, the market's main one", () => {
    expect(movementParams({ market: "goals.total", period: "FT", line: null })).toEqual({
      market: "goals.total",
      period: "FT",
      line: undefined,
    });
    expect(movementParams({ market: "goals.total", period: "2H", line: "2.5" }).line).toBe("2.5");
  });

  test("an open page reads again every two minutes", () => {
    expect(REFRESH_MS).toBe(120_000);
  });
});

describe("the hooks read the shared cache", () => {
  function render(qc: QueryClient, Probe: () => React.ReactNode): unknown {
    const html = renderToStaticMarkup(
      <QueryClientProvider client={qc}>
        <Probe />
      </QueryClientProvider>,
    );
    return JSON.parse(html.replace(/^<pre>|<\/pre>$/g, "").replaceAll("&quot;", '"'));
  }

  test("families and the board's pages, the envelopes opened", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(
      live.oddsFamilies(familiesParams(FAMILIES)).queryKey,
      envelope(fakeFamilies()) as never,
    );
    const rows = fakeRows("result.1x2", "FT", "main");
    const pages: InfiniteData<Envelope<ApiBoardPage>, string | undefined> = {
      pages: [envelope(page(rows.slice(0, 3), "c2")), envelope(page(rows.slice(3), "c3"))],
      pageParams: [undefined, "c2"],
    };
    qc.setQueryData(live.oddsBoardPages(boardParams(BOARD)).queryKey, pages as never);
    function Probe() {
      const f = API_EXPLORER_DATA.useFamilies(FAMILIES, { paused: false, enabled: true });
      const b = API_EXPLORER_DATA.useBoard(BOARD, { paused: false, enabled: true });
      return (
        <pre>
          {JSON.stringify({
            families: f.data?.families.map((x) => x.key),
            pending: f.isPending || b.isPending,
            pages: b.data?.length,
            rows: b.data?.flatMap((p) => p.rows).map((r) => r.fixture_id),
            more: b.hasNextPage,
            updated: b.updatedAt > 0,
          })}
        </pre>
      );
    }
    expect(render(qc, Probe)).toEqual({
      families: Object.keys(MARKETS),
      pending: false,
      pages: 2,
      rows: rows.map((r) => r.fixture_id),
      more: true,
      updated: true,
    });
  });

  test("a match's book and a line's movement: nothing until a row opens them, then the cache", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const q = { market: "result.1x2", period: "FT", line: null };
    qc.setQueryData(
      live.oddsMovement(7820, movementParams(q)).queryKey,
      envelope(fakeMovement(7820, q)) as never,
    );
    function Probe() {
      const book = API_EXPLORER_DATA.useMatchBook(7820, "result", false);
      const shut = API_EXPLORER_DATA.useMovement(7821, q, false);
      const open = API_EXPLORER_DATA.useMovement(7820, q, true);
      return (
        <pre>
          {JSON.stringify({
            book: book.data === undefined,
            shut: shut.data === undefined && !shut.isFetching,
            series: open.data?.series.length,
            source: open.data?.source,
          })}
        </pre>
      );
    }
    expect(render(qc, Probe)).toEqual({ book: true, shut: true, series: 3, source: "snapshots" });
  });
});
