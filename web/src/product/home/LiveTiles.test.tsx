/// <reference types="bun" />
/**
 * Mobile UX audit (October 2026), live states on Home: two tiles side by side on a phone squeezed the competition
 * into a column of single letters at 320 px and cut every team name ("New E…", "Americ…") up to 430 px. One tile a
 * row below 640 px, every name whole; and the state pill is the one /live shows (a shoot-out read "120'").
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
import { LiveTiles } from "./LiveTiles";

setLocale("es");

async function html(node: ReactNode): Promise<string> {
  const router = createRouter({
    routeTree: createRootRoute({ component: () => node }),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  await router.load();
  return renderToStaticMarkup(<RouterProvider router={router} />);
}

function m(fixture_id: number, status: string, elapsed: number | null): LiveMatch {
  return {
    fixture_id,
    kickoff_at: "2026-10-12T09:00:00Z",
    competition: "Major League Soccer",
    country: "USA",
    home: { id: 1, name: "New England Revolution", logo_url: null },
    away: { id: 2, name: "Borussia Mönchengladbach", logo_url: null },
    status,
    elapsed,
    extra: null,
    goals_home: 0,
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
  };
}

const tiles = (matches: LiveMatch[]) =>
  html(
    <LiveTiles
      section={{ status: "ok", data: matches, reason: null }}
      liveAt="2026-10-12T10:20:00Z"
    />,
  );

describe("Home's live tiles", () => {
  test("one tile a row on a phone, two from 640 px, three on a laptop", async () => {
    const out = await tiles([m(1, "2H", 67), m(2, "1H", 12)]);
    expect(out).toMatch(
      /<ul class="[^"]*\bgrid-cols-1\b[^"]*\bsm:grid-cols-2\b[^"]*\blg:grid-cols-3\b/,
    );
  });

  test("every team name whole: it wraps, it is never truncated", async () => {
    const out = await tiles([m(1, "2H", 67)]);
    const names = [...out.matchAll(/<span[^>]*data-testid="team-name"[^>]*>([^<]+)</g)];
    expect(names.map((x) => x[1])).toEqual(["New England Revolution", "Borussia Mönchengladbach"]);
    for (const [tag] of names) {
      expect(tag).not.toContain("truncate");
      expect(tag).toContain("break-words");
    }
  });

  test("before kick-off a tile shows no score (the feed's 0-0) and the kick-off time", async () => {
    const out = (await tiles([m(1, "Not Started", 0)])).replace(/<[^>]+>/g, " ");
    expect(out).not.toMatch(/\b0\b/);
    expect(out).toContain("–");
  });

  test("the state pill says what is happening, as on /live", async () => {
    const label = async (status: string, elapsed: number | null) =>
      (await tiles([m(1, status, elapsed)])).replace(/<[^>]+>/g, " ").replace(/&#x27;/g, "'");
    expect(await label("2H", 67)).toContain("67'");
    expect(await label("HT", 45)).toContain("Descanso");
    expect(await label("Halftime", 45)).toContain("Descanso");
    expect(await label("P", 120)).toContain("Penales");
    expect(await label("P", 120)).not.toContain("120'");
    expect(await label("BT", 90)).toContain("Pausa");
    expect(await label("SUSP", 61)).toContain("Suspendido");
  });
});
