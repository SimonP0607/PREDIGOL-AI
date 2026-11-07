/// <reference types="bun" />
/**
 * «Últimos resultados» (plan de Inicio, 3.1), rendered: each row says when it was played, who, the score, the competition and
 * how it ended - with the shoot-out when there was one - and opens its Postpartido; a day without results says so; a refresh
 * that fails keeps the rows with a small notice; a failure is never read as «no results».
 */
import { afterEach, beforeEach, describe, expect, test } from "bun:test";
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
import { LiveApiError } from "@/lib/api/v1/client";
import type { Home, HomeResult } from "@/lib/api/v1/types_product";
import { ResultsBlock, playedAt, type HomeQuery } from "./ResultsBlock";

setLocale("es");
beforeEach(() => setTimeZone("America/Bogota"));
afterEach(() => setTimeZone("UTC"));

async function html(node: ReactNode): Promise<string> {
  const router = createRouter({
    routeTree: createRootRoute({ component: () => node }),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  await router.load();
  return renderToStaticMarkup(<RouterProvider router={router} />);
}

function text(markup: string): string {
  return markup
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/[\u00a0\u202f]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** Saturday 7 November 2026, 15:00 in Bogotá. */
const NOW = Date.parse("2026-11-07T20:00:00Z");
const H = 3_600_000;
let next = 900;

function result(over: Partial<HomeResult> & { at: number }): HomeResult {
  const { at, ...rest } = over;
  return {
    fixture_id: next++,
    kickoff_at: new Date(at).toISOString(),
    competition: {
      id: 1,
      name: "Liga BetPlay",
      country: "Colombia",
      logo_url: null,
      flag_url: null,
    },
    home: { id: 1, name: "Nacional", logo_url: null },
    away: { id: 2, name: "Millonarios", logo_url: null },
    status: "FT",
    goals_home: 2,
    goals_away: 1,
    ...rest,
  };
}

function home(rows: HomeResult[]): Home {
  return {
    source: "qualified",
    data_freshness: { live_at: null },
    live: { status: "empty", data: [], reason: "no_live_matches" },
    results: {
      status: rows.length ? "ok" : "empty",
      data: rows,
      reason: rows.length ? null : "no_recent_results",
    },
  };
}

function query(over: { data?: Home; isError?: boolean; error?: unknown }): HomeQuery {
  const { data, ...rest } = over;
  return {
    isPending: false,
    isError: false,
    error: null,
    data: data ? { status: "ok", data, reason: null, meta: {} } : undefined,
    refetch: () => Promise.resolve(),
    ...rest,
  } as unknown as HomeQuery;
}

describe("Últimos resultados", () => {
  test("a result opens its Postpartido, with who, the score, the competition and when", async () => {
    const done = result({ at: NOW - 3 * H });
    const markup = await html(<ResultsBlock query={query({ data: home([done]) })} now={NOW} />);
    expect(markup).toContain(`href="/matches/${done.fixture_id}#postmatch"`);
    const page = text(markup);
    expect(page).toContain("Final");
    expect(page).toContain("Nacional");
    expect(page).toContain("Millonarios");
    expect(page).toContain("Liga BetPlay");
    expect(page).toContain("Hoy · 12:00");
    expect(markup).toContain('data-testid="results-list"');
  });

  test("extra time and a shoot-out say so, with the shoot-out", async () => {
    const aet = result({ at: NOW - 5 * H, status: "AET", goals_home: 2, goals_away: 2 });
    const pen = result({
      at: NOW - 4 * H,
      status: "PEN",
      goals_home: 1,
      goals_away: 1,
      pens_home: 4,
      pens_away: 3,
    });
    const page = text(
      await html(<ResultsBlock query={query({ data: home([pen, aet]) })} now={NOW} />),
    );
    expect(page).toContain("Final (prór.)");
    expect(page).toContain("Final (pen.)");
    expect(page).toContain("pen. 4-3");
  });

  test("none: said, never a blank block", async () => {
    const page = text(await html(<ResultsBlock query={query({ data: home([]) })} now={NOW} />));
    expect(page).toContain("Últimos resultados");
    expect(page).toContain("no hay resultados de las últimas 24 horas");
  });

  test("a failure: its retry, never «no results»", async () => {
    const error = new LiveApiError("down", 503, "unavailable", "rid-1");
    const markup = await html(<ResultsBlock query={query({ isError: true, error })} now={NOW} />);
    expect(markup).toContain('role="alert"');
    expect(markup).not.toContain("results-empty");
  });

  test("a refresh that fails keeps the rows, with a small notice and no error card", async () => {
    const done = result({ at: NOW - 3 * H });
    const markup = await html(
      <ResultsBlock
        query={query({ data: home([done]), isError: true, error: new Error("x") })}
        now={NOW}
      />,
    );
    expect(markup).toContain('data-testid="stale-note"');
    expect(markup).not.toContain('role="alert"');
    expect(markup).toContain(`data-fixture="${done.fixture_id}"`);
  });

  test("an API older than this block has no results: the block says none", async () => {
    const old = home([]);
    delete old.results;
    const page = text(await html(<ResultsBlock query={query({ data: old })} now={NOW} />));
    expect(page).toContain("no hay resultados de las últimas 24 horas");
  });
});

describe("when it was played", () => {
  test("Hoy, Ayer or the day, then the hour", () => {
    expect(playedAt(new Date(NOW - 2 * H).toISOString(), NOW)).toBe("Hoy · 13:00");
    expect(playedAt(new Date(NOW - 20 * H).toISOString(), NOW)).toBe("Ayer · 19:00");
    expect(playedAt(new Date(NOW - 60 * H).toISOString(), NOW)).toContain("5 nov");
  });
});
