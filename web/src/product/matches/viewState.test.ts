/// <reference types="bun" />
/**
 * The list's view in its URL (plan Partidos, P4): day, state, country, category, competition and search are read back
 * validated - what cannot be read is dropped, never an error -, written without what equals the default, and a copied
 * link reproduces the view. The folded competitions and «‹ Partidos» live in the tab.
 */
import { describe, expect, test } from "bun:test";
import { historyIndex, openedFromList, rememberOpened } from "./backToList";
import {
  hasFilters,
  isDay,
  parseMatchesSearch,
  readCollapsed,
  searchOf,
  viewOf,
  writeCollapsed,
  type MatchesView,
} from "./viewState";

const TODAY = "2026-11-07";

function withStorage<T>(run: (store: Map<string, string>) => T, state: unknown = null): T {
  const g = globalThis as { window?: unknown };
  const before = g.window;
  const store = new Map<string, string>();
  g.window = {
    sessionStorage: {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
    },
    history: { state },
  };
  try {
    return run(store);
  } finally {
    g.window = before;
  }
}

describe("the URL of the list", () => {
  test("every filter read back, validated", () => {
    expect(
      parseMatchesSearch({
        day: "2026-11-08",
        status: "live",
        country: "ES",
        category: "league",
        competition: 140,
        q: "betis",
      }),
    ).toEqual({
      day: "2026-11-08",
      status: "live",
      country: "ES",
      category: "league",
      competition: 140,
      q: "betis",
    });
  });

  test("what cannot be read is dropped, never an error", () => {
    expect(
      parseMatchesSearch({
        day: "2026-02-30",
        status: "soon",
        country: "",
        category: "beach",
        competition: "-3",
        q: "   ",
        s: "mercados",
      }),
    ).toEqual({});
    expect(parseMatchesSearch({ day: "mañana", competition: 1.5, status: "all" })).toEqual({});
    expect(parseMatchesSearch({ q: "x".repeat(200) }).q).toHaveLength(80);
  });

  test("the router's own parsing is undone: a number in the search is text, a competition in text is a number", () => {
    expect(parseMatchesSearch({ q: 1860, competition: "140", country: 7 })).toEqual({
      q: "1860",
      competition: 140,
      country: "7",
    });
  });

  test("a calendar day that exists", () => {
    expect(isDay("2026-11-07")).toBe(true);
    expect(isDay("2028-02-29")).toBe(true);
    expect(isDay("2026-02-29")).toBe(false);
    expect(isDay("2026-13-01")).toBe(false);
    expect(isDay("20261107")).toBe(false);
    expect(isDay(20261107)).toBe(false);
  });

  test("written without the defaults: a bare /matches is today, every state, nothing chosen", () => {
    const view: MatchesView = {
      day: TODAY,
      status: "all",
      competition: null,
      query: "  ",
      country: null,
      category: null,
      scope: "all",
    };
    expect(searchOf(view, TODAY)).toEqual({});
    expect(hasFilters(searchOf(view, TODAY))).toBe(false);
    expect(hasFilters({ status: "live" })).toBe(true);
  });

  test("a copied link reproduces the view (the scope stays in the tab)", () => {
    const view: MatchesView = {
      day: "2026-11-09",
      status: "upcoming",
      competition: 140,
      query: "betis",
      country: "ES",
      category: "league",
      scope: "mine",
    };
    const search = searchOf(view, TODAY);
    expect(search).toEqual({
      day: "2026-11-09",
      status: "upcoming",
      competition: 140,
      q: "betis",
      country: "ES",
      category: "league",
    });
    expect(parseMatchesSearch({ ...search })).toEqual(search);
    expect(viewOf(parseMatchesSearch({ ...search }), TODAY, "mine")).toEqual(view);
    expect(viewOf({}, TODAY, null)).toEqual({
      day: TODAY,
      status: "all",
      competition: null,
      query: "",
      country: null,
      category: null,
      scope: null,
    });
  });
});

describe("what the tab keeps", () => {
  test("the folded competitions", () => {
    withStorage((store) => {
      expect(readCollapsed().size).toBe(0);
      writeCollapsed(new Set([140, 2]));
      expect([...readCollapsed()].sort((a, b) => a - b)).toEqual([2, 140]);
      store.set("predigol.matches.collapsed", JSON.stringify([3, "x", 1.5, null]));
      expect([...readCollapsed()]).toEqual([3]);
      store.set("predigol.matches.collapsed", "{not json");
      expect(readCollapsed().size).toBe(0);
      writeCollapsed(new Set());
      expect(store.has("predigol.matches.collapsed")).toBe(false);
    });
  });

  test("«‹ Partidos» goes back only to the list this very match was opened from, one entry before", () => {
    withStorage(
      () => {
        expect(historyIndex()).toBe(4);
        expect(openedFromList(70, 5)).toBe(false);
        rememberOpened(70);
        expect(openedFromList(70, 5)).toBe(true);
        // another match, or the same one further on (a match opened from the first), or a shared link
        expect(openedFromList(71, 5)).toBe(false);
        expect(openedFromList(70, 6)).toBe(false);
        expect(openedFromList(70, 4)).toBe(false);
      },
      { __TSR_index: 4, key: "abc" },
    );
    withStorage(() => expect(historyIndex()).toBe(0), null);
  });
});
