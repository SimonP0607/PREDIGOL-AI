/// <reference types="bun" />
/**
 * The readers' global search (UX-153): grouping in the maqueta's order, honest kick-off reading, where a hit leads, the
 * recents kept on this device only, and the keys that open it.
 */
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import type { SearchHit } from "@/lib/api/v1/types";
import {
  cleanQuery,
  groupHits,
  hitKickoff,
  hitLink,
  MAX_RECENT,
  opensSearch,
  pushRecent,
  readRecent,
  RECENT_KEY,
  writeRecent,
} from "./model";
import { SearchButton } from "./SearchButton";

setLocale("es");

const hits: SearchHit[] = [
  { type: "fixture", id: 9, label: "Millonarios v Santa Fe", sublabel: "2026-11-20 01:30 UTC" },
  { type: "competition", id: 3, label: "Liga BetPlay", sublabel: "Colombia" },
  { type: "team", id: 7, label: "Millonarios", sublabel: "Colombia" },
];

function memory(seed: Record<string, string> = {}) {
  const m = new Map(Object.entries(seed));
  return {
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => void m.set(k, v),
    removeItem: (k: string) => void m.delete(k),
    m,
  };
}

describe("the answer", () => {
  test("grouped as the maqueta: teams, competitions, matches; empty groups are not drawn", () => {
    expect(groupHits(hits).map((g) => g.group)).toEqual(["team", "competition", "fixture"]);
    expect(groupHits([hits[1]!]).map((g) => g.group)).toEqual(["competition"]);
    expect(groupHits([])).toEqual([]);
  });

  test("the kick-off is read as an instant, or not at all", () => {
    expect(hitKickoff("2026-11-20 01:30 UTC")).toBe("2026-11-20T01:30:00Z");
    expect(hitKickoff("Colombia")).toBeNull();
    expect(hitKickoff("2026-11-20 01:30")).toBeNull();
  });

  test("where a hit leads: the match, the competition's matches, the team's matches (profiles come later)", () => {
    expect(hitLink(hits[0]!)).toEqual({ to: "/matches/$fixtureId", params: { fixtureId: "9" } });
    expect(hitLink(hits[1]!)).toEqual({ to: "/matches", search: { competition: 3 } });
    expect(hitLink(hits[2]!)).toEqual({ to: "/matches", search: { q: "Millonarios" } });
    // with the profiles open (UX-154), a team opens its profile
    expect(hitLink(hits[2]!, true)).toEqual({ to: "/teams/$teamId", params: { teamId: "7" } });
  });

  test("the query: spaces folded, at most 60 characters", () => {
    expect(cleanQuery("  real   madrid ")).toBe("real madrid");
    expect(cleanQuery("x".repeat(90))).toHaveLength(60);
  });
});

describe("recent searches, on this device only", () => {
  test("newest first, never twice, at most six", () => {
    let list = pushRecent([], hits[0]!);
    list = pushRecent(list, hits[2]!);
    list = pushRecent(list, hits[0]!);
    expect(list.map((r) => r.id)).toEqual([9, 7]);
    for (let i = 0; i < 10; i++) list = pushRecent(list, { ...hits[2]!, id: 100 + i });
    expect(list).toHaveLength(MAX_RECENT);
  });

  test("written and read back; a damaged or blocked store is an empty list", () => {
    const store = memory();
    writeRecent(store, [hits[2]!]);
    expect(readRecent(store)).toEqual([hits[2]!]);
    writeRecent(store, []);
    expect(store.m.has(RECENT_KEY)).toBe(false);
    expect(readRecent(memory({ [RECENT_KEY]: "{not json" }))).toEqual([]);
    expect(readRecent(memory({ [RECENT_KEY]: JSON.stringify([{ type: "x", id: 1 }]) }))).toEqual(
      [],
    );
    const broken = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
      removeItem: () => undefined,
    };
    expect(readRecent(broken)).toEqual([]);
    expect(() => writeRecent(broken, [hits[0]!])).not.toThrow();
    expect(readRecent(null)).toEqual([]);
  });
});

describe("the door", () => {
  test("«/» outside a field and Ctrl/⌘ K anywhere open it", () => {
    const k = (key: string, mod: Partial<KeyboardEvent> = {}) => ({
      key,
      metaKey: false,
      ctrlKey: false,
      altKey: false,
      ...mod,
    });
    expect(opensSearch(k("/"), false)).toBe(true);
    expect(opensSearch(k("/"), true)).toBe(false);
    expect(opensSearch(k("k", { ctrlKey: true }), true)).toBe(true);
    expect(opensSearch(k("K", { metaKey: true }), false)).toBe(true);
    expect(opensSearch(k("k"), false)).toBe(false);
    expect(opensSearch(k("k", { ctrlKey: true, altKey: true }), false)).toBe(false);
  });

  test("a 44 px button with a name and its keys; the layer is not loaded until it is used", () => {
    const html = renderToStaticMarkup(<SearchButton />);
    expect(html).toContain('data-testid="search-open"');
    expect(html).toContain('aria-label="Buscar"');
    expect(html).toContain('aria-keyshortcuts="/ Control+K Meta+K"');
    expect(html).toContain("h-11 w-11");
    expect(html).not.toContain("reader-search");
  });
});
