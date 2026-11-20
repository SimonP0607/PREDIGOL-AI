/// <reference types="bun" />
/**
 * Plan PM, PM-09-03 (UX-181): the calculator lists the matches still to be played that the table on screen counts, with three
 * choices each (44 px, pressed state said), and carries its label: the reader's own calculation, not a forecast, no model, no
 * probability, no invented score. A table with nothing left to play shows no calculator.
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
import type { SeasonTable, SeasonTables } from "@/lib/api/v1/types_season_tables";
import { WhatIf } from "./WhatIf";

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

const team = (id: number, name: string) => ({
  team_id: 100 + id,
  provider_team_id: id,
  name,
  logo_url: null,
});

const row = (position: number, id: number, name: string, points: number) => ({
  position,
  team: team(id, name),
  played: 39,
  points,
  wins: null,
  draws: null,
  losses: null,
  goals_for: null,
  goals_against: null,
  goal_difference: null,
  average: null,
  average_3: null,
  average_3_cut: null,
  seasons: [],
  window: [],
  tie_scope: null,
  shared_with: [],
  decided_by: null,
  open_on: null,
});

const TABLE: SeasonTable = {
  key: "reclasificacion",
  name: "Reclasificación",
  kind: "aggregate",
  complete: false,
  pending_matches: 2,
  unverified_decisions: 0,
  tiebreakers: ["goal_difference"],
  counts: ["liga_i.*", "liga_ii.*"],
  rows: [
    row(1, 1, "Valle Verde", 64),
    row(2, 2, "Sporting Sabana", 62),
    row(3, 3, "Puerto Dorado", 58),
    row(4, 4, "Los Nevados", 57),
  ],
  zones: [
    {
      kind: "continental",
      target: "CONMEBOL Sudamericana 2027",
      positions: [1],
      teams: [1],
      state: "provisional",
      note: null,
    },
  ],
  places: [],
  rounding: {},
  note: null,
};

const DATA = (remaining: SeasonTables["remaining"]): SeasonTables => ({
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
  tables: [TABLE],
  champions: [],
  remaining,
  unverified_decisions: 0,
  computed_at: "2026-11-20T18:00:00Z",
});

const MATCH = {
  fixture_id: 9,
  provider_fixture_id: 99,
  round: "Clausura - Cuadrangulares - 6",
  kickoff_at: null,
  home: team(1, "Valle Verde"),
  away: team(3, "Puerto Dorado"),
  tables: ["reclasificacion"],
};

describe("the calculator", () => {
  test("lists the matches left with three choices and carries its label", async () => {
    const out = await html(<WhatIf data={DATA([MATCH])} table={TABLE} />);
    expect(out).toContain("¿Qué pasa si…?");
    expect(out).toContain("Valle Verde – Puerto Dorado");
    expect(out.match(/aria-pressed="false"/g)).toHaveLength(3);
    expect(out).toContain("min-h-11");
    expect(out).toContain("no un pronóstico");
    expect(out).toContain("nunca inventa marcadores");
    expect(out).not.toContain("Tu escenario");
    expect(out).not.toMatch(/%|probabilidad de|cuota/i);
  });

  test("a match that does not count in the table on screen is not offered", async () => {
    const out = await html(
      <WhatIf data={DATA([{ ...MATCH, tables: ["descenso"] }])} table={TABLE} />,
    );
    expect(out).toBe("");
  });
});
