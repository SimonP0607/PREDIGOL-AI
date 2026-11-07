/// <reference types="bun" />
import { afterEach, describe, expect, mock, spyOn, test } from "bun:test";
import { v1 } from "./client";
import { live } from "./queries";
import { CATALOG_CATEGORIES, type MarketCatalog } from "./types_market_catalog";

const answer: MarketCatalog = {
  fixture_id: 7,
  kickoff_at: "2026-11-08T19:00:00Z",
  state: "priced",
  checked_at: "2026-11-08T09:00:00Z",
  newer_answer_pending: false,
  partial: false,
  category: "corners",
  categories: [{ key: "corners", markets: 1, selections: 2, bookmakers: 2 }],
  markets: [],
};

afterEach(() => {
  mock.restore();
});

describe("market catalogue query (F4a)", () => {
  test("the categories are the API's closed list, in the product's order", () => {
    expect([...CATALOG_CATEGORIES]).toEqual([
      "result",
      "goals",
      "goals_half",
      "corners",
      "cards",
      "shots",
    ]);
  });

  test("each category is its own cache entry, and the categories alone are another", () => {
    const keys = [undefined, ...CATALOG_CATEGORIES].map(
      (c) => live.matchMarketCatalog("7", c).queryKey,
    );
    expect(new Set(keys.map((k) => JSON.stringify(k))).size).toBe(keys.length);
    expect(live.matchMarketCatalog("7").queryKey).toEqual([
      "v1",
      "match-market-catalog",
      "7",
      "categories",
    ]);
  });

  test("it is read when a category opens, never polled", () => {
    const options = live.matchMarketCatalog("7", "corners") as Record<string, unknown>;
    expect(options["refetchInterval"]).toBeUndefined();
    expect(options["staleTime"]).toBe(60_000);
  });

  test("the query asks for the match and the category it names", async () => {
    const call = spyOn(v1, "matchMarketCatalog").mockResolvedValue({
      status: "ok",
      data: answer,
      reason: null,
      meta: {},
    } as unknown as Awaited<ReturnType<typeof v1.matchMarketCatalog>>);
    const got = await live.matchMarketCatalog("7", "corners").queryFn();
    expect(call).toHaveBeenCalledWith("7", "corners");
    expect(got.data.categories[0]?.key).toBe("corners");
  });
});
