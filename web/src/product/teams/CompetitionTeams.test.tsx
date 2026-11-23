/// <reference types="bun" />
/** AP-E01: Equipos → league → its teams → profile; no click of the page leads to Partidos. */
import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import type { CompetitionSummary, TeamSummary } from "@/lib/api/v1/types";
import { LeagueRow, TeamGrid } from "./CompetitionTeams";

async function html(node: ReactNode): Promise<string> {
  const router = createRouter({
    routeTree: createRootRoute({ component: () => <>{node}</> }),
    history: createMemoryHistory({ initialEntries: ["/teams"] }),
  });
  await router.load();
  return renderToStaticMarkup(<RouterProvider router={router} />);
}

const team = (id: number, name: string, country: string | null): TeamSummary => ({
  id,
  provider_team_id: id,
  name,
  country,
  fixtures: 0,
  results: 0,
  logo_url: null,
});

const LEAGUE = {
  id: 7,
  name: "Primera A",
  country: "Colombia",
  is_tracked: true,
} as CompetitionSummary;

describe("the teams of a league", () => {
  test("each team opens its profile - a national side its own - in alphabetical order", async () => {
    const markup = await html(
      <TeamGrid
        teams={[
          team(3, "Millonarios", "Colombia"),
          team(1, "Atlético Nacional", "Colombia"),
          team(9, "Colombia", "Colombia"),
        ]}
      />,
    );
    expect(markup).toContain('href="/teams/1"');
    expect(markup).toContain('href="/teams/3"');
    expect(markup).toContain('href="/nations/9"');
    expect(markup).not.toContain("/matches");
    expect(markup.indexOf("Atlético Nacional")).toBeLessThan(markup.indexOf("Millonarios"));
    expect(markup).toContain("grid-cols-2");
    expect(markup).toContain("@[64rem]:grid-cols-6");
  });

  test("a closed league is a native disclosure: its name, no teams fetched yet", async () => {
    const markup = await html(
      <ul>
        <LeagueRow competition={LEAGUE} competitionPage />
      </ul>,
    );
    expect(markup).toContain("<details");
    expect(markup).toContain("Primera A");
    expect(markup).not.toContain('data-testid="league-panel"');
    expect(markup).not.toContain("/matches");
  });

  test("no file of Equipos links to Partidos", () => {
    for (const file of ["TeamsPage.tsx", "CompetitionTeams.tsx"]) {
      const source = readFileSync(new URL(`./${file}`, import.meta.url), "utf8");
      expect(source, file).not.toMatch(/to:\s*"\/matches"|to="\/matches"/);
    }
  });
});
