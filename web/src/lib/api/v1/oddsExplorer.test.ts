/// <reference types="bun" />
import { afterEach, describe, expect, test } from "bun:test";
import { v1 } from "./client";
import {
  live,
  useAdminOddsHealth,
  useMatchOddsBook,
  useOddsBoard,
  useOddsFamilies,
  useOddsMovement,
} from "./queries";
import type { OddsBoardPage } from "./types_odds_explorer";
import type { Envelope } from "./types";

const realFetch = globalThis.fetch;
const scope = globalThis as { window?: unknown };
let asked: string[] = [];

afterEach(() => {
  globalThis.fetch = realFetch;
  delete scope.window;
  asked = [];
});

/** The page's own origin and a server that answers every GET with `body`, remembering the URLs asked. */
function serve(body: unknown): void {
  scope.window = { location: { origin: "https://predigol.test" }, dispatchEvent: () => true };
  globalThis.fetch = (async (url: URL | string) => {
    asked.push(String(url));
    return new Response(JSON.stringify(body), { status: 200 });
  }) as unknown as typeof fetch;
}

function page(cursor: string | null): Envelope<OddsBoardPage> {
  return {
    status: "ok",
    reason: null,
    meta: {} as Envelope<OddsBoardPage>["meta"],
    data: {
      market: {
        key: "result.1x2",
        family: "result",
        kind: "plain",
        subject: "match",
        periods: ["FT"],
        has_line: false,
        fair: true,
        parlay: true,
        fixtures: 3,
        max_books: 10,
      },
      period: "FT",
      rows: [],
      total: 3,
      next_cursor: cursor,
      competitions: [],
      bookmakers: [],
      generated_at: "2026-11-08T12:00:00Z",
    },
  };
}

describe("the odds explorer's client (BE-011)", () => {
  test("each function asks its own route with the parameters given and nothing else", async () => {
    serve(page(null));
    await v1.oddsFamilies({ hours: 48, country: "Italy" });
    await v1.oddsBoard({
      market: "goals.total",
      line: "2.5",
      fair_only: true,
      sort: "edge",
      cursor: "abc",
      q: undefined,
    });
    await v1.matchOddsBook(7, { family: "corners" });
    await v1.matchOddsBook(7);
    await v1.oddsMovement(7, { market: "result.asian_handicap", line: "-0.5" });
    await v1.adminOddsHealth();
    expect(asked).toEqual([
      "https://predigol.test/api/v1/odds/families?hours=48&country=Italy",
      "https://predigol.test/api/v1/odds/board?market=goals.total&line=2.5&fair_only=true&sort=edge&cursor=abc",
      "https://predigol.test/api/v1/matches/7/odds-book?family=corners",
      "https://predigol.test/api/v1/matches/7/odds-book",
      "https://predigol.test/api/v1/odds/fixtures/7/movement?market=result.asian_handicap&line=-0.5",
      "https://predigol.test/api/v1/admin/odds/health",
    ]);
  });
});

describe("the odds explorer's queries (BE-011)", () => {
  test("every parameter set is its own cache entry", () => {
    const keys = [
      live.oddsFamilies({ hours: 24 }).queryKey,
      live.oddsFamilies({ hours: 48 }).queryKey,
      live.oddsBoardPages({ market: "result.1x2" }).queryKey,
      live.oddsBoardPages({ market: "result.1x2", q: "juve" }).queryKey,
      live.matchOddsBook(7).queryKey,
      live.matchOddsBook(7, "corners").queryKey,
      live.oddsMovement(7, { market: "result.1x2" }).queryKey,
      live.oddsMovement(7, { market: "goals.total", line: "2.5" }).queryKey,
      live.adminOddsHealth.queryKey,
    ];
    expect(new Set(keys.map((k) => JSON.stringify(k))).size).toBe(keys.length);
    expect(live.matchOddsBook("7").queryKey).toEqual(live.matchOddsBook(7).queryKey);
  });

  test("the board reads page after page from the page's own cursor", async () => {
    const options = live.oddsBoardPages({ market: "result.1x2", sort: "competition" });
    expect(options.initialPageParam).toBeUndefined();
    expect(options.getNextPageParam(page("next-1"), [], undefined, [])).toBe("next-1");
    expect(options.getNextPageParam(page(null), [], undefined, [])).toBeUndefined();
    serve(page(null));
    const fn = options.queryFn as unknown as (ctx: {
      pageParam: string | undefined;
    }) => Promise<unknown>;
    await fn({ pageParam: "next-1" });
    expect(asked).toEqual([
      "https://predigol.test/api/v1/odds/board?market=result.1x2&sort=competition&cursor=next-1",
    ]);
  });

  test("the server keeps each answer a minute (the movement five) and nothing is polled", () => {
    const all = [
      live.oddsFamilies(),
      live.oddsBoardPages({ market: "result.1x2" }),
      live.matchOddsBook(7),
      live.adminOddsHealth,
    ] as Record<string, unknown>[];
    for (const options of all) {
      expect(options["staleTime"]).toBe(60_000);
      expect(options["refetchInterval"]).toBeUndefined();
    }
    expect(
      (live.oddsMovement(7, { market: "result.1x2" }) as Record<string, unknown>)["staleTime"],
    ).toBe(300_000);
  });

  test("the hooks the explorer reads through exist under their contract names", () => {
    for (const hook of [
      useOddsFamilies,
      useOddsBoard,
      useMatchOddsBook,
      useOddsMovement,
      useAdminOddsHealth,
    ]) {
      expect(typeof hook).toBe("function");
    }
  });
});
