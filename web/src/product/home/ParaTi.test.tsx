/// <reference types="bun" />
/**
 * «Para ti» (closing plan 3.2), rendered: the players the reader follows with the state of his team's next match - the state as
 * the data has it, a reason only for an absence -, the day's picks that are theirs (or the sentence that none is, or that the day
 * has none), their bells and whether the line-ups can reach them, the two layers' bands and the discreet prompt without
 * favourites. A failure shows with its reference and a retry - never an empty list.
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
import type {
  MatchBell,
  MeToday,
  PlayerState,
  RelatedPicks,
  WatchedPlayer,
} from "@/lib/api/v1/types_me_today";
import {
  ChoosePrompt,
  ForYouEdit,
  ForYouPart,
  Layer,
  NoticesBlock,
  PlayersBlock,
  RelatedPicksBlock,
  type MeQuery,
} from "./ParaTi";
import { stateText } from "./playerState";

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

/** Thursday 5 November 2026, 10:00 in Bogotá. */
const NOW = Date.parse("2026-11-05T15:00:00Z");
const H = 3_600_000;

const badge = (id: number, name: string) => ({ id, name, logo_url: null });
const competition = {
  id: 1,
  name: "Liga BetPlay",
  country: "Colombia",
  logo_url: null,
  flag_url: null,
};

function player(state: PlayerState, over: Partial<WatchedPlayer> = {}): WatchedPlayer {
  const match = state !== "no_match";
  return {
    id: 7,
    name: "James Rodríguez",
    position: "Midfielder",
    team: match ? badge(10, "Millonarios") : null,
    state,
    reason: null,
    next: match
      ? {
          fixture_id: 900,
          kickoff_at: new Date(NOW + 3 * H).toISOString(),
          competition,
          home: badge(10, "Millonarios"),
          away: badge(11, "Nacional"),
        }
      : null,
    ...over,
  };
}

const me = (over: Partial<MeToday> = {}): MeToday => ({
  personalization: true,
  chosen: true,
  players: [],
  markets: [],
  picks: null,
  notices: null,
  ...over,
});

function loaded(value: MeToday): MeQuery {
  return {
    isPending: false,
    isError: false,
    data: value,
    error: null,
    refetch: () => Promise.resolve(),
  } as unknown as MeQuery;
}
const pending = { isPending: true, isError: false, data: undefined } as unknown as MeQuery;
const failed = {
  isPending: false,
  isError: true,
  data: undefined,
  error: new LiveApiError("down", 503, "unavailable", "req-777"),
  refetch: () => Promise.resolve(),
} as unknown as MeQuery;

/** A board that is not read: these tests never reach a pick's card. */
const board = { isPending: true, isError: false, data: undefined } as never;

describe("Tus jugadores", () => {
  test("each player says what the next match of his team has for him, as the data has it", async () => {
    const markup = await html(
      <PlayersBlock
        now={NOW}
        players={[
          player("starter"),
          player("absent", { id: 8, name: "Radamel Falcao", reason: "Knee Injury" }),
          player("doubtful", { id: 9, name: "Duván Zapata", reason: "Muscle Injury" }),
          player("waiting", { id: 10, name: "Luis Díaz" }),
          player("no_match", { id: 11, name: "Jugador Viejo" }),
        ]}
      />,
    );
    const page = text(markup);
    expect(page).toContain("Tus jugadores");
    expect(page).toContain("Titular");
    expect(page).toContain("Baja · Lesión");
    expect(page).toContain("Duda · Lesión");
    expect(page).toContain("Aún sin alineación ni bajas");
    expect(page).toContain("Sin partido próximo");
    expect(markup).toContain('data-state="starter"');
    expect(markup).toContain('data-state="no_match"');
    expect(page).toContain("Millonarios – Nacional · Hoy 13:00");
    expect(markup).toContain('href="/matches/900#lineups"');
  });

  test("a player with no match to come is not a link and says no match: nothing is made up", async () => {
    const markup = await html(
      <PlayersBlock now={NOW} players={[player("no_match", { id: 11, name: "Jugador Viejo" })]} />,
    );
    expect(markup).not.toContain("<a ");
    expect(markup).not.toContain('data-testid="player-next"');
    expect(text(markup)).toContain("Sin partido próximo");
  });

  test("none followed: the block stays out", async () => {
    expect(text(await html(<PlayersBlock now={NOW} players={[]} />))).toBe("");
  });

  test("the reason only tells for an absence", () => {
    expect(stateText({ state: "starter", reason: "Knee Injury" })).toBe("Titular");
    expect(stateText({ state: "absent", reason: null })).toBe("Baja");
    expect(stateText({ state: "absent", reason: "Red Card" })).toBe("Baja · Sanción");
  });
});

describe("Picks de tus partidos", () => {
  const picks = (over: Partial<RelatedPicks>): RelatedPicks => ({
    day: "2026-11-05",
    published: 3,
    items: [],
    ...over,
  });

  test("none of the day's picks is theirs: it says how many there were and where they are", async () => {
    const markup = await html(<RelatedPicksBlock me={me({ picks: picks({}) })} board={board} />);
    const page = text(markup);
    expect(page).toContain("Picks de tus partidos");
    expect(page).toContain(
      "Ninguno de los 3 picks publicados hoy es de tus equipos, ligas, jugadores ni mercados",
    );
    expect(markup).toContain('data-testid="related-none"');
  });

  test("one pick in the day, none theirs: the singular", async () => {
    const page = text(
      await html(<RelatedPicksBlock me={me({ picks: picks({ published: 1 }) })} board={board} />),
    );
    expect(page).toContain(
      "El pick publicado hoy no es de tus equipos, ligas, jugadores ni mercados",
    );
  });

  test("a day without published picks says so, whatever they follow", async () => {
    const markup = await html(
      <RelatedPicksBlock me={me({ picks: picks({ published: 0 }) })} board={board} />,
    );
    expect(text(markup)).toContain(
      "Hoy no hay picks publicados, tengas lo que tengas en favoritos",
    );
    expect(markup).toContain('data-testid="related-none-day"');
  });

  test("a reader who follows no team, league or market has no such block", async () => {
    expect(text(await html(<RelatedPicksBlock me={me({ picks: null })} board={board} />))).toBe("");
  });

  test("their picks are one notice with a line each that goes to the card below - never a second card", async () => {
    const loaded = {
      data: {
        status: "ok",
        data: {
          set: {
            items: [
              {
                rank: 1,
                match: { fixture_id: 5, home: { name: "Nacional" }, away: { name: "Junior" } },
              },
              {
                rank: 2,
                match: { fixture_id: 6, home: { name: "Cali" }, away: { name: "Pasto" } },
              },
            ],
          },
        },
      },
    } as unknown as Parameters<typeof RelatedPicksBlock>[0]["board"];
    const two = picks({
      items: [
        {
          rank: 1,
          fixture_id: 5,
          market_key: "OU",
          followed: { kind: "team", names: ["Nacional"] },
          market_followed: false,
        },
        {
          rank: 2,
          fixture_id: 6,
          market_key: "1X2",
          followed: null,
          market_followed: true,
          players: ["Uno"],
        },
      ],
    });
    const markup = await html(<RelatedPicksBlock me={me({ picks: two })} board={loaded} />);
    const page = text(markup);
    expect(page).toContain("2 picks de hoy coinciden con tus favoritos");
    expect(page).toContain("Nacional – Junior");
    expect(page).toContain("Tu equipo");
    expect(page).toContain("Tu jugador");
    expect(page).toContain("Tu mercado");
    expect(markup).toContain('href="#pick-1"');
    expect(markup).toContain('href="#pick-2"');
    expect(markup).not.toContain('data-testid="daily-item"');
    const one = await html(
      <RelatedPicksBlock me={me({ picks: picks({ items: [two.items[0]!] }) })} board={loaded} />,
    );
    expect(text(one)).toContain("1 pick de hoy coincide con tus favoritos");
  });

  test("their picks wait for the day's cards: a skeleton, never an empty list", async () => {
    const withPick = picks({
      items: [{ rank: 1, fixture_id: 5, market_key: "OU", followed: null, market_followed: true }],
    });
    const markup = await html(<RelatedPicksBlock me={me({ picks: withPick })} board={board} />);
    expect(markup).not.toContain('data-testid="related-none"');
    expect(markup).not.toContain('data-testid="related-list"');
  });
});

describe("Tus avisos", () => {
  const bell = (fixture: number, minutes: number, at: number): MatchBell => ({
    fixture_id: fixture,
    kickoff_at: new Date(at).toISOString(),
    minutes_before: minutes,
    competition,
    home: badge(10, "Millonarios"),
    away: badge(11, "Nacional"),
  });
  const notices = (over: Partial<NonNullable<MeToday["notices"]>> = {}) => ({
    available: true,
    devices: 1,
    lineup: true,
    bells: [],
    ...over,
  });

  test("their bells, soonest first, with the match and when; the line-ups reach their devices", async () => {
    const markup = await html(
      <NoticesBlock
        teams
        now={NOW}
        me={me({
          notices: notices({ bells: [bell(900, 30, NOW + 3 * H), bell(901, 60, NOW + 30 * H)] }),
        })}
      />,
    );
    const page = text(markup);
    expect(page).toContain("Tus avisos");
    expect(page).toContain("Millonarios – Nacional");
    expect(page).toContain("30 minutos antes · 13:00");
    expect(page).toContain("1 hora antes");
    expect(markup).toContain('data-status="lineupOn"');
    expect(markup).not.toContain('data-testid="notices-link"');
  });

  test("no device: it says the line-ups do not reach them and the way to turn notices on", async () => {
    const markup = await html(
      <NoticesBlock teams now={NOW} me={me({ notices: notices({ devices: 0 }) })} />,
    );
    expect(markup).toContain('data-status="noDevice"');
    expect(text(markup)).toContain("las alineaciones de tus equipos no te llegan");
    expect(markup).toContain('href="/profile#notifications"');
  });

  test("the line-up category off: said, with the way to change it", async () => {
    const markup = await html(
      <NoticesBlock teams now={NOW} me={me({ notices: notices({ lineup: false }) })} />,
    );
    expect(markup).toContain('data-status="lineupOff"');
    expect(text(markup)).toContain("Tienes apagados los avisos de alineaciones");
  });

  test("nothing to say stays out: no bells and no invitation (notices off, or no team followed)", async () => {
    expect(
      text(
        await html(
          <NoticesBlock teams now={NOW} me={me({ notices: notices({ available: false }) })} />,
        ),
      ),
    ).toBe("");
    expect(
      text(await html(<NoticesBlock teams={false} now={NOW} me={me({ notices: notices() })} />)),
    ).toBe("");
    expect(text(await html(<NoticesBlock teams now={NOW} me={me({ notices: null })} />))).toBe("");
  });

  test("a reader with no team still sees their bells", async () => {
    const markup = await html(
      <NoticesBlock
        teams={false}
        now={NOW}
        me={me({ notices: notices({ bells: [bell(900, 15, NOW + H)] }) })}
      />,
    );
    expect(markup).toContain('data-testid="notices-bell"');
    expect(markup).not.toContain('data-testid="notices-status"');
  });

  test("more bells than shown: how many more", async () => {
    const bells = [1, 2, 3, 4, 5].map((i) => bell(900 + i, 30, NOW + i * H));
    const markup = await html(
      <NoticesBlock teams now={NOW} me={me({ notices: notices({ bells }) })} />,
    );
    expect(markup.match(/data-testid="notices-bell"/g)?.length).toBe(3);
    expect(text(markup)).toContain("Y 2 avisos más, en tus partidos");
  });
});

describe("the layers", () => {
  test("each is a landmark named by its band; «Para ti» carries the way to change the favourites", async () => {
    const markup = await html(
      <>
        <Layer
          id="for-you"
          title="Para ti"
          hint="Lo que elegiste seguir"
          tone="primary"
          action={<ForYouEdit />}
        >
          <p>uno</p>
        </Layer>
        <Layer id="predigol" title="PrediGol" hint="Lo mismo para todos" tone="gold">
          <p>dos</p>
        </Layer>
      </>,
    );
    expect(markup).toContain('aria-labelledby="layer-for-you"');
    expect(markup).toContain('id="layer-predigol"');
    expect(text(markup)).toContain("Cambiar favoritos");
    expect(markup.match(/data-testid="layer-edit"/g)?.length).toBe(1);
    expect(markup).toContain('href="/profile#football"');
  });

  test("without favourites: one discreet line to choose them, that can be closed", async () => {
    const markup = await html(<ChoosePrompt />);
    const page = text(markup);
    expect(page).toContain("Elige tus favoritos");
    expect(page).toContain("los picks son los mismos para todos");
    expect(markup).toContain('data-testid="choose-prompt-link"');
    expect(markup).toContain('href="/profile#football"');
    expect(markup).toContain('data-testid="choose-prompt-close"');
    expect(markup).toContain('aria-label="Cerrar"');
  });
});

describe("ForYouPart", () => {
  const props = { board, teams: true, now: NOW };

  test("while /me/today loads: one skeleton, in the picks part only", async () => {
    const picks = await html(<ForYouPart part="picks" query={pending} {...props} />);
    expect(picks).toContain('aria-busy="true"');
    for (const part of ["players", "notices"] as const) {
      expect(text(await html(<ForYouPart part={part} query={pending} {...props} />))).toBe("");
    }
  });

  test("when it fails: the reference and a retry in the picks part - never an empty list", async () => {
    const markup = await html(<ForYouPart part="picks" query={failed} {...props} />);
    expect(markup).toContain('data-testid="for-you-failed"');
    expect(text(markup)).toContain("req-777");
    expect(text(await html(<ForYouPart part="players" query={failed} {...props} />))).toBe("");
  });

  test("the owner's query is off: nothing to wait for, so no skeleton", async () => {
    const off = { isPending: true, isError: false, data: undefined, fetchStatus: "idle" } as never;
    expect(await html(<ForYouPart part="picks" query={off} {...props} />)).toBe("");
  });

  test("when it answers: each part is its own block", async () => {
    const value = me({
      players: [player("bench")],
      picks: { day: "2026-11-05", published: 0, items: [] },
      notices: { available: true, devices: 0, lineup: true, bells: [] },
    });
    expect(await html(<ForYouPart part="players" query={loaded(value)} {...props} />)).toContain(
      'data-testid="home-players"',
    );
    expect(await html(<ForYouPart part="picks" query={loaded(value)} {...props} />)).toContain(
      'data-testid="home-related"',
    );
    expect(await html(<ForYouPart part="notices" query={loaded(value)} {...props} />)).toContain(
      'data-testid="home-notices"',
    );
  });
});
