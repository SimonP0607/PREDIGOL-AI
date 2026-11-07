/// <reference types="bun" />
/**
 * The day's picks that are the reader's (closing plan 3.2): the API names each by its rank and its match; the card is the one the
 * day's set already shows. A pick the set no longer has under that rank and match is left out - never made up, never another's.
 */
import { describe, expect, test } from "bun:test";
import type { RelatedPick, RelatedPicks } from "@/lib/api/v1/types_me_today";
import type { DailyItem } from "@/lib/api/v1/types_records";
import { mineByRank, mineReasons, pickAnchor, relatedCards } from "./related";

const card = (rank: number, fixture: number): DailyItem =>
  ({ rank, match: { fixture_id: fixture } }) as unknown as DailyItem;
const pick = (rank: number, fixture: number, over: Partial<RelatedPick> = {}): RelatedPick => ({
  rank,
  fixture_id: fixture,
  market_key: "1X2",
  followed: null,
  market_followed: false,
  ...over,
});
const picks = (items: RelatedPick[], published = 3): RelatedPicks => ({
  day: "2026-11-05",
  published,
  items,
});

describe("relatedCards", () => {
  const set = [card(1, 100), card(2, 101), card(3, 102)];

  test("each related pick with its card, in the set's order", () => {
    const got = relatedCards(picks([pick(1, 100), pick(3, 102)]), set);
    expect(got.map((c) => [c.related.rank, c.item.match.fixture_id])).toEqual([
      [1, 100],
      [3, 102],
    ]);
    expect(got[0]?.item).toBe(set[0]);
  });

  test("a card the set no longer has under that rank and match is left out", () => {
    expect(relatedCards(picks([pick(4, 103)]), set)).toEqual([]);
    expect(relatedCards(picks([pick(2, 999)]), set)).toEqual([]);
    expect(
      relatedCards(picks([pick(1, 100), pick(2, 999)]), set).map((c) => c.related.rank),
    ).toEqual([1]);
  });

  test("nothing related, or no set yet: nothing", () => {
    expect(relatedCards(picks([]), set)).toEqual([]);
    expect(relatedCards(picks([pick(1, 100)]), [])).toEqual([]);
  });
});

describe("why a pick is the reader's", () => {
  test("team, player, league, market - in that order, each with what it names", () => {
    const all = pick(1, 100, {
      followed: { kind: "team", names: ["Nacional"] },
      players: ["Jugador Uno"],
      market_followed: true,
    });
    expect(mineReasons(all, "1X2")).toEqual([
      { kind: "team", names: ["Nacional"] },
      { kind: "player", names: ["Jugador Uno"] },
      { kind: "market", names: ["1X2"] },
    ]);
    const league = pick(2, 101, { followed: { kind: "league", names: ["Liga BetPlay"] } });
    expect(mineReasons(league, "1X2")).toEqual([{ kind: "league", names: ["Liga BetPlay"] }]);
  });

  test("an API from before the players says nothing of them; a pick with no reason has none", () => {
    expect(mineReasons(pick(1, 100), "1X2")).toEqual([]);
    expect(mineReasons(pick(1, 100, { market_followed: true }), "OU")).toEqual([
      { kind: "market", names: ["OU"] },
    ]);
  });

  test("by rank, and an anchor per pick", () => {
    const map = mineByRank(picks([pick(2, 101), pick(5, 104)]));
    expect([...map.keys()]).toEqual([2, 5]);
    expect(mineByRank(null).size).toBe(0);
    expect(pickAnchor(3)).toBe("pick-3");
  });
});
