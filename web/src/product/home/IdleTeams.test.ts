/// <reference types="bun" />
/** AP-B06: the followed teams with no match we follow are named, in the reader's order; no one else sees the note. */
import { describe, expect, test } from "bun:test";
import type { FavoritesView } from "@/lib/api/v1/types_favorites";
import { idleTeamNames } from "@/product/favorites/follow";

const team = (id: number, name: string) => ({ id, name, logo_url: null });
const view = (over: Partial<FavoritesView> = {}): FavoritesView => ({
  leagues: [],
  teams: [team(1, "Santa Fe"), team(2, "Club Lejano"), team(3, "Sin Partidos FC")],
  players: [],
  markets: [],
  suggested: false,
  max_leagues: 10,
  max_teams: 20,
  max_players: 20,
  max_markets: 7,
  personalization: true,
  idle_teams: [3, 2],
  ...over,
});

describe("the followed teams with no match we follow (AP-B06)", () => {
  test("named in the order the reader chose them, not the order the server lists them", () => {
    expect(idleTeamNames(view())).toEqual(["Club Lejano", "Sin Partidos FC"]);
  });
  test("nothing for the suggested teams, with personalisation off, or from an older API", () => {
    expect(idleTeamNames(view({ suggested: true }))).toEqual([]);
    expect(idleTeamNames(view({ personalization: false }))).toEqual([]);
    const { idle_teams: _gone, ...older } = view();
    expect(idleTeamNames(older)).toEqual([]);
    expect(idleTeamNames(null)).toEqual([]);
    expect(idleTeamNames(undefined)).toEqual([]);
  });
});
