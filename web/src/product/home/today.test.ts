/// <reference types="bun" />
/**
 * Which matches each block of Inicio shows (plan UX, A9 and A13; section 24), from one board cut in the reader's day and
 * zone: block 1 in play first and never what is over, block 3 only the other competitions' matches with a reading, block 5
 * only the reader's next matches with context, block 6 the last 48 hours newest first. The reader's own matches are the
 * ones the API marks as theirs (``followed``); an API from before A13 marks the suggested ones only.
 */
import { describe, expect, test } from "bun:test";
import type { NextFixture, Today, TodayMatch } from "@/lib/api/v1/types_today";
import {
  CONTEXT_MATCHES,
  NEXT_FAVOURITES,
  RELEVANT_ROWS,
  contextAhead,
  followedOf,
  mineToday,
  nextOfFavourites,
  phaseOf,
  pickContext,
  relevantToday,
  suggestedView,
} from "./today";

const TZ = "America/Bogota";
/** Saturday 24 October 2026, 15:00 in Bogotá (20:00 UTC). */
const NOW = Date.parse("2026-10-24T20:00:00Z");
const H = 3_600_000;

let next = 1;
function m(over: Partial<TodayMatch> & { at: number }): TodayMatch {
  const { at, ...rest } = over;
  const id = next++;
  return {
    fixture_id: id,
    kickoff_at: new Date(at).toISOString(),
    status_group: "scheduled",
    status: "NS",
    elapsed: null,
    goals_home: null,
    goals_away: null,
    competition: {
      id: 1,
      name: "Liga BetPlay",
      country: "Colombia",
      logo_url: null,
      flag_url: null,
    },
    home: { id: 10 + id, name: `Local ${id}`, logo_url: null },
    away: { id: 100 + id, name: `Visita ${id}`, logo_url: null },
    suggested: true,
    forecast: null,
    headline: null,
    has_reading: false,
    context: [],
    ...rest,
  };
}

const live = (at: number, extra: Partial<TodayMatch> = {}) =>
  m({
    at,
    status_group: "live",
    status: "2H",
    elapsed: 61,
    goals_home: 1,
    goals_away: 0,
    ...extra,
  });
const over = (at: number, extra: Partial<TodayMatch> = {}) =>
  m({ at, status_group: "finished", status: "FT", goals_home: 2, goals_away: 2, ...extra });

describe("block 1 · today in the reader's leagues", () => {
  test("in play first, then by kick-off; what is over is left to Resultados", () => {
    const later = m({ at: NOW + 3 * H });
    const soon = m({ at: NOW + 1 * H });
    const playing = live(NOW - 1 * H);
    const done = over(NOW - 4 * H);
    const elsewhere = m({ at: NOW + 2 * H, suggested: false });
    const tomorrow = m({ at: NOW + 20 * H }); // 11:00 on Sunday in Bogotá
    const r = mineToday([later, soon, playing, done, elsewhere, tomorrow], TZ, NOW);
    expect(r.rows.map((x) => x.fixture_id)).toEqual([
      playing.fixture_id,
      soon.fixture_id,
      later.fixture_id,
    ]);
    expect(r.playedToday).toBe(1);
    expect(r.next).toEqual([]);
  });

  test("the reader's own day: Madrid's evening is past Bogotá's midnight", () => {
    const night = m({ at: Date.parse("2026-10-25T03:30:00Z") }); // 22:30 Bogotá · 04:30 Madrid (Sunday)
    expect(mineToday([night], TZ, NOW).rows).toHaveLength(1);
    expect(mineToday([night], "Europe/Madrid", NOW).rows).toHaveLength(0);
  });

  test("a match still in play from yesterday stays, at the top", () => {
    const midnight = Date.parse("2026-10-25T05:15:00Z"); // 00:15 on Sunday in Bogotá
    const sinceYesterday = live(Date.parse("2026-10-25T04:30:00Z")); // kicked off 23:30 on Saturday
    const soon = m({ at: midnight + 2 * H });
    const rows = mineToday([soon, sinceYesterday], TZ, midnight).rows;
    expect(rows.map((x) => x.fixture_id)).toEqual([sinceYesterday.fixture_id, soon.fixture_id]);
  });

  test("a stale «in play» is waiting for its result: after the matches to come, never as live", () => {
    const stale = m({ at: NOW - 5 * H, status_group: "live", status: "2H" });
    const soon = m({ at: NOW + 1 * H });
    expect(phaseOf(stale, NOW)).toBe("awaiting");
    const rows = mineToday([stale, soon], TZ, NOW).rows;
    expect(rows.map((x) => x.fixture_id)).toEqual([soon.fixture_id, stale.fixture_id]);
  });

  test("nothing today: the next suggested matches inside the window", () => {
    const tomorrow = m({ at: NOW + 20 * H });
    const after = m({ at: NOW + 30 * H });
    const r = mineToday([after, tomorrow, m({ at: NOW + 22 * H, suggested: false })], TZ, NOW);
    expect(r.rows).toEqual([]);
    expect(r.playedToday).toBe(0);
    expect(r.next.map((x) => x.fixture_id)).toEqual([tomorrow.fixture_id, after.fixture_id]);
  });

  test("everything already played today: said, with no «next» list", () => {
    const r = mineToday([over(NOW - 3 * H), m({ at: NOW + 20 * H })], TZ, NOW);
    expect(r.rows).toEqual([]);
    expect(r.playedToday).toBe(1);
    expect(r.next).toEqual([]);
  });

  test("a missing provider code reads the stored group", () => {
    expect(phaseOf(m({ at: NOW - 2 * H, status: null, status_group: "finished" }), NOW)).toBe(
      "finished",
    );
    expect(phaseOf(m({ at: NOW + H, status: null, status_group: "postponed" }), NOW)).toBe(
      "postponed",
    );
  });
});

describe("block 3 · relevant matches", () => {
  test("the other competitions' matches of today with a reading, at most five", () => {
    const rows = [
      ...Array.from({ length: 7 }, (_, i) =>
        m({ at: NOW + (i + 1) * 0.5 * H, suggested: false, has_reading: true }),
      ),
      m({ at: NOW + H, suggested: false, has_reading: false }),
      m({ at: NOW + H, suggested: true, has_reading: true }),
      over(NOW - 2 * H, { suggested: false, has_reading: true }),
    ];
    const relevant = relevantToday(rows, TZ, NOW);
    expect(relevant).toHaveLength(RELEVANT_ROWS);
    expect(relevant.every((x) => !x.suggested && x.has_reading)).toBe(true);
  });

  test("none with a reading: the block has nothing (it is left out of the page)", () => {
    expect(relevantToday([m({ at: NOW + H, suggested: false })], TZ, NOW)).toEqual([]);
  });
});

describe("block 5 · what is at stake", () => {
  const stake = {
    code: "stakes_pressure",
    params: { pressure: "title" },
    ref: "packet:stakes.home",
  };
  test("the next suggested matches with context, in kick-off order, at most four", () => {
    const rows = [
      ...Array.from({ length: 6 }, (_, i) => m({ at: NOW + (6 - i) * H, context: [stake] })),
      m({ at: NOW + H, context: [] }),
      live(NOW - H, { context: [stake] }),
      m({ at: NOW + H, suggested: false, context: [stake] }),
    ];
    const ahead = contextAhead(rows, NOW);
    expect(ahead).toHaveLength(CONTEXT_MATCHES);
    const kickoffs = ahead.map((x) => x.kickoff_at);
    expect(kickoffs).toEqual([...kickoffs].sort());
    expect(ahead.every((x) => x.suggested && x.context.length > 0)).toBe(true);
  });
});

describe("block 5 · the lines told of a match", () => {
  const f = (code: string, ref: string) => ({ code, params: {}, ref });
  const facts = [
    f("stakes_pressure", "packet:stakes.home"),
    f("stakes_pressure", "packet:stakes.away"),
    f("stakes_zone", "packet:stakes.home"),
    f("stakes_gap_up", "packet:stakes.home"),
    f("rest_days", "packet:schedule.home"),
    f("rest_days", "packet:schedule.away"),
    f("next_match", "packet:schedule.home.next_match"),
  ];

  test("table or tie, rest and next match - one of each first - never the line block 1 shows", () => {
    const lines = pickContext(facts, f("stakes_pressure", "packet:stakes.home"));
    expect(lines.map((l) => `${l.code} ${l.ref}`)).toEqual([
      "stakes_pressure packet:stakes.away",
      "rest_days packet:schedule.home",
      "next_match packet:schedule.home.next_match",
    ]);
  });

  test("with only what is at stake, up to three of it", () => {
    const lines = pickContext(facts.slice(0, 4), null);
    expect(lines.map((l) => l.code)).toEqual(["stakes_pressure", "stakes_pressure", "stakes_zone"]);
    expect(pickContext([], null)).toEqual([]);
  });
});

describe("A13 · the reader's own matches, as the API marks them", () => {
  const team = { kind: "team" as const, names: ["Atlético Nacional"] };
  const league = { kind: "league" as const, names: ["Liga BetPlay"] };

  test("the API's mark decides: a followed team's match elsewhere is theirs, a suggested league they do not follow is not", () => {
    const theirs = m({ at: NOW + H, suggested: false, followed: team });
    const notTheirs = m({ at: NOW + 2 * H, suggested: true, followed: null });
    const byLeague = m({ at: NOW + 3 * H, suggested: false, followed: league });
    const rows = mineToday([theirs, notTheirs, byLeague], TZ, NOW).rows;
    expect(rows.map((x) => x.fixture_id)).toEqual([theirs.fixture_id, byLeague.fixture_id]);
    const withReading = { ...notTheirs, has_reading: true };
    expect(relevantToday([theirs, withReading], TZ, NOW).map((x) => x.fixture_id)).toEqual([
      withReading.fixture_id,
    ]);
  });

  test("an API from before A13 (no mark at all): the suggested ones count as the reader's, by their league", () => {
    expect(followedOf(m({ at: NOW, suggested: true }))).toEqual(league);
    expect(followedOf(m({ at: NOW, suggested: false }))).toBeNull();
    expect(followedOf(m({ at: NOW, suggested: true, followed: null }))).toBeNull();
  });

  const day = (following: Today["following"]): Today => ({
    day: "2026-10-24",
    suggested: [],
    suggested_team: null,
    matches: { data: [], status: "ok", reason: null },
    no_pick: {
      data: { day: "2026-10-24", state: "none", stage: null, reason: null, matches: 0 },
      status: "ok",
      reason: null,
    },
    ...(following === undefined ? {} : { following }),
  });
  const nf = (id: number, at: number, name: string): NextFixture => ({
    followed: { kind: "team", names: [name] },
    fixture_id: id,
    kickoff_at: new Date(at).toISOString(),
    competition: {
      id: 1,
      name: "Liga BetPlay",
      country: "Colombia",
      logo_url: null,
      flag_url: null,
    },
    home: { id: 1, name: "A", logo_url: null },
    away: { id: 2, name: "B", logo_url: null },
  });

  test("labelled as suggested while the reader chose none, with personalisation off, or with an API from before A13", () => {
    const mine = { suggested: false, personalization: true, leagues: [], teams: [], next: [] };
    expect(suggestedView(day(mine))).toBe(false);
    expect(suggestedView(day({ ...mine, suggested: true }))).toBe(true);
    expect(suggestedView(day(undefined))).toBe(true);
  });

  test("their leagues do not play today: the next match of each favourite still to come, in kick-off order", () => {
    const next = [
      nf(3, NOW + 50 * H, "Millonarios"),
      nf(1, NOW + 5 * H, "Nacional"),
      nf(1, NOW + 5 * H, "Liga BetPlay"), // a team and its league share the match: one row
      nf(2, NOW - H, "Santa Fe"), // already kicked off since the API answered
      ...Array.from({ length: 8 }, (_, i) => nf(10 + i, NOW + (60 + i) * H, `Equipo ${i}`)),
    ];
    const shown = nextOfFavourites(
      day({ suggested: false, personalization: true, leagues: [], teams: [], next }),
      NOW,
    );
    expect(shown.map((n) => n.fixture_id).slice(0, 3)).toEqual([1, 3, 10]);
    expect(shown).toHaveLength(NEXT_FAVOURITES);
    expect(nextOfFavourites(day(undefined), NOW)).toEqual([]);
  });
});
