/// <reference types="bun" />
/**
 * The readers' global search (UX-153): grouping in the maqueta's order, honest kick-off reading, where a hit leads, the
 * recents kept on this device only, and the keys that open it.
 */
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import type { SearchHit } from "@/lib/api/v1/types";
import type { SearchV2 } from "@/lib/api/v1/types_search";
import {
  cleanQuery,
  entriesOfV2,
  groupHits,
  hitKickoff,
  hitLink,
  MAX_RECENT,
  opensSearch,
  pushRecent,
  readRecent,
  RECENT_KEY,
  suggestionsOfV2,
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

const group = <T,>(items: T[] = []) => ({
  items,
  missing_reason: items.length ? null : "sin_resultados",
});
const v2 = (over: Partial<SearchV2["groups"]> = {}, mean: string[] = []): SearchV2 => ({
  query: "atletico",
  normalized: "atletico",
  groups: {
    teams: group([{ kind: "team", id: 101, label: "Atlético Ejemplo", sublabel: "Ejemplandia" }]),
    national_teams: group([{ kind: "national_team", id: 5, label: "España", sublabel: "España" }]),
    players: group([
      { kind: "player", id: 301, label: "J. Atletiquez", sublabel: "Atlético Ejemplo" },
    ]),
    competitions: group([
      { kind: "competition", id: 3, label: "Liga BetPlay", sublabel: "Colombia" },
    ]),
    fixtures: group([
      {
        id: 901,
        label: "Atlético Ejemplo v Deportivo Ficticio",
        sublabel: "Liga Ficticia",
        kickoff_at: "2026-11-23T20:00:00Z",
      },
    ]),
    ...over,
  },
  did_you_mean: group(mean.map((text) => ({ text }))),
});

describe("the search v2 (C-10, AP-B07)", () => {
  test("teams, national teams, players, competitions and matches, in the maqueta's order", () => {
    const entries = entriesOfV2(v2(), { profiles: true });
    expect(groupHits(entries).map((g) => g.group)).toEqual([
      "team",
      "national_team",
      "player",
      "competition",
      "fixture",
    ]);
    // a match reads its kick-off the way the list always did
    const fixture = entries.find((e) => e.type === "fixture")!;
    expect(hitKickoff(fixture.sublabel)).toBe("2026-11-23T20:00:00Z");
  });

  test("a player is listed only with the profiles open; coaches, referees and stadiums never are", () => {
    expect(entriesOfV2(v2(), { profiles: false }).some((e) => e.type === "player")).toBe(false);
    // the contract also carries coaches, referees, stadiums and news: none is read, so none is drawn
    const full = v2();
    (full.groups as unknown as Record<string, unknown>)["venues"] = group([
      { kind: "venue", id: 9, label: "Estadio Ejemplo", sublabel: "Villaejemplo" },
    ]);
    (full.groups as unknown as Record<string, unknown>)["coaches"] = group([
      { kind: "coach", id: 8, label: "Entrenador Ejemplo", sublabel: "" },
    ]);
    const labels = entriesOfV2(full, { profiles: true }).map((e) => e.label);
    expect(labels).not.toContain("Estadio Ejemplo");
    expect(labels).not.toContain("Entrenador Ejemplo");
  });

  test("each hit leads to its own page; without the profiles, to the matches as before", () => {
    const [team, nation, player, competition, fixture] = groupHits(
      entriesOfV2(v2(), { profiles: true }),
    ).map((g) => g.hits[0]!);
    expect(hitLink(team!, true)).toEqual({ to: "/teams/$teamId", params: { teamId: "101" } });
    expect(hitLink(nation!, true)).toEqual({ to: "/nations/$teamId", params: { teamId: "5" } });
    expect(hitLink(player!, true)).toEqual({
      to: "/players/$playerId",
      params: { playerId: "301" },
    });
    expect(hitLink(competition!, true, true)).toEqual({
      to: "/competitions/$competitionId",
      params: { competitionId: "3" },
    });
    expect(hitLink(competition!, true, false)).toEqual({
      to: "/matches",
      search: { competition: 3 },
    });
    expect(hitLink(fixture!, true)).toEqual({
      to: "/matches/$fixtureId",
      params: { fixtureId: "901" },
    });
    expect(hitLink(nation!, false)).toEqual({ to: "/matches", search: { q: "España" } });
  });

  test("«¿Quisiste decir…?»: up to three close names, only from an answer that has them", () => {
    expect(suggestionsOfV2(v2({}, ["Deportivo Ficticio", "B", "C", "D"]))).toEqual([
      "Deportivo Ficticio",
      "B",
      "C",
    ]);
    expect(suggestionsOfV2(v2())).toEqual([]);
    expect(suggestionsOfV2(undefined)).toEqual([]);
  });

  test("the recents of before still read, and a new kind is kept", () => {
    const store = memory({ [RECENT_KEY]: JSON.stringify([hits[2]]) });
    expect(readRecent(store)).toEqual([hits[2]!]);
    const player = {
      type: "player" as const,
      id: 301,
      label: "J. Atletiquez",
      sublabel: "Atlético",
    };
    expect(pushRecent(readRecent(store), player).map((r) => r.type)).toEqual(["player", "team"]);
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
