/// <reference types="bun" />
/**
 * Mobile UX audit (October 2026), live states: on /live the "PrediGol · 2 picks" badge was laid over a compact row
 * (absolute, right) and covered the team names and the score on a phone. The count now sits under the minute, in
 * the row's own flow, and still says what it is to a screen reader.
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
import type { LiveMatch } from "@/lib/api/v1/types_center";
import { LiveRow } from "./LiveRow";

setLocale("es");

async function html(node: ReactNode): Promise<string> {
  const router = createRouter({
    routeTree: createRootRoute({ component: () => node }),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  await router.load();
  return renderToStaticMarkup(<RouterProvider router={router} />);
}

function liveMatch(over: Partial<LiveMatch> = {}): LiveMatch {
  return {
    fixture_id: 21141,
    kickoff_at: "2026-10-12T09:00:00Z",
    competition: "Super League",
    country: "China",
    home: { id: 1, name: "Chongqing Tongliang Long", logo_url: null },
    away: { id: 2, name: "Shandong Luneng", logo_url: null },
    status: "2H",
    elapsed: 78,
    extra: null,
    goals_home: 1,
    goals_away: 1,
    state_at: "2026-10-12T10:20:00Z",
    state_source: "fixture_feed",
    state_age_seconds: 25,
    odds_feed_at: null,
    markets_offered: null,
    values_suspended: null,
    events: [],
    statistics: [],
    main_odds: [],
    data_status: "ok",
    ...over,
  };
}

describe("a compact live row", () => {
  test("the picks count sits in the row's flow, under the minute - never laid over the names", async () => {
    const out = await html(<LiveRow m={liveMatch()} picks={2} />);
    const badge = /<span[^>]*data-testid="live-picks-badge"[^>]*>/.exec(out)?.[0] ?? "";
    expect(badge).not.toBe("");
    expect(badge).not.toMatch(/absolute|right-|translate/);
    // inside the row's link, after the minute and before the teams
    const link = /<a[^>]*data-testid="live-row"[\s\S]*<\/a>/.exec(out)?.[0] ?? "";
    expect(link.indexOf("78&#x27;")).toBeLessThan(link.indexOf("live-picks-badge"));
    expect(link.indexOf("live-picks-badge")).toBeLessThan(link.indexOf("Chongqing Tongliang Long"));
    expect(out).toContain("PrediGol · 2 picks");
  });

  test("no picks, no mark; the names are whole", async () => {
    const out = await html(<LiveRow m={liveMatch()} picks={0} />);
    expect(out).not.toContain("live-picks-badge");
    expect(out).toContain("Chongqing Tongliang Long");
    expect(out).toContain("Shandong Luneng");
  });
});
