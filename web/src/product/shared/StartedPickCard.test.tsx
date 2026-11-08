/// <reference types="bun" />
/**
 * «Estado actual» of a pre-match pick whose match has kicked off (plan PICKS, U4): never empty. Before the whistle - the
 * provider still says «NS» in the 15 minutes of grace - it reads «Esperando el inicio»; with a code nobody knows it reads
 * «Sin estado», not a guess; in play it is the match's own badge; once settled, the result.
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
import type { StartedPick } from "@/lib/api/v1/types_product";
import { StartedPickCard } from "./StartedPickCard";

afterAll(() => setLocale("es"));

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

const KICKOFF = new Date(Date.now() - 5 * 60_000).toISOString();

function pick(over: Partial<StartedPick>): StartedPick {
  return {
    pick_id: 1,
    fixture_id: 10,
    kickoff_at: KICKOFF,
    competition: { id: 1, name: "Liga Test", logo_url: null, flag_url: null, country: "Colombia" },
    home: { id: 1, name: "Local", logo_url: null },
    away: { id: 2, name: "Visitante", logo_url: null },
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
    phase: "scheduled",
    status_short: "NS",
    live_minute: null,
    live_extra: null,
    live_home: null,
    live_away: null,
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

/** The text of the element with this test id, or null when there is none. */
function textOf(out: string, testId: string): string | null {
  const m = new RegExp(`data-testid="${testId}"[^>]*>([^<]*)<`).exec(out);
  return m ? (m[1] ?? "") : null;
}

describe("«Estado actual» is never empty (plan PICKS, U4)", () => {
  test("before the whistle it waits for the kick-off", async () => {
    const out = await html(
      <StartedPickCard pick={pick({ phase: "scheduled", status_short: "NS" })} />,
    );
    expect(textOf(out, "started-pick-quiet")).toBe("Esperando el inicio");
    expect(out).not.toContain('data-testid="match-state"');
  });

  test("with a code nobody knows it says so instead of guessing", async () => {
    const out = await html(
      <StartedPickCard pick={pick({ phase: "unknown", status_short: "XYZ" })} />,
    );
    expect(textOf(out, "started-pick-quiet")).toBe("Sin estado");
    expect(out).not.toContain("Esperando el inicio");
  });

  test("in play it is the match's own badge, and once settled the result", async () => {
    const live = await html(
      <StartedPickCard
        pick={pick({
          phase: "live",
          status_short: "1H",
          live_minute: 12,
          live_home: 1,
          live_away: 0,
        })}
      />,
    );
    expect(textOf(live, "started-pick-quiet")).toBeNull();
    expect(live).toContain('data-testid="match-state"');
    const settled = await html(
      <StartedPickCard
        pick={pick({ phase: "finished", result_status: "win", profit_units: "1.10" })}
      />,
    );
    expect(textOf(settled, "started-pick-quiet")).toBeNull();
    expect(settled).not.toContain('data-testid="match-state"');
  });

  test("in English too", async () => {
    setLocale("en");
    try {
      const out = await html(<StartedPickCard pick={pick({ phase: "scheduled" })} />);
      expect(textOf(out, "started-pick-quiet")).toBe("Waiting for kick-off");
      const unknown = await html(<StartedPickCard pick={pick({ phase: "unknown" })} />);
      expect(textOf(unknown, "started-pick-quiet")).toBe("No status");
    } finally {
      setLocale("es");
    }
  });
});
