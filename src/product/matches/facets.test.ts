/// <reference types="bun" />
import { describe, expect, test } from "bun:test";
import {
  categoriesOf,
  countryKey,
  countryOptions,
  genderOf,
  inFacets,
  matchesTeam,
  WORLD,
} from "./facets";

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
      competition: comp({ name: "Liga F", country: "Spain", country_code: "ES" }),
      home: { name: "Barcelona" },
      away: { name: "Levante" },
    } as never;
    expect(inFacets(m, { country: "ES", category: "women", team: "barce" })).toBe(true);
    expect(inFacets(m, { country: "CO", category: null, team: "" })).toBe(false);
    expect(inFacets(m, { country: null, category: "cup", team: "" })).toBe(false);
  });
});
