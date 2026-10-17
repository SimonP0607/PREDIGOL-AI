/// <reference types="bun" />
/**
 * Mobile UX audit (October 2026), the Match Center's summary at 320 px: a team's name beside its five form chips
 * and in the two-row standings table was cut ("Zorya Luh…"). Both now wrap.
 */
import { describe, expect, test } from "bun:test";
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { setLocale } from "@/lib/i18n";
import type { StandingLine } from "@/lib/api/v1/types_center";
import type { MatchCtx } from "./context";
import { FormBlock, StandingsBlock } from "./ContextBlocks";

setLocale("es");

async function html(node: ReactNode): Promise<string> {
  const router = createRouter({
    routeTree: createRootRoute({ component: () => node }),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  await router.load();
  return renderToStaticMarkup(<RouterProvider router={router} />);
}

function line(side: "home" | "away", team: string, rank: number): StandingLine {
  return {
    side,
    team,
    rank,
    points: 20 - rank,
    played: 9,
    wins: 5,
    draws: 2,
    losses: 2,
    goals_for: 14,
    goals_against: 9,
    form: "WWDLW",
    group: null,
    snapshot_at: "2026-10-12T04:00:00Z",
    before_kickoff: true,
  };
}

// Only what the two blocks read: the teams, and the stored standings (their form letters feed the chips).
const ctx = {
  fixtureId: "21676",
  match: {
    id: 21676,
    home: { id: 1, name: "Livyi Bereh", logo_url: null },
    away: { id: 2, name: "Zorya Luhansk", logo_url: null },
    competition: { id: 177, name: "Premier League" },
  },
  center: {
    data: {
      form: { status: "empty", data: [], reason: null },
      standings: {
        status: "ok",
        data: [line("home", "Livyi Bereh", 7), line("away", "Zorya Luhansk", 3)],
        reason: null,
      },
      standings_tables: [],
    },
    loading: false,
    error: null,
    status: null,
    retry: () => {},
  },
  showAdmin: false,
  goTo: () => {},
} as unknown as MatchCtx;

function nameTags(out: string): string[] {
  return [...out.matchAll(/<span[^>]*data-testid="team-name"[^>]*>/g)].map((m) => m[0]);
}

describe("the Match Center's context blocks keep team names whole", () => {
  test("form: the name beside the five chips wraps", async () => {
    const out = await html(<FormBlock ctx={ctx} />);
    expect(out).toContain("Zorya Luhansk");
    const tags = nameTags(out);
    expect(tags.length).toBe(2);
    for (const tag of tags) expect(tag).not.toContain("truncate");
  });

  test("standings: the names in the fixed table wrap", async () => {
    const out = await html(<StandingsBlock ctx={ctx} />);
    expect(out).toContain("Livyi Bereh");
    const tags = nameTags(out);
    expect(tags.length).toBe(2);
    for (const tag of tags) expect(tag).not.toContain("truncate");
  });
});
