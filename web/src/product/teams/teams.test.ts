/// <reference types="bun" />
/** The profiles' model (UX-154 to UX-157): the last results, the table excerpt, the squad by position, the age. */
import { describe, expect, test } from "bun:test";
import type { CompetitionSummary, MatchSummary } from "@/lib/api/v1/types";
import type { PlayerSummary, TableRow } from "@/lib/api/v1/types_center";
import { setLocale } from "@/lib/i18n";
import {
  ageOf,
  countryName,
  excerpt,
  formOf,
  isNation,
  parseTab,
  squadGroups,
  teamLabel,
} from "./model";
import { byCountry, byRegion, NATION_SHORTCUTS } from "./TeamsPage";
import { REGIONS } from "@/product/competitions/region";
import { t as tc } from "@/product/competitions/text";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const m = (id: number, home: number, away: number, score: [number, number] | null) =>
  ({
    id,
    home: { id: home, name: `T${home}` },
    away: { id: away, name: `T${away}` },
    score: score ? { home: score[0], away: score[1] } : null,
  }) as unknown as MatchSummary;

describe("the profiles", () => {
  test("the last results from the team's side; matches without a score are skipped", () => {
    const f = formOf(
      [m(1, 7, 2, [2, 0]), m(2, 3, 7, [1, 1]), m(3, 7, 4, null), m(4, 5, 7, [3, 1])],
      7,
    );
    expect(f.map((x) => [x.match.id, x.result, x.goalsFor, x.goalsAgainst])).toEqual([
      [1, "W", 2, 0],
      [2, "D", 1, 1],
      [4, "L", 1, 3],
    ]);
  });

  test("the table excerpt keeps five rows around the team, inside the table", () => {
    const rows = Array.from(
      { length: 10 },
      (_, i) => ({ rank: i + 1, team_id: 100 + i }) as TableRow,
    );
    expect(excerpt(rows, 100).map((r) => r.rank)).toEqual([1, 2, 3, 4, 5]);
    expect(excerpt(rows, 105).map((r) => r.rank)).toEqual([4, 5, 6, 7, 8]);
    expect(excerpt(rows, 109).map((r) => r.rank)).toEqual([6, 7, 8, 9, 10]);
    expect(excerpt(rows, 999)).toEqual([]);
  });

  test("the squad in the order a line-up reads, most minutes first", () => {
    const p = (id: number, position: string | null, minutes: number) =>
      ({ id, name: `P${id}`, position, minutes }) as PlayerSummary;
    const g = squadGroups([
      p(1, "Attacker", 90),
      p(2, "Goalkeeper", 900),
      p(3, "Attacker", 500),
      p(4, null, 1),
    ]);
    expect(g.map((x) => [x.group, x.players.map((y) => y.id)])).toEqual([
      ["Goalkeeper", [2]],
      ["Attacker", [3, 1]],
      ["Other", [4]],
    ]);
  });

  test("a national side, the age, the tab and the countries", () => {
    expect(isNation({ name: "Colombia", country: "Colombia" })).toBe(true);
    expect(isNation({ name: "Millonarios", country: "Colombia" })).toBe(false);
    expect(ageOf("2000-11-17", Date.parse("2026-11-16T12:00:00Z"))).toBe(25);
    expect(ageOf("2000-11-16", Date.parse("2026-11-16T12:00:00Z"))).toBe(26);
    expect(ageOf(null)).toBeNull();
    expect(parseTab("squad")).toBe("squad");
    expect(parseTab("x")).toBe("summary");
    const c = (id: number, country: string | null, tracked = true) =>
      ({ id, name: `C${id}`, country, is_tracked: tracked, tier: 1 }) as CompetitionSummary;
    expect(
      byCountry([c(1, "Spain"), c(2, "Colombia"), c(3, "Argentina", false)]).map((g) => g.country),
    ).toEqual(["Colombia", "Spain"]);
  });
});

describe("AP-T02: the countries in the reader's language", () => {
  const c = (id: number, country: string | null) =>
    ({ id, name: `C${id}`, country, is_tracked: true, tier: 1 }) as CompetitionSummary;

  test("es: «Belgium» and «Brazil» are «Bélgica» and «Brasil»; a national side is named like its country", () => {
    setLocale("es");
    expect(countryName("Belgium")).toBe("Bélgica");
    expect(countryName("Brazil")).toBe("Brasil");
    expect(countryName("World")).toBe("Internacional");
    expect(countryName(null)).toBeNull();
    expect(countryName("Atlantis")).toBe("Atlantis");
    expect(teamLabel({ name: "Belgium", country: "Belgium" })).toBe("Bélgica");
    expect(teamLabel({ name: "Brazil", country: "Brazil" })).toBe("Brasil");
    expect(teamLabel({ name: "Millonarios", country: "Colombia" })).toBe("Millonarios");
    setLocale("es");
  });

  test("en: the English names stay", () => {
    setLocale("en");
    expect(countryName("Belgium")).toBe("Belgium");
    expect(teamLabel({ name: "Brazil", country: "Brazil" })).toBe("Brazil");
    setLocale("es");
  });

  test("the groups carry their label, Colombia first, the rest by the label in the reader's language", () => {
    setLocale("es");
    const groups = byCountry([c(1, "Spain"), c(2, "Colombia"), c(3, "Belgium"), c(4, "Germany")]);
    expect(groups.map((g) => g.label)).toEqual(["Colombia", "Alemania", "Bélgica", "España"]);
    expect(groups.map((g) => g.country)).toEqual(["Colombia", "Germany", "Belgium", "Spain"]);
  });
});

describe("Equipos como portada (AP-E02)", () => {
  const c = (id: number, country: string, code: string | null) =>
    ({
      id,
      name: `C${id}`,
      country,
      country_code: code,
      is_tracked: true,
      tier: 1,
    }) as CompetitionSummary;

  test("los países se agrupan por región, la del lector primero, y no se inventa una región", () => {
    setLocale("es");
    const groups = byCountry([
      c(1, "Spain", "ES"),
      c(2, "Colombia", "CO"),
      c(3, "Brazil", "BR"),
      c(4, "Japan", "JP"),
      c(5, "Atlantis", null),
      c(6, "World", null),
    ]);
    const regions = byRegion(groups);
    expect(regions.map((r) => r.region)).toEqual([
      "sudamerica",
      "europa",
      "asia",
      "internacional",
      "otras",
    ]);
    expect(regions[0]!.countries.map((g) => g.country)).toEqual(["Colombia", "Brazil"]);
    expect(regions[4]!.countries.map((g) => g.country)).toEqual(["Atlantis"]);
  });

  test("las selecciones de atajo salen con su nombre en español y en inglés", () => {
    setLocale("es");
    expect(NATION_SHORTCUTS.map((n) => countryName(n))).toEqual([
      "Colombia",
      "Brasil",
      "Argentina",
      "España",
      "Inglaterra",
      "Alemania",
      "Países Bajos",
      "Sudáfrica",
    ]);
    setLocale("en");
    expect(countryName("Spain")).toBe("Spain");
    setLocale("es");
  });
});

describe("Equipos · las palabras de las regiones (26-nov-2026)", () => {
  test("cada región y «Mundo» se traducen en es y en en, nunca se muestra la clave", () => {
    for (const locale of ["es", "en"] as const) {
      setLocale(locale);
      for (const r of REGIONS) {
        const key = `competitions.directory.region.${r}`;
        expect(tc(key)).not.toBe(key);
      }
      expect(countryName("World")).toBe(locale === "es" ? "Internacional" : "International");
    }
    setLocale("es");
  });

  test("ningún módulo registra un catálogo con un `import` sin nombres (package.json dice sideEffects:false y el empaquetador lo descarta)", () => {
    const bare = /^import\s+"@\/[^"]*";\s*$/m;
    const bad: string[] = [];
    const walk = (dir: string) => {
      for (const f of readdirSync(dir)) {
        const p = join(dir, f);
        if (statSync(p).isDirectory()) walk(p);
        else if (/\.(ts|tsx)$/.test(f) && !/\.test\./.test(f) && bare.test(readFileSync(p, "utf8")))
          bad.push(p);
      }
    };
    walk(join(import.meta.dir, "..", ".."));
    expect(bad).toEqual([]);
  });
});
