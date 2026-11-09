/// <reference types="bun" />
/**
 * A reader's favourites, the welcome, the hints and the tour on the page (plan UX, A13), without a browser: the picker's
 * rules (the limits, the reader's order, what a save added and removed), the leagues by country, the search as the API
 * folds it; the welcome's steps and where it leads; a dismissed hint never shown again (UNIT: «pistas que no vuelven»);
 * the tour's pages; and the picker as it renders - every toggle a 44 px button that says its state. The browser half is
 * e2e/onboarding.spec.ts.
 */
import { describe, expect, test } from "bun:test";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import type { Me } from "@/lib/api/v1/types_auth";
import type { PlayerBadge } from "@/lib/api/v1/types_favorites";
import type { CompetitionBadge, TeamBadge } from "@/lib/api/v1/types_product";
import type { Today } from "@/lib/api/v1/types_today";
import { whyText } from "@/product/home/why";
import { afterWelcome } from "@/product/welcome/next";
import { FavoritesPicker } from "./FavoritesPicker";
import { catalogKeyName } from "./catalogName";
import { validEvent } from "@/lib/track";
import type { FavoritesView } from "@/lib/api/v1/types_favorites";
import {
  MARKETS,
  beforeOf,
  bodyOf,
  byCountry,
  changes,
  choiceOf,
  chosenIn,
  extrasBody,
  fold,
  followableMarket,
  followedFirst,
  full,
  hasCatalog,
  hasMarket,
  hasPlayer,
  leagueMatches,
  limitsOf,
  playerSearchable,
  searchable,
  toggleCatalog,
  toggleLeague,
  toggleMarket,
  togglePlayer,
  toggleTeam,
  type Choice,
} from "./model";
import { trackChanges } from "./analytics";
import { hintShown, welcomeSteps, withOnboarding } from "./onboarding";

setLocale("es");

const league = (
  id: number,
  name: string,
  country: string | null = "Colombia",
): CompetitionBadge => ({
  id,
  name,
  country,
  logo_url: null,
  flag_url: null,
});
const team = (id: number, name: string): TeamBadge => ({ id, name, logo_url: null });
const LIMITS = { leagues: 2, teams: 2, players: 2, markets: 2, catalog: 2 };
const player = (id: number, name: string): PlayerBadge => ({
  id,
  name,
  position: "Midfielder",
  team: "Millonarios",
});
const EMPTY: Choice = { leagues: [], teams: [], players: [], markets: [], catalog: [] };

describe("the picker's rules", () => {
  test("added at the end (the reader's order), taken away with a tap, nothing added at a limit", () => {
    let c: Choice = EMPTY;
    c = toggleLeague(c, league(2, "B"), LIMITS);
    c = toggleLeague(c, league(1, "A"), LIMITS);
    expect(c.leagues.map((l) => l.id)).toEqual([2, 1]);
    expect(full(c, LIMITS)).toEqual({
      leagues: true,
      teams: false,
      players: false,
      markets: false,
      catalog: false,
    });
    expect(toggleLeague(c, league(3, "C"), LIMITS).leagues.map((l) => l.id)).toEqual([2, 1]);
    expect(toggleLeague(c, league(2, "B"), LIMITS).leagues.map((l) => l.id)).toEqual([1]);
    c = toggleTeam(toggleTeam(c, team(7, "X"), LIMITS), team(8, "Y"), LIMITS);
    expect(toggleTeam(c, team(9, "Z"), LIMITS).teams.map((x) => x.id)).toEqual([7, 8]);
  });

  test("what a save added and removed; the suggested ones were never the reader's, so saving them adds them", () => {
    const before: Choice = { ...EMPTY, leagues: [league(1, "A")], teams: [team(7, "X")] };
    const after: Choice = { ...EMPTY, leagues: [league(1, "A"), league(2, "B")] };
    expect(changes(before, after)).toEqual({
      added: [{ kind: "competition", id: 2 }],
      removed: [{ kind: "team", id: 7 }],
    });
    expect(changes(null, after).added).toEqual([
      { kind: "competition", id: 1 },
      { kind: "competition", id: 2 },
    ]);
  });

  test("the leagues by country: Colombia first, the rest by name, the international ones last", () => {
    const groups = byCountry([
      league(1, "Serie A", "Italy"),
      league(2, "Libertadores", null),
      league(3, "Primera B", "Colombia"),
      league(4, "Liga BetPlay", "Colombia"),
      league(5, "Champions", "World"),
      league(6, "LaLiga", "Spain"),
    ]);
    expect(groups.map((g) => g.country)).toEqual(["Colombia", "Italy", "Spain", null]);
    expect(groups[0]?.leagues.map((l) => l.name)).toEqual(["Liga BetPlay", "Primera B"]);
    expect(groups[3]?.leagues.map((l) => l.name)).toEqual(["Champions", "Libertadores"]);
  });

  test("a league is found by its name or its country; a country's row counts what is chosen", () => {
    const premier = league(2, "Premier League", "England");
    expect(leagueMatches(premier, "premier")).toBe(true);
    expect(leagueMatches(premier, "ENGL")).toBe(true);
    expect(leagueMatches(league(3, "Liga BetPlay"), "betplay")).toBe(true);
    expect(leagueMatches(premier, "serie")).toBe(false);
    expect(leagueMatches(premier, "  ")).toBe(false);
    const c: Choice = { ...EMPTY, leagues: [premier] };
    expect(chosenIn(c, [premier, league(4, "Championship", "England")])).toBe(1);
  });

  test("the search as the API folds it: no accents, no case, two letters or more", () => {
    expect(fold("Atlético NACIONAL")).toBe("atletico nacional");
    expect(fold("São Paulo")).toBe("sao paulo");
    expect(searchable(" a ")).toBe(false);
    expect(searchable("ñu")).toBe(true);
  });
});

const me = (over: Partial<Me> = {}): Me =>
  ({ id: 1, role: "USER", hints_seen: [], welcome_due: true, ...over }) as Me;

describe("the welcome and the hints", () => {
  test("the steps the API lists - football always, about for a new account", () => {
    expect(welcomeSteps(me({ welcome_steps: ["football", "about"] }))).toEqual([
      "football",
      "about",
    ]);
    expect(welcomeSteps(me({ welcome_steps: ["football"] }))).toEqual(["football"]);
    expect(welcomeSteps(me({ welcome_steps: ["nonsense"] }))).toEqual(["football"]);
    expect(welcomeSteps(null)).toEqual(["football"]);
  });

  test("after the welcome: the page the reader asked for, never another site nor the welcome again", () => {
    expect(afterWelcome("")).toBe("/home");
    expect(afterWelcome("?next=%2Fmatches%2F42")).toBe("/matches/42");
    expect(afterWelcome("?next=%2F%2Fevil.example")).toBe("/home");
    expect(afterWelcome("?next=https%3A%2F%2Fevil.example")).toBe("/home");
    expect(afterWelcome("?next=%2Fwelcome")).toBe("/home");
  });

  test("a dismissed hint never comes back; only a reader's account sees them, and only with an API that keeps them", () => {
    expect(hintShown(me(), "picks")).toBe(true);
    expect(hintShown(me({ hints_seen: ["picks"] }), "picks")).toBe(false);
    expect(hintShown(me({ hints_seen: ["picks"] }), "match")).toBe(true);
    expect(hintShown(me({ role: "SUPER_ADMIN" }), "picks")).toBe(false);
    const old = me();
    delete (old as { hints_seen?: string[] }).hints_seen;
    expect(hintShown(old, "picks")).toBe(false);
    expect(hintShown(null, "picks")).toBe(false);
  });

  test("the account as the API now says it: the welcome done, the hints it keeps", () => {
    const done = withOnboarding(me({ welcome_steps: ["football", "about"] }), {
      welcome_due: false,
      welcome_steps: ["football", "about"],
      onboarded_at: "2026-10-26T12:00:00Z",
      hints_seen: ["parlay"],
    });
    expect(done.welcome_due).toBe(false);
    expect(done.welcome_steps).toEqual([]);
    expect(done.hints_seen).toEqual(["parlay"]);
    expect(hintShown(done, "parlay")).toBe(false);
  });
});

describe("the reasons", () => {
  test("why a match shows, in both languages", () => {
    expect(whyText({ kind: "team", names: ["Nacional", "Millonarios"] }).label).toBe(
      "Sigues a Nacional y Millonarios",
    );
    expect(whyText({ kind: "league", names: ["Liga BetPlay"] }).label).toBe("Tu liga");
    expect(whyText({ kind: "suggested" }).label).toBe("Sugerida");
    setLocale("en");
    expect(whyText({ kind: "team", names: ["Nacional"] }).help).toBe(
      "We show you this match because you follow Nacional.",
    );
    setLocale("es");
  });
});

describe("the picker as it renders", () => {
  function render(
    choice: Choice,
    limits = { leagues: 10, teams: 20, players: 20, markets: 5, catalog: 10 },
  ): string {
    const qc = new QueryClient();
    qc.setQueryData(["me", "favorite-options", ""], {
      leagues: [league(1, "Liga BetPlay"), league(2, "Premier League", "England")],
      teams: [],
      players: [],
    });
    return renderToStaticMarkup(
      <QueryClientProvider client={qc}>
        <FavoritesPicker choice={choice} limits={limits} onChange={() => undefined} />
      </QueryClientProvider>,
    );
  }

  test("the reader's choice on top, every league a toggle that says its state, 44 px each", () => {
    const html = render({
      ...EMPTY,
      leagues: [league(1, "Liga BetPlay")],
      teams: [team(7, "Santa Fe")],
    });
    expect(html).toContain("1 de 10 ligas");
    expect(html).toContain("1 de 20 equipos");
    expect(html).toContain('aria-label="Quitar Santa Fe"');
    expect(html.match(/data-testid="fav-league"/g)?.length).toBe(2);
    expect(html.match(/aria-pressed="true"/g)?.length).toBe(1);
    expect(html.match(/aria-pressed="false"/g)?.length).toBe(6); // Premier League and the five markets
    expect(html).toContain("min-h-11");
    expect(html).toContain('for="'); // the search has its label
  });

  test("at the limit: said before the reader tries, the rest disabled", () => {
    const html = render(
      { ...EMPTY, leagues: [league(1, "Liga BetPlay")] },
      { leagues: 1, teams: 20, players: 20, markets: 5, catalog: 10 },
    );
    expect(html).toContain("Llegaste a 1 ligas");
    expect(html).toMatch(/aria-pressed="false" disabled=""/);
  });
});

describe("players and markets (closing plan 3.1)", () => {
  const view = (over: Partial<FavoritesView> = {}): FavoritesView => ({
    leagues: [league(1, "Liga BetPlay")],
    teams: [team(7, "Santa Fe")],
    players: [player(50, "James Rodríguez")],
    markets: ["OU"],
    suggested: false,
    max_leagues: 10,
    max_teams: 20,
    max_players: 2,
    max_markets: 2,
    personalization: true,
    ...over,
  });

  test("a player is added at the end, taken away with a tap, nothing added at the limit", () => {
    let c = togglePlayer(EMPTY, player(2, "B"), LIMITS);
    c = togglePlayer(c, player(1, "A"), LIMITS);
    expect(c.players.map((p) => p.id)).toEqual([2, 1]);
    expect(full(c, LIMITS).players).toBe(true);
    expect(togglePlayer(c, player(3, "C"), LIMITS).players.map((p) => p.id)).toEqual([2, 1]);
    expect(togglePlayer(c, player(2, "B"), LIMITS).players.map((p) => p.id)).toEqual([1]);
    expect(hasPlayer(c, 1)).toBe(true);
    expect(hasPlayer(c, 9)).toBe(false);
  });

  test("a market likewise: the reader's order, a tap takes it away, nothing added at the limit", () => {
    let c = toggleMarket(EMPTY, "OU", LIMITS);
    c = toggleMarket(c, "1X2", LIMITS);
    expect(c.markets).toEqual(["OU", "1X2"]);
    expect(full(c, LIMITS).markets).toBe(true);
    expect(toggleMarket(c, "BTTS", LIMITS).markets).toEqual(["OU", "1X2"]);
    expect(toggleMarket(c, "OU", LIMITS).markets).toEqual(["1X2"]);
    expect(hasMarket(c, "1X2")).toBe(true);
    expect(hasMarket(c, "DC")).toBe(false);
  });

  test("the markets a reader may follow are the five PrediGol reads; another is not offered", () => {
    expect([...MARKETS]).toEqual(["1X2", "OU", "BTTS", "AH", "DC"]);
    expect(followableMarket("BTTS")).toBe("BTTS");
    expect(followableMarket("CS")).toBeNull();
    expect(followableMarket("")).toBeNull();
  });

  test("a catalogue market is added at the end, taken away with a tap, nothing added at the limit", () => {
    let c = toggleCatalog(EMPTY, "corners_over_under.FT.match", LIMITS);
    c = toggleCatalog(c, "goals_btts.1H.match", LIMITS);
    expect(c.catalog).toEqual(["corners_over_under.FT.match", "goals_btts.1H.match"]);
    expect(full(c, LIMITS).catalog).toBe(true);
    expect(toggleCatalog(c, "cards_over_under.FT.match", LIMITS).catalog).toEqual(c.catalog);
    expect(toggleCatalog(c, "corners_over_under.FT.match", LIMITS).catalog).toEqual([
      "goals_btts.1H.match",
    ]);
    expect(hasCatalog(c, "goals_btts.1H.match")).toBe(true);
    expect(hasCatalog(c, "nope")).toBe(false);
    expect(c.markets).toEqual([]);
  });

  test("the catalogue markets the reader follows go first, the rest keep the usual order", () => {
    const views = ["a", "b", "c", "d"].map((key) => ({ key }));
    expect(followedFirst(views, []).map((v) => v.key)).toEqual(["a", "b", "c", "d"]);
    expect(followedFirst(views, ["d", "b"]).map((v) => v.key)).toEqual(["d", "b", "a", "c"]);
    expect(followedFirst(views, ["x"]).map((v) => v.key)).toEqual(["a", "b", "c", "d"]);
  });

  test("a save with catalogue markets sends them, and an older answer reads as none", () => {
    const v = view({ catalog_markets: ["corners_over_under.FT.match"], max_catalog_markets: 3 });
    expect(bodyOf(choiceOf(v)).catalog_markets).toEqual(["corners_over_under.FT.match"]);
    expect(limitsOf(v).catalog).toBe(3);
    expect(choiceOf(view()).catalog).toEqual([]);
    expect(limitsOf(view()).catalog).toBe(10);
    // a catalogue market is not announced to the product's analytics (the event names the five classic ones alone)
    const only = { ...EMPTY, catalog: ["corners_over_under.FT.match"] };
    expect(changes(EMPTY, only)).toEqual({ added: [], removed: [] });
  });

  test("what is sent holds everything the reader follows, in their order", () => {
    const c = choiceOf(view());
    expect(bodyOf(c)).toEqual({
      leagues: [1],
      teams: [7],
      players: [50],
      markets: ["OU"],
      catalog_markets: [],
    });
    expect(limitsOf(view())).toEqual({
      leagues: 10,
      teams: 20,
      players: 2,
      markets: 2,
      catalog: 10,
    });
    expect(limitsOf(undefined)).toEqual({
      leagues: 10,
      teams: 20,
      players: 20,
      markets: 5,
      catalog: 10,
    });
  });

  test("a tap on a player never makes the suggested leagues and teams the reader's", () => {
    const suggested = view({ suggested: true });
    const next = togglePlayer(choiceOf(suggested), player(51, "Falcao"), limitsOf(suggested));
    expect(extrasBody(suggested, next)).toEqual({
      leagues: [],
      teams: [],
      players: [50, 51],
      markets: ["OU"],
      catalog_markets: [],
    });
    const own = view();
    expect(extrasBody(own, next).leagues).toEqual([1]);
    expect(extrasBody(own, next).teams).toEqual([7]);
  });

  test("what a save added and removed names players by id and markets by key", () => {
    const before = beforeOf(view());
    const after: Choice = {
      ...before,
      players: [player(51, "Falcao")],
      markets: ["OU", "BTTS"],
    };
    expect(changes(before, after)).toEqual({
      added: [
        { kind: "player", id: 51 },
        { kind: "market", market: "BTTS" },
      ],
      removed: [{ kind: "player", id: 50 }],
    });
  });

  test("the suggested leagues and teams were never the reader's; their players and markets always were", () => {
    const before = beforeOf(view({ suggested: true }));
    expect(before.leagues).toEqual([]);
    expect(before.teams).toEqual([]);
    expect(before.players.map((p) => p.id)).toEqual([50]);
    expect(before.markets).toEqual(["OU"]);
    const after = choiceOf(view({ suggested: true }));
    expect(changes(before, after).added).toEqual([
      { kind: "competition", id: 1 },
      { kind: "team", id: 7 },
    ]);
  });

  test("every change is an event the catalog accepts: an id, or for a market its key", () => {
    const sent: unknown[] = [];
    for (const c of [
      { kind: "player" as const, id: 51 },
      { kind: "market" as const, market: "BTTS" as const },
      { kind: "competition" as const, id: 1 },
    ]) {
      const props =
        c.kind === "market" ? { kind: c.kind, market: c.market } : { kind: c.kind, id: c.id };
      sent.push(validEvent("favorite_added", props));
    }
    expect(sent).toEqual([
      { kind: "player", id: 51 },
      { kind: "market", market: "BTTS" },
      { kind: "competition", id: 1 },
    ]);
    expect(validEvent("favorite_added", { kind: "market", market: "CS" })).toBeNull();
    expect(validEvent("favorite_removed", { kind: "player", name: "James" })).toBeNull();
    expect(() => trackChanges({ added: [], removed: [] })).not.toThrow();
  });

  test("a player is searched from three letters", () => {
    expect(playerSearchable("ja")).toBe(false);
    expect(playerSearchable(" jam ")).toBe(true);
    expect(playerSearchable("Ñu")).toBe(false);
    expect(playerSearchable("ÁÉÍ")).toBe(true);
  });
});

describe("the picker shows players and markets", () => {
  function render(choice: Choice): string {
    const qc = new QueryClient();
    qc.setQueryData(["me", "favorite-options", ""], {
      leagues: [league(1, "Liga BetPlay")],
      teams: [],
      players: [],
    });
    return renderToStaticMarkup(
      <QueryClientProvider client={qc}>
        <FavoritesPicker
          choice={choice}
          limits={{ leagues: 10, teams: 20, players: 2, markets: 2, catalog: 10 }}
          onChange={() => undefined}
        />
      </QueryClientProvider>,
    );
  }

  test("the counts, the chips that remove and the five markets as toggles that say their state", () => {
    const html = render({
      ...EMPTY,
      players: [player(50, "James Rodríguez")],
      markets: ["OU", "BTTS"],
    });
    expect(html).toContain("1 de 2 jugadores");
    expect(html).toContain("2 de 2 mercados");
    expect(html).toContain('aria-label="Quitar James Rodríguez"');
    expect(html).toContain('aria-label="Quitar Más/Menos goles"');
    expect(html.match(/data-testid="fav-market"/g)?.length).toBe(5);
    expect(html).toContain("Mercados que lees");
    expect(html).toContain("no cambian ningún pick, probabilidad ni cuota");
    // two markets chosen, the limit: the other three cannot be added
    expect(html.match(/data-testid="fav-market"/g)?.length).toBe(5);
    expect((html.match(/aria-pressed="false" disabled=""/g) ?? []).length).toBeGreaterThanOrEqual(
      3,
    );
  });

  test("a followed catalogue market is a chip that removes, named in the reader's words", () => {
    const html = render({
      ...EMPTY,
      markets: ["OU"],
      catalog: ["corners_over_under.FT.match", "goals_btts.1H.match", "yellow_cards_1x2.FT.home"],
    });
    expect(html).toContain('data-kind="catalog"');
    expect(html).toContain('data-id="corners_over_under.FT.match"');
    expect(html).toContain('aria-label="Quitar Más/menos córners"');
    expect(html).toContain("1.ª parte");
    expect(html).toContain("local");
    expect(html).not.toContain("corners_over_under</span>");
  });

  test("with no league or team the reader is still told the suggested ones will show", () => {
    const html = render({ ...EMPTY, players: [player(50, "James Rodríguez")] });
    expect(html).toContain("Aún no eliges ninguna liga ni equipo");
    expect(html).toContain('data-kind="player"');
  });

  test("a full list of players says so before the reader tries", () => {
    const html = render({ ...EMPTY, players: [player(1, "A"), player(2, "B")] });
    expect(html).toContain("Llegaste a 2 jugadores");
  });
});

describe("a catalogue market in the reader's words", () => {
  test("its name, the side of a team's market and the period of a half; an unknown code is never shown raw", () => {
    expect(catalogKeyName("corners_over_under.FT.match")).toBe("Más/menos córners");
    expect(catalogKeyName("yellow_cards_1x2.FT.home")).toContain("local");
    expect(catalogKeyName("yellow_cards_1x2.FT.away")).toContain("visitante");
    expect(catalogKeyName("goals_btts.1H.match")).toContain("1.ª parte");
    const strange = catalogKeyName("bet_999.FT.match");
    expect(strange).not.toContain("bet_999");
  });
});
