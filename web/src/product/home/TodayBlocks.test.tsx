/// <reference types="bun" />
/**
 * Inicio's blocks from GET /today (plan UX, A9; section 24), rendered: the matches of the suggested leagues with why they
 * show («Sugerida»), the forecast labelled («sin calibrar») and a line of the reading; an empty day that says so and
 * names the next matches; a failure with its retry - never an empty list -; the context of the next matches with the
 * reference of each fact; and the results, each to its Postpartido.
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
import type { Following, Today, TodayMatch } from "@/lib/api/v1/types_today";
import {
  ContextBlock,
  RelevantBlock,
  ResultsBlock,
  TodayBlock,
  type TodayQuery,
} from "./TodayBlocks";

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
    .replace(/&quot;/g, '"')
    .replace(/[\u00a0\u202f]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** Saturday 24 October 2026, 10:00 in Bogotá. */
const NOW = Date.parse("2026-10-24T15:00:00Z");
const H = 3_600_000;
let next = 500;

function m(over: Partial<TodayMatch> & { at: number }): TodayMatch {
  const { at, ...rest } = over;
  const id = next++;
  return {
    fixture_id: id,
    kickoff_at: new Date(at).toISOString(),
    status_group: "scheduled",
    status: "NS",
    elapsed: null,
    goals_home: null,
    goals_away: null,
    competition: {
      id: 1,
      name: "Liga BetPlay",
      country: "Colombia",
      logo_url: null,
      flag_url: null,
    },
    home: { id: 1, name: "Nacional", logo_url: null },
    away: { id: 2, name: "Millonarios", logo_url: null },
    suggested: true,
    forecast: null,
    headline: null,
    has_reading: false,
    context: [],
    ...rest,
  };
}

function board(matches: TodayMatch[]): Today {
  return {
    day: "2026-10-24",
    suggested: [
      { id: 1, name: "Liga BetPlay", country: "Colombia", logo_url: null, flag_url: null },
    ],
    suggested_team: "Colombia",
    matches: { status: matches.length ? "ok" : "empty", data: matches, reason: null },
    no_pick: {
      status: "ok",
      data: {
        day: "2026-10-24",
        state: "none",
        stage: null,
        reason: "no_qualified_candidates",
        matches: 1,
      },
      reason: null,
    },
  };
}

function loaded(today: Today): TodayQuery {
  return {
    isPending: false,
    isError: false,
    data: { status: "ok", data: today, reason: null, meta: {} },
    error: null,
    dataUpdatedAt: NOW,
    refetch: () => Promise.resolve(),
  } as unknown as TodayQuery;
}

function failed(): TodayQuery {
  return {
    isPending: false,
    isError: true,
    data: undefined,
    error: new LiveApiError("down", 503, "unavailable", "req-123"),
    dataUpdatedAt: 0,
    refetch: () => Promise.resolve(),
  } as unknown as TodayQuery;
}

describe("1 · Hoy en las ligas sugeridas", () => {
  test("a match with why it shows, the forecast labelled and a line of its reading", async () => {
    const match = m({
      at: NOW + 2 * H,
      forecast: { outcome: "away", probability: "0.523", calibrated: false },
      headline: { code: "match_kind", params: { kind: "final" }, ref: "packet:fixture" },
      has_reading: true,
    });
    const markup = await html(<TodayBlock query={loaded(board([match]))} now={NOW} />);
    const page = text(markup);
    expect(markup).toContain(`href="/matches/${match.fixture_id}"`);
    expect(page).toContain("Hoy en las ligas sugeridas");
    expect(page).toContain("Sugerida");
    expect(markup).toContain('data-testid="today-why"');
    expect(page).toContain("Pronóstico: gana Millonarios 52 %");
    expect(page).toContain("sin calibrar");
    expect(markup).toContain('data-testid="today-headline"');
    expect(page).toContain("no es una recomendación");
    expect(page).toContain("Actualizado a las");
    expect(page).not.toMatch(/\bvalor\b/i);
  });

  test("no suggested match today: said, with the next ones", async () => {
    const tomorrow = m({ at: NOW + 30 * H });
    const page = text(await html(<TodayBlock query={loaded(board([tomorrow]))} now={NOW} />));
    expect(page).toContain("Hoy no juegan las ligas sugeridas.");
    expect(page).toContain("Próximos partidos de las ligas sugeridas");
  });

  test("a failure: its reference and a retry, never «no matches»", async () => {
    const page = text(await html(<TodayBlock query={failed()} now={NOW} />));
    expect(page).toContain("req-123");
    expect(page).toContain("Reintentar");
    expect(page).not.toContain("Hoy no juegan");
  });
});

describe("3 · Partidos relevantes and 5 · Qué se juega", () => {
  test("out of the page with nothing to show", async () => {
    const quiet = loaded(board([m({ at: NOW + H })]));
    expect(await html(<RelevantBlock query={quiet} now={NOW} />)).toBe("");
    expect(await html(<ContextBlock query={quiet} now={NOW} />)).toBe("");
  });

  test("the context of the next match, each fact with its reference, to the match's Análisis", async () => {
    const match = m({
      at: NOW + 20 * H,
      context: [
        {
          code: "stakes_pressure",
          params: { side: "home", team: "Nacional", pressure: "title" },
          ref: "packet:stakes.home",
        },
        {
          code: "rest_days",
          params: { side: "away", team: "Millonarios", days: 3, matches_14d: 4, at_most: false },
          ref: "packet:schedule.away",
        },
        { code: "a_code_from_the_future", params: {}, ref: "packet:x" },
      ],
    });
    const markup = await html(<ContextBlock query={loaded(board([match]))} now={NOW} />);
    expect(markup).toContain(`href="/matches/${match.fixture_id}#analysis"`);
    expect(markup).toContain('data-ref="packet:stakes.home"');
    expect(markup).toContain('data-ref="packet:schedule.away"');
    expect(markup).not.toContain("a_code_from_the_future");
    expect(text(markup)).toContain("Millonarios llega con 3 días de descanso");
  });
});

describe("6 · Resultados", () => {
  test("a result opens its Postpartido; none says so", async () => {
    const done = m({
      at: NOW - 5 * H,
      status_group: "finished",
      status: "FT",
      goals_home: 2,
      goals_away: 1,
    });
    const markup = await html(<ResultsBlock query={loaded(board([done]))} now={NOW} />);
    expect(markup).toContain(`href="/matches/${done.fixture_id}#postmatch"`);
    expect(text(markup)).toContain("Final");
    const empty = text(await html(<ResultsBlock query={loaded(board([]))} now={NOW} />));
    expect(empty).toContain("Sin resultados recientes en las ligas sugeridas.");
  });
});

describe("A13 · Hoy en tus ligas", () => {
  const following = (over: Partial<Following> = {}): Following => ({
    suggested: false,
    personalization: true,
    leagues: [{ id: 1, name: "Liga BetPlay", country: "Colombia", logo_url: null, flag_url: null }],
    teams: [{ id: 7, name: "Santa Fe", logo_url: null }],
    next: [],
    ...over,
  });
  const mine = (matches: TodayMatch[], f: Following): Today => ({
    ...board(matches),
    following: f,
  });

  test("the reader's own: their title, why each match is theirs, their leagues and teams named, the way to change them", async () => {
    const byTeam = m({
      at: NOW + H,
      suggested: false,
      followed: { kind: "team", names: ["Santa Fe"] },
      competition: { id: 9, name: "Copa", country: "Colombia", logo_url: null, flag_url: null },
    });
    const byLeague = m({ at: NOW + 2 * H, followed: { kind: "league", names: ["Liga BetPlay"] } });
    const notMine = m({ at: NOW + 3 * H, suggested: true, followed: null });
    const markup = await html(
      <TodayBlock query={loaded(mine([byTeam, byLeague, notMine], following()))} now={NOW} />,
    );
    const page = text(markup);
    expect(page).toContain("Hoy en tus ligas");
    expect(page).not.toContain("ligas sugeridas");
    expect(markup).toContain('data-view="mine"');
    expect(page).toContain("Sigues a Santa Fe");
    expect(page).toContain("Tu liga");
    expect(markup).toContain("porque sigues a Santa Fe");
    expect(markup).not.toContain(`data-fixture="${notMine.fixture_id}"`);
    expect(markup).toContain('data-testid="mine-chips"');
    expect(page).toContain("Cambiar");
    expect(markup).toContain('href="/profile#football"');
  });

  test("while the reader chose none: the suggested ones, labelled, and the way to choose", async () => {
    const match = m({ at: NOW + H, followed: { kind: "league", names: ["Liga BetPlay"] } });
    const markup = await html(
      <TodayBlock query={loaded(mine([match], following({ suggested: true })))} now={NOW} />,
    );
    const page = text(markup);
    expect(page).toContain("Hoy en las ligas sugeridas");
    expect(page).toContain("Sugerida");
    expect(page).toContain("Elegir mis ligas");
    expect(markup).toContain('data-testid="suggested-leagues"');
  });

  test("personalisation off: the common view, without the way to choose", async () => {
    const match = m({ at: NOW + H, followed: { kind: "league", names: ["Liga BetPlay"] } });
    const markup = await html(
      <TodayBlock
        query={loaded(mine([match], following({ suggested: true, personalization: false })))}
        now={NOW}
      />,
    );
    expect(text(markup)).toContain("Hoy en las ligas sugeridas");
    expect(markup).not.toContain('data-testid="today-choose"');
  });

  test("their leagues do not play today: it says so and lists the next match of each favourite", async () => {
    const elsewhere = m({ at: NOW + H, suggested: true, followed: null });
    const next = [
      {
        followed: { kind: "team" as const, names: ["Santa Fe"] },
        fixture_id: 901,
        kickoff_at: new Date(NOW + 30 * H).toISOString(),
        competition: { id: 9, name: "Copa", country: "Colombia", logo_url: null, flag_url: null },
        home: { id: 7, name: "Santa Fe", logo_url: null },
        away: { id: 8, name: "Junior", logo_url: null },
      },
    ];
    const markup = await html(
      <TodayBlock query={loaded(mine([elsewhere], following({ next })))} now={NOW} />,
    );
    const page = text(markup);
    expect(page).toContain("Hoy no juegan tus ligas.");
    expect(page).toContain("Lo próximo de tus favoritos");
    expect(page).toContain("Próximo de Santa Fe");
    expect(markup).toContain('href="/matches/901"');
  });

  test("B2: the suggestion sits with the reader's own part; never with personalisation off", async () => {
    const match = m({ at: NOW + H, followed: { kind: "league", names: ["Liga BetPlay"] } });
    const slot = <p data-testid="slot">¿Agregas la Serie A a tus ligas?</p>;
    const on = await html(
      <TodayBlock query={loaded(mine([match], following()))} now={NOW} suggestion={slot} />,
    );
    expect(on).toContain('data-testid="slot"');
    const off = await html(
      <TodayBlock
        query={loaded(mine([match], following({ personalization: false })))}
        now={NOW}
        suggestion={slot}
      />,
    );
    expect(off).not.toContain('data-testid="slot"');
  });

  test("Qué se juega and Resultados follow the reader's own too", async () => {
    const stake = {
      code: "stakes_pressure",
      params: { pressure: "title", team: "Santa Fe", side: "home" },
      ref: "packet:stakes.home",
    };
    const ahead = m({
      at: NOW + 5 * H,
      suggested: false,
      followed: { kind: "team", names: ["Santa Fe"] },
      context: [stake],
    });
    const done = m({
      at: NOW - 5 * H,
      status_group: "finished",
      status: "FT",
      goals_home: 1,
      goals_away: 0,
      suggested: false,
      followed: { kind: "team", names: ["Santa Fe"] },
    });
    const today = mine([ahead, done], following());
    const context = text(await html(<ContextBlock query={loaded(today)} now={NOW} />));
    expect(context).toContain("tus ligas y equipos");
    const results = await html(<ResultsBlock query={loaded(today)} now={NOW} />);
    expect(text(results)).toContain("Tus ligas y equipos · últimas 48 horas");
    expect(results).toContain(`data-fixture="${done.fixture_id}"`);
    const none = text(await html(<ResultsBlock query={loaded(mine([], following()))} now={NOW} />));
    expect(none).toContain("Sin resultados recientes de tus equipos.");
  });
});
