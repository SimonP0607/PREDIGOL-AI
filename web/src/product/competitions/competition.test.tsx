/// <reference types="bun" />
/**
 * Plan PM, PM-09-04 (UX-178): a competition's page shows each tab by the level of its own data in C-16 - at level A tables,
 * calendar, leaders and coverage; at level C the same with the partial level said; at level D only the calendar and the results,
 * saying once what it does not offer - and draws the season tables computed from the regulation (BE-082) with their zones, places
 * and the honesty notes (provisional, decisions not verified, «no es un pronóstico»).
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
import type {
  CompetitionAvailability,
  CoverageFamily,
  CoverageLevel,
} from "@/lib/api/v1/types_availability";
import type { CompetitionReference } from "@/lib/api/v1/types_center";
import type { SeasonTables } from "@/lib/api/v1/types_season_tables";
import { CoverageTab, LeadersTab, competitionKind } from "./CompetitionPage";
import { chosenTab, competitionModules, familyLevel } from "./model";
import { SeasonTablesBlock, tableViews } from "./SeasonTables";

afterAll(() => setLocale("es"));

async function html(node: ReactNode): Promise<string> {
  const router = createRouter({
    routeTree: createRootRoute({ component: () => node }),
    history: createMemoryHistory({ initialEntries: ["/competitions/16"] }),
  });
  await router.load();
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

const FAMILIES: CoverageFamily[] = [
  "base",
  "team_stats",
  "xg",
  "player_stats",
  "referee",
  "main_odds",
  "stat_odds",
];

function competition(level: CoverageLevel, base: CoverageLevel = level): CompetitionAvailability {
  return {
    competition_id: 16,
    name: "Liga Ejemplo",
    country: "Colombia",
    tier: 1,
    summary: level,
    summary_label: level,
    families: FAMILIES.map((f) => ({ family: f, level: f === "base" ? base : level })),
    seasons: [],
  };
}

describe("the tabs follow the level of their own data", () => {
  const has = { table: true, leaders: true };

  test("level A: tables, matches, leaders and coverage", () => {
    const m = competitionModules(competition("A"), has);
    expect(m.tabs).toEqual(["table", "calendar", "leaders", "coverage"]);
    expect(m.notOffered).toEqual([]);
    expect(m.level).toBe("A");
  });

  test("level C (base B): the same tabs; the summary is only the header's", () => {
    const m = competitionModules(competition("C", "B"), has);
    expect(m.tabs).toEqual(["table", "calendar", "leaders", "coverage"]);
    expect(m.level).toBe("C");
  });

  test("level D: only the calendar and the results, and what it does not offer said once", () => {
    const m = competitionModules(competition("D"), has);
    expect(m.tabs).toEqual(["calendar", "coverage"]);
    expect(m.notOffered).toEqual(["table", "leaders"]);
    expect(chosenTab(undefined, m.tabs)).toBe("calendar");
    expect(chosenTab("table", m.tabs)).toBe("calendar");
  });

  test("the summary never decides: a summary D with its base data at B keeps the tables", () => {
    const m = competitionModules(competition("D", "B"), has);
    expect(m.tabs).toContain("table");
  });

  test("without C-16 (FBI_AVAILABILITY off) the page shows what the routes have, and no level", () => {
    const m = competitionModules(null, { table: false, leaders: true });
    expect(m.tabs).toEqual(["calendar", "leaders"]);
    expect(m.level).toBeNull();
    expect(familyLevel(null, "base")).toBeNull();
  });

  test("a cup is a cup, anything unknown reads as a league", () => {
    expect(competitionKind("cup")).toBe("cup");
    expect(competitionKind("whatever")).toBe("league");
  });
});

const TEAM = (id: number, name: string) => ({
  team_id: 100 + id,
  provider_team_id: id,
  name,
  logo_url: null,
});

const TABLES: SeasonTables = {
  contract: "season-tables",
  contract_version: "1.0.0",
  computed_by: "season-tables-v1",
  competition_id: 16,
  league_id: 239,
  season: 2026,
  rules_version: 2,
  rules_file: "239_primera_a_colombia/v2.yaml",
  rules_sha256: "a".repeat(64),
  points: { win: 3, draw: 1, loss: 0 },
  tables: [
    {
      key: "reclasificacion",
      name: "Tabla de reclasificación total 2026",
      kind: "aggregate",
      complete: false,
      pending_matches: 13,
      unverified_decisions: 1,
      tiebreakers: ["goal_difference", "goals_for"],
      counts: ["liga_i.*", "liga_ii.*"],
      rows: [
        { position: 1, team: TEAM(1, "Unión Caribe"), played: 39, points: 78 },
        { position: 2, team: TEAM(2, "Atl. Cordillera"), played: 39, points: 74 },
        { position: 3, team: TEAM(3, "Bahía Azul"), played: 39, points: 69 },
      ].map((r) => ({
        ...r,
        wins: 20,
        draws: 9,
        losses: 10,
        goals_for: 50,
        goals_against: 30,
        goal_difference: 20,
        average: null,
        average_3: null,
        average_3_cut: null,
        seasons: [],
        window: [],
        tie_scope: null,
        shared_with: [],
        decided_by: null,
        open_on: null,
      })),
      zones: [
        {
          kind: "continental",
          target: "CONMEBOL Libertadores 2027",
          positions: [1, 2],
          teams: [1, 2],
          state: "condicional",
          note: "art. 30",
        },
      ],
      places: [
        {
          competition: "CONMEBOL Libertadores 2027",
          article: "art. 30",
          slot: "Colombia 1",
          source: "champion",
          of: "liga_i",
          team: TEAM(2, "Atl. Cordillera"),
          position: null,
          state: "calculado",
          reason: null,
        },
        {
          competition: "CONMEBOL Libertadores 2027",
          article: "art. 30",
          slot: "Colombia 2",
          source: "champion",
          of: "liga_ii",
          team: null,
          position: null,
          state: "pendiente",
          reason: "the champion of liga_ii is not known",
        },
      ],
      rounding: {},
      note: null,
    },
    {
      key: "descenso",
      name: "Tabla de descenso 2026 (promedio)",
      kind: "average",
      complete: true,
      pending_matches: 0,
      unverified_decisions: 0,
      tiebreakers: ["points", "goal_difference"],
      counts: ["liga_i.fase_1", "liga_ii.fase_1"],
      rows: [
        {
          position: 1,
          team: TEAM(1, "Unión Caribe"),
          played: 116,
          points: 208,
          wins: null,
          draws: null,
          losses: null,
          goals_for: null,
          goals_against: null,
          goal_difference: null,
          average: "52/29",
          average_3: "1.793",
          average_3_cut: "1.793",
          seasons: [],
          window: [2024, 2025, 2026],
          tie_scope: null,
          shared_with: [],
          decided_by: "points",
          open_on: null,
        },
      ],
      zones: [
        {
          kind: "relegation",
          target: "Primera B 2027",
          positions: [1],
          teams: [1],
          state: "definitivo",
          note: "art. 34",
        },
      ],
      places: [],
      rounding: { "3_half_up": "igual" },
      note: null,
    },
  ],
  champions: [],
  remaining: [],
  unverified_decisions: 1,
  computed_at: "2026-11-20T18:00:00Z",
};

describe("the season tables computed from the regulation", () => {
  test("three views: the reclasificación, the average and the places", () => {
    expect(tableViews(TABLES).map((v) => v.key)).toEqual([
      "reclasificacion",
      "descenso",
      "reclasificacion:places",
    ]);
  });

  test("the reclasificación says it is provisional, what is not verified and that it is not a forecast", async () => {
    const out = await html(<SeasonTablesBlock data={TABLES} />);
    expect(out).toContain("Las tablas que deciden el año");
    expect(out).toContain("Unión Caribe");
    expect(out).toContain('href="/teams/101"');
    expect(out).toContain("faltan 13 partidos");
    expect(out).toContain("1 resultados decididos fuera de la cancha");
    expect(out).toContain("No es un pronóstico");
    expect(out).toContain("depende de los campeones");
  });

  test("the average shows the quotient cut to three decimals and the relegation zone", async () => {
    const out = await html(<SeasonTablesBlock data={TABLES} view="descenso" />);
    expect(out).toContain("1.793");
    expect(out).toContain("Descenso");
    expect(out).toContain("Tabla definitiva");
  });

  test("a place that depends on a champion not known yet is pending, never guessed", async () => {
    const out = await html(<SeasonTablesBlock data={TABLES} view="reclasificacion:places" />);
    expect(out).toContain("El campeón de liga_ii");
    expect(out).toContain("Pendiente");
    expect(out).toContain("Calculado");
  });
});

describe("leaders and coverage", () => {
  const reference: CompetitionReference = {
    competition_id: 16,
    season: 2026,
    leaders: {
      status: "ok",
      reason: null,
      data: [
        {
          kind: "topscorers",
          provenance: { source: "API-Football /players/topscorers" } as never,
          rows: [
            {
              rank: 1,
              provider_player_id: 9,
              player_id: 77,
              name: "N. Castaño",
              photo_url: null,
              team_id: 101,
              provider_team_id: 1,
              team: "Unión Caribe",
              team_logo: null,
              appearances: 16,
              minutes: 1300,
              goals: 12,
              assists: 3,
              penalties_scored: 1,
              yellow_cards: 2,
              yellowred_cards: 0,
              red_cards: 0,
              rating: null,
              unrated_matches: 0,
            },
          ],
        },
      ],
    },
    rounds: { status: "ok", reason: null, data: [] },
    rounds_provenance: null,
    current_rounds: [],
  };

  test("the scorers link to the player and say their source", async () => {
    const out = await html(<LeadersTab reference={reference} />);
    expect(out).toContain("N. Castaño");
    expect(out).toContain('href="/players/77"');
    expect(out).toContain(">12<");
    expect(out).toContain("Fuente: los líderes que publica el proveedor");
  });

  test("the coverage lists the seven families and says the level is not the league's quality", async () => {
    const out = await html(<CoverageTab availability={competition("C", "B")} />);
    expect(out).toContain("Eventos y alineaciones");
    expect(out).toContain("Cuotas de córners y tarjetas");
    expect(out).toContain("no la calidad de la liga");
    expect(out.match(/data-slot|Nivel [ABCD]/g)?.length ?? 0).toBeGreaterThan(0);
  });
});
