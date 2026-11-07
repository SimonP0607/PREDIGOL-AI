/// <reference types="bun" />
import { afterAll, describe, expect, test } from "bun:test";
import { setLocale } from "@/lib/i18n";
import {
  categoriesOf,
  countryKey,
  countryOptions,
  genderOf,
  inFacets,
  matchesTeam,
  matchesTeamOrCompetition,
  playing,
  WORLD,
} from "./facets";

afterAll(() => setLocale("es"));

const comp = (over: Record<string, unknown>) =>
  ({
    id: 1,
    name: "La Liga",
    country: "Spain",
    country_code: "ES",
    competition_type: "domestic_league",
    ...over,
  }) as never;

describe("country, category and team (REVIEW points 3 and 11)", () => {
  test("a competition's categories: its type, plus women's or youth by name", () => {
    expect(categoriesOf(comp({}))).toEqual(["league"]);
    expect(
      categoriesOf(
        comp({ name: "Primera División Femenina", competition_type: "domestic_league" }),
      ),
    ).toEqual(["league", "women"]);
    expect(
      categoriesOf(comp({ name: "UEFA U19 Championship", competition_type: "international" })),
    ).toEqual(["international", "youth"]);
    expect(categoriesOf(comp({ name: "Copa del Rey", competition_type: "domestic_cup" }))).toEqual([
      "cup",
    ]);
    expect(genderOf({ name: "NWSL" })).toBe("women");
    expect(genderOf({ name: "Premier League" })).toBe("men");
  });

  test("world competitions file as international; countries sort by name, international last", () => {
    expect(countryKey({ country: "World", country_code: null })).toBe(WORLD);
    const opts = countryOptions(
      [
        { competition: comp({ country: "World", country_code: null }) },
        { competition: comp({ country: "Spain", country_code: "ES" }) },
        { competition: comp({ country: "Colombia", country_code: "CO" }) },
        { competition: comp({ country: "Spain", country_code: "ES" }) },
      ],
      "es",
      "Internacional",
    );
    expect(opts.map((o) => [o.key, o.count])).toEqual([
      ["CO", 1],
      ["ES", 2],
      [WORLD, 1],
    ]);
  });

  test("the team search reads team names only, without accents", () => {
    const m = { home: { name: "Atlético Nacional" }, away: { name: "Millonarios" } } as never;
    expect(matchesTeam(m, "atletico nac")).toBe(true);
    expect(matchesTeam(m, "liga")).toBe(false);
  });

  test("all facets together", () => {
    const m = {
      competition: comp({ id: 9, name: "Liga F", country: "Spain", country_code: "ES" }),
      home: { name: "Barcelona" },
      away: { name: "Levante" },
    } as never;
    const none = { country: null, category: null, competition: null, query: "" };
    expect(inFacets(m, { ...none, country: "ES", category: "women", query: "barce" })).toBe(true);
    expect(inFacets(m, { ...none, country: "CO" })).toBe(false);
    expect(inFacets(m, { ...none, category: "cup" })).toBe(false);
    expect(inFacets(m, { ...none, competition: 9 })).toBe(true);
    expect(inFacets(m, { ...none, competition: 10 })).toBe(false);
  });
});

describe("one search box for a team or a competition (plan Partidos, P6)", () => {
  const m = {
    competition: comp({ name: "La Liga", country: "Spain", country_code: "ES" }),
    home: { name: "Real Betis" },
    away: { name: "Atlético de Madrid" },
  } as never;

  test("a team, a competition by its name, or by its country in either language", () => {
    setLocale("es");
    expect(matchesTeamOrCompetition(m, "betis")).toBe(true);
    expect(matchesTeamOrCompetition(m, "atletico")).toBe(true);
    expect(matchesTeamOrCompetition(m, "la liga")).toBe(true);
    expect(matchesTeamOrCompetition(m, "españa")).toBe(true);
    expect(matchesTeamOrCompetition(m, "spain")).toBe(true);
    expect(matchesTeamOrCompetition(m, "liga betis")).toBe(true);
    expect(matchesTeamOrCompetition(m, "")).toBe(true);
    expect(matchesTeamOrCompetition(m, "bundesliga")).toBe(false);
    expect(matchesTeamOrCompetition(m, "betis bundesliga")).toBe(false);
  });

  test("En vivo keeps its team-only search", () => {
    expect(matchesTeam(m, "la liga")).toBe(false);
  });
});

describe("a facet that does not play that day is ignored (plan Partidos, P2)", () => {
  test("kept while it is among the day's options, dropped otherwise", () => {
    const options = [{ key: "league" }, { key: "cup" }];
    expect(playing("cup", options)).toBe("cup");
    expect(playing("women", options)).toBeNull();
    expect(playing(null, options)).toBeNull();
    expect(playing(7, [{ key: 7 }])).toBe(7);
    expect(playing(8, [{ key: 7 }])).toBeNull();
  });
});
