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
import type { CompetitionBadge, TeamBadge } from "@/lib/api/v1/types_product";
import type { Today } from "@/lib/api/v1/types_today";
import { whyText } from "@/product/home/why";
import { stepPath } from "@/product/tour/steps";
import { afterWelcome } from "@/product/welcome/next";
import { FavoritesPicker } from "./FavoritesPicker";
import {
  byCountry,
  changes,
  chosenIn,
  fold,
  full,
  leagueMatches,
  searchable,
  toggleLeague,
  toggleTeam,
  type Choice,
} from "./model";
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
const LIMITS = { leagues: 2, teams: 2 };

describe("the picker's rules", () => {
  test("added at the end (the reader's order), taken away with a tap, nothing added at a limit", () => {
    let c: Choice = { leagues: [], teams: [] };
    c = toggleLeague(c, league(2, "B"), LIMITS);
    c = toggleLeague(c, league(1, "A"), LIMITS);
    expect(c.leagues.map((l) => l.id)).toEqual([2, 1]);
    expect(full(c, LIMITS)).toEqual({ leagues: true, teams: false });
    expect(toggleLeague(c, league(3, "C"), LIMITS).leagues.map((l) => l.id)).toEqual([2, 1]);
    expect(toggleLeague(c, league(2, "B"), LIMITS).leagues.map((l) => l.id)).toEqual([1]);
    c = toggleTeam(toggleTeam(c, team(7, "X"), LIMITS), team(8, "Y"), LIMITS);
    expect(toggleTeam(c, team(9, "Z"), LIMITS).teams.map((x) => x.id)).toEqual([7, 8]);
  });

  test("what a save added and removed; the suggested ones were never the reader's, so saving them adds them", () => {
    const before: Choice = { leagues: [league(1, "A")], teams: [team(7, "X")] };
    const after: Choice = { leagues: [league(1, "A"), league(2, "B")], teams: [] };
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
    const c: Choice = { leagues: [premier], teams: [] };
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

describe("the tour and the reasons", () => {
  test("each step's page; the match is the first of today's board, else the list of matches", () => {
    const today = { matches: { data: [{ fixture_id: 42 }] } } as unknown as Today;
    expect([stepPath("home", today), stepPath("match", today), stepPath("pick", today)]).toEqual([
      "/home",
      "/matches/42",
      "/picks",
    ]);
    expect(stepPath("parlay", today)).toBe("/parlays");
    expect(stepPath("myPicks", null)).toBe("/my-picks");
    expect(stepPath("match", null)).toBe("/matches");
  });

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
  function render(choice: Choice, limits = { leagues: 10, teams: 20 }): string {
    const qc = new QueryClient();
    qc.setQueryData(["me", "favorite-options", ""], {
      leagues: [league(1, "Liga BetPlay"), league(2, "Premier League", "England")],
      teams: [],
    });
    return renderToStaticMarkup(
      <QueryClientProvider client={qc}>
        <FavoritesPicker choice={choice} limits={limits} onChange={() => undefined} />
      </QueryClientProvider>,
    );
  }

  test("the reader's choice on top, every league a toggle that says its state, 44 px each", () => {
    const html = render({ leagues: [league(1, "Liga BetPlay")], teams: [team(7, "Santa Fe")] });
    expect(html).toContain("1 de 10 ligas");
    expect(html).toContain("1 de 20 equipos");
    expect(html).toContain('aria-label="Quitar Santa Fe"');
    expect(html.match(/data-testid="fav-league"/g)?.length).toBe(2);
    expect(html.match(/aria-pressed="true"/g)?.length).toBe(1);
    expect(html.match(/aria-pressed="false"/g)?.length).toBe(1);
    expect(html).toContain("min-h-11");
    expect(html).toContain('for="'); // the search has its label
  });

  test("at the limit: said before the reader tries, the rest disabled", () => {
    const html = render(
      { leagues: [league(1, "Liga BetPlay")], teams: [] },
      { leagues: 1, teams: 20 },
    );
    expect(html).toContain("Llegaste a 1 ligas");
    expect(html).toMatch(/aria-pressed="false" disabled=""/);
  });
});
