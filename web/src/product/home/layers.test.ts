/// <reference types="bun" />
/**
 * Inicio's two layers (closing plan 3.2): «Para ti» only once the reader chose a league, a team, a player or a market, and the
 * leagues the product suggests until then never count as theirs; the prompt to choose waits for /me/today so a reader with
 * favourites is never asked to choose them.
 */
import { describe, expect, test } from "bun:test";
import type { MeToday } from "@/lib/api/v1/types_me_today";
import type { Following, Today } from "@/lib/api/v1/types_today";
import { holdsLayers, LAYERS_HOLD_MS, layersOf, shownLayers } from "./layers";

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

describe("holdsLayers", () => {
  const waiting = {
    reader: true,
    mePending: true,
    todayPending: true,
    homePending: true,
    boardPending: true,
    expired: false,
  };
  const answered = {
    ...waiting,
    mePending: false,
    todayPending: false,
    homePending: false,
    boardPending: false,
  };

  test("a reader whose page is not known yet is held: nothing of PrediGol is painted to be pushed down later", () => {
    expect(holdsLayers(waiting)).toBe(true);
  });

  test("any answer missing holds it: /today decides whose the board's blocks are, /me/today whether to ask for favourites", () => {
    expect(holdsLayers({ ...answered, mePending: true })).toBe(true);
    expect(holdsLayers({ ...answered, todayPending: true })).toBe(true);
  });

  test("the day's picks and the board hold it too: their skeletons are taller than their empty states, and what is under climbs", () => {
    expect(holdsLayers({ ...answered, boardPending: true })).toBe(true);
    expect(holdsLayers({ ...answered, homePending: true })).toBe(true);
  });

  test("all answered (or failed): the page is painted at once", () => {
    expect(holdsLayers(answered)).toBe(false);
  });

  test("never longer than the hold: a slow answer does not keep the page empty", () => {
    expect(holdsLayers({ ...waiting, expired: true })).toBe(false);
    expect(LAYERS_HOLD_MS).toBeGreaterThanOrEqual(1000);
    expect(LAYERS_HOLD_MS).toBeLessThanOrEqual(2000);
  });

  test("the owner is never held: no /me/today to wait for, the page paints as it always did", () => {
    expect(holdsLayers({ ...waiting, reader: false })).toBe(false);
    expect(holdsLayers({ ...waiting, reader: false, mePending: false })).toBe(false);
  });
});

describe("«Para ti / Todo» (plan maestro UX/UI 2026, PR-14)", () => {
  const none = { forYou: false, mine: false, prompt: true };
  const own = { forYou: true, mine: true, prompt: false };

  test("without a layer of their own there is no selector, and PrediGol always shows", () => {
    for (const view of ["all", "mine"] as const) {
      expect(shownLayers(view, none)).toEqual({ selector: false, forYou: false, predigol: true });
    }
  });

  test("«Todo» is Inicio as it always was: the reader's layer on top of PrediGol's", () => {
    expect(shownLayers("all", own)).toEqual({ selector: true, forYou: true, predigol: true });
  });

  test("«Para ti» keeps only what the reader follows", () => {
    expect(shownLayers("mine", own)).toEqual({ selector: true, forYou: true, predigol: false });
  });
});
