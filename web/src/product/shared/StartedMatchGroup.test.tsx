/// <reference types="bun" />
/**
 * «Ya empezaron» por partido (plan PICKS, F6 / L2): the teams, the competition and the score are said once per
 * match; every pick keeps its own card and its own result.
 */
import { describe, expect, test } from "bun:test";
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import type { StartedPick } from "@/lib/api/v1/types_product";
import { groupByMatch } from "@/product/picks/started";
import { StartedMatchGroupCard } from "./StartedMatchGroup";

async function html(node: ReactNode): Promise<string> {
  const router = createRouter({
    routeTree: createRootRoute({ component: () => node }),
    history: createMemoryHistory({ initialEntries: ["/picks"] }),
  });
  await router.load();
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

const KICKOFF = new Date(Date.now() - 60 * 60_000).toISOString();

function pick(over: Partial<StartedPick>): StartedPick {
  return {
    pick_id: 1,
    fixture_id: 10,
    kickoff_at: KICKOFF,
    competition: { id: 1, name: "Liga Test", logo_url: null, flag_url: null, country: "Colombia" },
    home: { id: 1, name: "Equipo Local", logo_url: null },
    away: { id: 2, name: "Equipo Visitante", logo_url: null },
    market_key: "1X2",
    selection: "Home",
    line: "0",
    status: "shadow",
    model: "dixon_coles",
    created_at: KICKOFF,
    taken_at: KICKOFF,
    odds_taken: "2.10",
    bookmaker: null,
    p_model: "0.52",
    p_market: "0.45",
    fair_odds: "2.22",
    edge: "0.07",
    ev: "0.09",
    evaluations: 1,
    phase: "live",
    status_short: "2H",
    live_minute: 60,
    live_extra: null,
    live_home: 2,
    live_away: 1,
    score_home: null,
    score_away: null,
    result_status: null,
    profit_units: null,
    settled_at: null,
    review_reason: null,
    near_close_odds: null,
    line_value: null,
    ...over,
  } as StartedPick;
}

describe("a match with its started picks", () => {
  const picks = [
    pick({ pick_id: 1, market_key: "1X2", selection: "Home" }),
    pick({ pick_id: 2, market_key: "OU", selection: "Over", line: "2.5" }),
    pick({ pick_id: 3, market_key: "BTTS", selection: "Yes", result_status: "win" }),
  ];

  test("says the teams once and keeps one card per pick", async () => {
    const [group] = groupByMatch(picks);
    if (!group) throw new Error("no group");
    const out = await html(<StartedMatchGroupCard group={group} />);
    expect(out.match(/data-testid="started-match"/g)).toHaveLength(1);
    expect(out.match(/data-testid="started-pick"/g)).toHaveLength(3);
    // The team names appear once as the match's (home and away), not once per pick.
    expect(out.match(/data-testid="team-name"/g)).toHaveLength(2);
    expect(out.match(/Liga Test/g)).toHaveLength(1);
    expect(out).toContain("3 picks en este partido");
  });

  test("each pick keeps its own result", async () => {
    const [group] = groupByMatch(picks);
    if (!group) throw new Error("no group");
    const out = await html(<StartedMatchGroupCard group={group} />);
    expect(out.match(/data-result="win"/g)).toHaveLength(1);
    expect(out.match(/data-result="open"/g)).toHaveLength(2);
  });

  test("a match with one pick says it in the singular", async () => {
    const [group] = groupByMatch([pick({})]);
    if (!group) throw new Error("no group");
    const out = await html(<StartedMatchGroupCard group={group} />);
    expect(out).toContain("1 pick en este partido");
  });
});
