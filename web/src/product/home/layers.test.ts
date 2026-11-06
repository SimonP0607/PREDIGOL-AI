/// <reference types="bun" />
/**
 * Inicio's two layers (closing plan 3.2): «Para ti» only once the reader chose a league, a team, a player or a market, and the
 * leagues the product suggests until then never count as theirs; the prompt to choose waits for /me/today so a reader with
 * favourites is never asked to choose them.
 */
import { describe, expect, test } from "bun:test";
import type { MeToday } from "@/lib/api/v1/types_me_today";
import type { Following, Today } from "@/lib/api/v1/types_today";
import { layersOf } from "./layers";

const me = (over: Partial<MeToday> = {}): MeToday => ({
  personalization: true,
  chosen: false,
  players: [],
  markets: [],
  picks: null,
  notices: null,
  ...over,
});

function board(following: Partial<Following> | null): Today {
  return {
    day: "2026-11-05",
    suggested: [],
    suggested_team: null,
    matches: { status: "empty", data: [], reason: null },
    no_pick: { status: "ok", data: null, reason: null },
    ...(following === null
      ? {}
      : {
          following: {
            suggested: false,
            personalization: true,
            leagues: [],
            teams: [],
            next: [],
            ...following,
          },
        }),
  } as unknown as Today;
}

describe("layersOf", () => {
  test("a reader with no favourites: the PrediGol layer alone and the discreet prompt", () => {
    expect(layersOf(me(), board({ suggested: true }))).toEqual({
      forYou: false,
      mine: false,
      prompt: true,
    });
  });

  test("leagues or teams of their own: «Para ti» holds the board's blocks", () => {
    expect(layersOf(me({ chosen: true }), board({}))).toEqual({
      forYou: true,
      mine: true,
      prompt: false,
    });
  });

  test("a player or a market alone makes «Para ti» - the board's blocks stay the suggested ones, in PrediGol", () => {
    expect(layersOf(me({ chosen: true, markets: ["OU"] }), board({ suggested: true }))).toEqual({
      forYou: true,
      mine: false,
      prompt: false,
    });
  });

  test("while /me/today loads: the board's word stands in, and the prompt waits", () => {
    expect(layersOf(undefined, board({}))).toEqual({ forYou: true, mine: true, prompt: false });
    expect(layersOf(undefined, board({ suggested: true }))).toEqual({
      forYou: false,
      mine: false,
      prompt: false,
    });
    expect(layersOf(undefined, undefined)).toEqual({ forYou: false, mine: false, prompt: false });
  });

  test("an API without the board's own part is the suggested view", () => {
    expect(layersOf(me(), board(null)).mine).toBe(false);
  });

  test("personalisation off: the common view - no «Para ti» and no way to choose", () => {
    expect(layersOf(me({ personalization: false }), board({ suggested: true }))).toEqual({
      forYou: false,
      mine: false,
      prompt: false,
    });
  });

  test("an account /me/today says has chosen nothing (the owner's) never gets «Para ti», whatever the board says", () => {
    expect(layersOf(me({ chosen: false }), board({}))).toEqual({
      forYou: false,
      mine: false,
      prompt: true,
    });
  });
});
