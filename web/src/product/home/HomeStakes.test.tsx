/// <reference types="bun" />
/**
 * «Partidos relevantes» and «Qué se juega» (plan de Inicio, 3.1b), rendered: each match with the sentence of its reason and a link
 * to the match; a block with nothing to show is out of the page; «En vivo» does not read «nothing in play» while the relevant
 * matches are on the page.
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
import type { LiveMatch } from "@/lib/api/v1/types_center";
import type { Home, HomeAtStake, HomeRelevant } from "@/lib/api/v1/types_product";
import { AtStakeBlock, RelevantNowBlock, kickoffAt } from "./HomeStakes";
import { LiveTiles } from "./LiveTiles";
import type { HomeQuery } from "./ResultsBlock";

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

function live(id: number, over: Partial<LiveMatch> = {}): LiveMatch {
  return {
    fixture_id: id,
    kickoff_at: "2026-11-07T19:00:00Z",
    competition: "Liga BetPlay",
    country: "Colombia",
    home: { id: 1, name: "Nacional", logo_url: null },
    away: { id: 2, name: "Millonarios", logo_url: null },
    status: "2H",
    elapsed: 61,
    extra: null,
    goals_home: 0,
    goals_away: 1,
    state_at: "2026-11-07T19:59:00Z",
    state_source: "fixture_feed",
    state_age_seconds: 20,
    odds_feed_at: null,
    markets_offered: null,
    values_suspended: null,
    events: [],
    statistics: [],
    main_odds: [],
    data_status: "ok",
    ...over,
  };
}

const relevant = (id: number, reasons: HomeRelevant["reasons"]): HomeRelevant => ({
  match: live(id),
  reasons,
});

function atStake(id: number, at: number, reason: HomeAtStake["reason"]): HomeAtStake {
  return {
    fixture_id: id,
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
    reason,
  };
}

function query(body: Partial<Home>): HomeQuery {
  const data: Home = {
    source: "qualified",
    data_freshness: { live_at: null },
    live: { status: "empty", data: [], reason: "no_live_matches" },
    ...body,
  };
  return {
    isPending: false,
    isError: false,
    error: null,
    data: { status: "ok", data, reason: null, meta: {} },
    refetch: () => Promise.resolve(),
  } as unknown as HomeQuery;
}

const ok = <T,>(data: T[]) => ({ status: "ok" as const, data, reason: null });

describe("Partidos relevantes", () => {
  test("each match opens, with its score and the sentence of its reason", async () => {
    const markup = await html(
      <RelevantNowBlock
        query={query({
          relevant: ok([
            relevant(11, [
              { code: "stakes", params: { team: "Nacional", pressure: "title", state: "behind" } },
              { code: "comeback", params: { team: "Millonarios", down_by: 1, state: "level" } },
            ]),
          ]),
        })}
      />,
    );
    expect(markup).toContain('href="/matches/11"');
    const page = text(markup);
    expect(page).toContain("Partidos relevantes");
    expect(page).toContain("Nacional");
    expect(page).toContain("Nacional pelea el título y ahora pierde.");
    expect(page).toContain("Millonarios iba perdiendo por 1 gol y ya empata.");
    expect(markup).toContain('href="/live"');
  });

  test("a reason the client cannot word leaves no line, never a wrong one", async () => {
    const markup = await html(
      <RelevantNowBlock
        query={query({
          relevant: ok([relevant(12, [{ code: "tie", params: { home: "Nacional" } }])]),
        })}
      />,
    );
    expect(markup).toContain('data-fixture="12"');
    expect(markup).not.toContain("reason-lines");
  });

  test("out of the page with nothing to show, or from an API that does not send it", async () => {
    expect(await html(<RelevantNowBlock query={query({ relevant: ok([]) })} />)).toBe("");
    expect(await html(<RelevantNowBlock query={query({})} />)).toBe("");
  });
});

describe("Qué se juega", () => {
  test("a match with its day, hour, competition and one sentence", async () => {
    const markup = await html(
      <AtStakeBlock
        now={NOW}
        query={query({
          at_stake: ok([
            atStake(21, NOW + 2 * H, { code: "final", params: {} }),
            atStake(22, NOW + 20 * H, {
              code: "first_leg",
              params: { home: "Nacional", away: "Millonarios", first_home: 1, first_away: 3 },
            }),
          ]),
        })}
      />,
    );
    expect(markup).toContain('href="/matches/21"');
    const page = text(markup);
    expect(page).toContain("Qué se juega");
    expect(page).toContain("Hoy · 17:00");
    expect(page).toContain("Mañana · 11:00");
    expect(page).toContain("Es una final.");
    expect(page).toContain("En la ida: Nacional 1, Millonarios 3.");
    expect(page).not.toContain("descanso");
  });

  test("out of the page with nothing at stake", async () => {
    expect(await html(<AtStakeBlock now={NOW} query={query({ at_stake: ok([]) })} />)).toBe("");
  });

  test("the kick-off says today, tomorrow or the date", () => {
    expect(kickoffAt(new Date(NOW + H).toISOString(), NOW)).toBe("Hoy · 16:00");
    expect(kickoffAt(new Date(NOW + 26 * H).toISOString(), NOW)).toBe("Mañana · 17:00");
    expect(kickoffAt(new Date(NOW + 60 * H).toISOString(), NOW)).toContain(" · ");
  });
});

describe("En vivo beside Partidos relevantes", () => {
  const section = { status: "empty" as const, data: [] as LiveMatch[], reason: "no_live_matches" };

  test("empty while the relevant matches are on the page: it stays out, not «nothing in play»", async () => {
    const out = await html(<LiveTiles section={section} liveAt={null} elsewhere />);
    expect(out).toBe("");
  });

  test("empty with no relevant match: it says nothing is in play", async () => {
    const out = await html(<LiveTiles section={section} liveAt={null} />);
    expect(out).toContain('data-testid="home-live"');
  });
});
