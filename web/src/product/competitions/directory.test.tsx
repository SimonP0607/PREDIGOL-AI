/// <reference types="bun" />
/**
 * Plan PM, PM-09-05 (UX-179; lámina I08): the directory lists every competition PrediGol follows with its measured level and,
 * when it has P0 or P1, «Destacada»; groups them by region (Colombia in Sudamérica, England in Europa, the World Cup in «Torneos
 * internacionales»); filters by name or country (without accents), by level with its counts, by «Solo destacadas» and «Las que
 * sigo»; and says that the level measures data, not the quality of a league. Accessible: chips are pressed buttons, every level
 * tag carries its meaning for a screen reader, each region has its heading.
 */
import { afterAll, describe, expect, test } from "bun:test";
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { setLocale } from "@/lib/i18n";
import type { CompetitionSummary } from "@/lib/api/v1/types";
import type { CompetitionAvailability, CoverageLevel } from "@/lib/api/v1/types_availability";
import { DirectoryView } from "./DirectoryPage";
import {
  byRegion,
  countryCount,
  directoryEntries,
  filterEntries,
  levelCounts,
  NO_FILTER,
} from "./directory";
import { regionOf } from "./region";

afterAll(() => setLocale("es"));

async function html(node: ReactNode): Promise<string> {
  const router = createRouter({
    routeTree: createRootRoute({ component: () => node }),
    history: createMemoryHistory({ initialEntries: ["/competitions"] }),
  });
  await router.load();
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

function avail(
  id: number,
  name: string,
  country: string | null,
  level: CoverageLevel,
  priority: "P0" | "P1" | "P2" | "P3" | null,
): CompetitionAvailability {
  return {
    competition_id: id,
    name,
    country: country ?? { missing_reason: "sin_datos" },
    tier: 1,
    priority: priority ?? { missing_reason: "sin_datos" },
    summary: level,
    summary_label: level,
    families: [],
    seasons: [],
  } as CompetitionAvailability;
}

function cat(
  id: number,
  country: string | null,
  code: string | null,
  type = "league",
): CompetitionSummary {
  return {
    id,
    provider_league_id: id,
    name: `#${id}`,
    country,
    type,
    competition_type: "domestic_league",
    tier: 1,
    is_tracked: true,
    seasons: 1,
    current_season: 2026,
    fixtures: 10,
    teams: 10,
    country_code: code,
  };
}

const AVAIL = [
  avail(1, "Primera A", "Colombia", "A", "P0"),
  avail(2, "Primera B", "Colombia", "D", "P0"),
  avail(3, "Copa Colombia", "Colombia", "B", null),
  avail(4, "Premier League", "England", "A", "P2"),
  avail(5, "Primera División", "Spain", "A", "P2"),
  avail(6, "World Cup", null, "B", "P1"),
  avail(7, "J1 League", "Japan", "C", "P3"),
  avail(8, "Botola Pro", "Morocco", "C", null),
];
const CATALOGUE = [
  cat(1, "Colombia", "CO"),
  cat(2, "Colombia", "CO"),
  cat(3, "Colombia", "CO", "cup"),
  cat(4, "England", "GB-ENG"),
  cat(5, "Spain", "ES"),
  cat(6, "World", null, "cup"),
  cat(7, "Japan", "JP"),
  cat(8, "Morocco", "MA"),
];
const ENTRIES = directoryEntries(AVAIL, CATALOGUE);

describe("the directory's model", () => {
  test("regions by the country's confederation; international on its own", () => {
    expect(regionOf("Colombia", "CO")).toBe("sudamerica");
    expect(regionOf("England", "GB-ENG")).toBe("europa");
    expect(regionOf("Kazakhstan", "KZ")).toBe("europa");
    expect(regionOf("Australia", "AU")).toBe("asia");
    expect(regionOf("World", null)).toBe("internacional");
    expect(regionOf("Atlantis", "QQ")).toBe("otras");
  });

  test("featured is P0 or P1; a competition without priority is not", () => {
    const by = new Map(ENTRIES.map((e) => [e.id, e]));
    expect(by.get(1)?.featured).toBe(true);
    expect(by.get(6)?.featured).toBe(true);
    expect(by.get(4)?.featured).toBe(false);
    expect(by.get(3)?.priority).toBeNull();
  });

  test("grouped by region in the lámina's order, featured first, then the deeper level", () => {
    const groups = byRegion(ENTRIES);
    expect(groups.map((g) => g.region)).toEqual([
      "sudamerica",
      "europa",
      "asia",
      "africa",
      "internacional",
    ]);
    expect(groups[0]?.entries.map((e) => e.id)).toEqual([1, 2, 3]);
    expect(groups[0]?.withA).toBe(1);
    expect(countryCount(ENTRIES)).toBe(5);
  });

  test("filters: search without accents and by country, level, featured, mine", () => {
    const none = new Set<number>();
    expect(
      filterEntries(ENTRIES, { ...NO_FILTER, query: "division" }, none).map((e) => e.id),
    ).toEqual([5]);
    expect(filterEntries(ENTRIES, { ...NO_FILTER, query: "colombia" }, none)).toHaveLength(3);
    expect(filterEntries(ENTRIES, { ...NO_FILTER, level: "C" }, none).map((e) => e.id)).toEqual([
      7, 8,
    ]);
    expect(filterEntries(ENTRIES, { ...NO_FILTER, featured: true }, none).map((e) => e.id)).toEqual(
      [1, 2, 6],
    );
    expect(
      filterEntries(ENTRIES, { ...NO_FILTER, mine: true }, new Set([4])).map((e) => e.id),
    ).toEqual([4]);
    expect(levelCounts(ENTRIES)).toEqual({ all: 8, A: 3, B: 2, C: 2, D: 1, MI: 0 });
  });
});

describe("the directory's page", () => {
  test("lists every competition with its level, the featured mark and the two signals explained", async () => {
    const out = await html(<DirectoryView entries={ENTRIES} mine={new Set()} page />);
    expect(out).toContain("8 competiciones seguidas en 5 países");
    expect(out.match(/data-testid="directory-row"/g)).toHaveLength(8);
    expect(out).toContain('href="/competitions/1"');
    expect(out).toContain("Destacada");
    expect(out).toContain("no cuántos datos hay");
    expect(out).toContain("no la calidad de la liga");
    expect(out).toContain("Sudamérica");
    expect(out).toContain("Torneos internacionales");
    expect(out).toContain('aria-pressed="true"');
    expect(out).toContain("Nivel A: cobertura completa");
    expect(out).not.toContain("Las que sigo");
  });

  test("with the competition's page closed a row leads to its matches", async () => {
    const out = await html(<DirectoryView entries={ENTRIES} mine={new Set([1])} page={false} />);
    expect(out).toContain('href="/matches?competition=1"');
    expect(out).toContain("Las que sigo");
  });
});
