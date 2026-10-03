/// <reference types="bun" />
/**
 * What the Live page reads out of a live match: key events, comparable statistics, the
 * current main prices, how fresh they are, and the board's headline numbers.
 */
import { describe, expect, test } from "bun:test";
import type { LiveMatch, LiveQuote, MatchEvent, TeamStatLine } from "@/lib/api/v1/types_center";
import {
  boardSummary,
  completenessBars,
  homeShare,
  keyEvents,
  latestEvents,
  levelOf,
  liveOdds,
  quoteFreshness,
  statRows,
} from "./model";

function ev(over: Partial<MatchEvent> & { seq: number; minute: number }): MatchEvent {
  return {
    extra_minute: null,
    side: "home",
    player: "Player",
    player_id: null,
    assist: null,
    type: "Goal",
    detail: "Normal Goal",
    comments: null,
    ...over,
  };
}

function stat(side: "home" | "away", over: Partial<TeamStatLine> = {}): TeamStatLine {
  return {
    side,
    shots: null,
    shots_on_target: null,
    shots_off_target: null,
    shots_blocked: null,
    shots_inside_box: null,
    shots_outside_box: null,
    corners: null,
    fouls: null,
    offsides: null,
    yellow_cards: null,
    red_cards: null,
    saves: null,
    possession_pct: null,
    passes: null,
    passes_accurate: null,
    expected_goals: null,
    fetched_at: "2026-10-03T18:57:37Z",
    ...over,
  };
}

function quote(
  market_key: string,
  selection: string,
  line: string,
  odds: string | null,
  captured: string,
  over: Partial<LiveQuote> = {},
): LiveQuote {
  return {
    market_key,
    provider_bet_id: market_key === "1X2" ? 59 : 36,
    selection,
    line,
    odds,
    suspended: false,
    main_line: market_key === "OU" ? true : null,
    captured_at: `2026-10-03T${captured}Z`,
    minute: null,
    ...over,
  };
}

function liveMatch(over: Partial<LiveMatch> = {}): LiveMatch {
  return {
    fixture_id: 1,
    kickoff_at: "2026-10-03T18:00:00Z",
    competition: "Eerste Divisie",
    country: "Netherlands",
    home: { id: 1, name: "Waalwijk" },
    away: { id: 2, name: "Emmen" },
    status: "2H",
    elapsed: 60,
    extra: null,
    goals_home: 1,
    goals_away: 0,
    state_at: "2026-10-03T18:58:17Z",
    state_source: "fixture_feed",
    state_age_seconds: 10,
    odds_feed_at: null,
    markets_offered: null,
    values_suspended: null,
    events: [],
    statistics: [],
    main_odds: [],
    data_status: "ok",
    ...over,
  };
}

describe("key events", () => {
  test("goals and red cards only, in match order, provider dots cleaned", () => {
    const list = keyEvents([
      ev({ seq: 3, minute: 45, extra_minute: 3, player: "David Barbona" }),
      ev({ seq: 0, minute: 6, side: "away", type: "Card", detail: "Yellow Card" }),
      ev({ seq: 1, minute: 22, player: "Rayan·Buifrahi" }),
      ev({ seq: 2, minute: 45, player: "Héctor David Martínez" }),
      ev({ seq: 4, minute: 50, side: "away", type: "Card", detail: "Red Card" }),
      ev({ seq: 5, minute: 61, side: "away", detail: "Own Goal", player: "Erik Janža" }),
      ev({ seq: 6, minute: 70, detail: "Penalty" }),
      ev({ seq: 7, minute: 75, detail: "Missed Penalty" }),
      ev({ seq: 8, minute: 120, detail: "Penalty", comments: "Penalty Shootout" }),
      ev({ seq: 9, minute: 80, side: null }),
    ]);
    expect(list.map((e) => [e.minute, e.kind])).toEqual([
      [22, "goal"],
      [45, "goal"],
      [45, "goal"],
      [50, "red_card"],
      [61, "own_goal"],
      [70, "penalty"],
    ]);
    expect(list[0]?.player).toBe("Rayan Buifrahi");
    expect(list[2]?.extra).toBe(3);
  });

  test("the most recent four, the rest counted", () => {
    const list = keyEvents(
      Array.from({ length: 6 }, (_, i) => ev({ seq: i, minute: 10 * (i + 1) })),
    );
    const { shown, hidden } = latestEvents(list);
    expect(shown.map((e) => e.minute)).toEqual([30, 40, 50, 60]);
    expect(hidden).toBe(2);
  });
});

describe("statistics", () => {
  test("only what both teams have; possession as a share", () => {
    const rows = statRows([
      stat("home", { possession_pct: "46.00", shots: 6, shots_on_target: 4, corners: 1 }),
      stat("away", { possession_pct: "54.00", shots: 5, shots_on_target: 1, corners: null }),
    ]);
    expect(rows.map((r) => [r.key, r.home, r.away])).toEqual([
      ["possession", 46, 54],
      ["shots", 6, 5],
      ["shotsOnTarget", 4, 1],
    ]);
    expect(homeShare(rows[0]!)).toBeCloseTo(0.46);
  });

  test("a match not kicked off has no statistics to show", () => {
    expect(statRows([stat("home"), stat("away")])).toEqual([]);
    expect(
      statRows([
        stat("home", { possession_pct: "0.00" }),
        stat("away", { possession_pct: "0.00" }),
      ]),
    ).toEqual([]);
    expect(homeShare({ key: "corners", home: 0, away: 0, pct: false })).toBe(0.5);
  });
});

describe("in-play prices", () => {
  test("1X2 in Home/Draw/Away order and the goals line quoted most recently", () => {
    const odds = liveOdds([
      quote("1X2", "Away", "0.00", "10.000", "18:47:17"),
      quote("1X2", "Draw", "0.00", "4.750", "18:47:47"),
      quote("1X2", "Home", "0.00", "1.333", "18:45:47"),
      quote("OU", "Over", "2.25", "1.975", "18:29:47"),
      quote("OU", "Under", "2.25", "1.825", "18:29:47"),
      quote("OU", "Over", "2.75", "1.925", "18:47:17"),
      quote("OU", "Under", "2.75", "1.875", "18:47:17"),
      quote("OU", "Over", "3.00", "2.025", "18:42:47"),
      quote("OU", "Under", "3.00", "1.775", "18:42:47"),
    ]);
    expect(odds.x12?.map((q) => q?.odds)).toEqual(["1.333", "4.750", "10.000"]);
    expect(odds.ou?.line).toBe("2.75");
    expect(odds.ou?.over?.odds).toBe("1.925");
    expect(odds.ou?.under?.odds).toBe("1.875");
    expect(odds.newest).toBe("2026-10-03T18:47:47Z");
  });

  test("a line with both sides beats a newer half line; suspended and withdrawn stay visible", () => {
    const odds = liveOdds([
      quote("OU", "Over", "3.25", "1.825", "18:33:47", { suspended: true }),
      quote("OU", "Under", "3.25", "1.975", "18:33:47", { suspended: true }),
      quote("OU", "Over", "4.25", null, "18:58:17"),
    ]);
    expect(odds.x12).toBeNull();
    expect(odds.ou?.line).toBe("3.25");
    expect(odds.ou?.over?.suspended).toBe(true);
    expect(liveOdds([]).ou).toBeNull();
    expect(liveOdds([]).newest).toBeNull();
  });

  test("freshness of a live price is counted in minutes", () => {
    const now = Date.parse("2026-10-03T19:00:00Z");
    expect(quoteFreshness("2026-10-03T18:59:00Z", now)).toBe("fresh");
    expect(quoteFreshness("2026-10-03T18:52:00Z", now)).toBe("aging");
    expect(quoteFreshness("2026-10-03T18:40:00Z", now)).toBe("stale");
    expect(quoteFreshness(null, now)).toBe("none");
  });
});

describe("the board", () => {
  test("in play vs about to start, and the newest state", () => {
    const s = boardSummary([
      liveMatch({ status: "Halftime", state_at: "2026-10-03T18:58:17Z" }),
      liveMatch({ status: "1H", state_at: "2026-10-03T18:57:37Z" }),
      liveMatch({ status: "Not Started", elapsed: 0, state_at: "2026-10-03T18:58:20Z" }),
    ]);
    expect(s).toEqual({ inPlay: 2, starting: 1, newest: "2026-10-03T18:58:20Z" });
  });

  test("level from the API, else from what the match carries", () => {
    expect(
      levelOf(
        liveMatch({
          completeness: {
            score: 30,
            level: "basic",
            signals: {
              score: true,
              minute: true,
              events: false,
              stats: false,
              lineups: false,
              players: false,
              live_odds: false,
              markets: false,
            },
          },
        }),
      ),
    ).toBe("basic");
    expect(levelOf(liveMatch())).toBe("basic");
    expect(levelOf(liveMatch({ statistics: [stat("home"), stat("away")] }))).toBe("partial");
  });

  test("the data meter", () => {
    expect([100, 90, 85, 70, 55, 40, 20].map(completenessBars)).toEqual([4, 4, 3, 3, 2, 2, 1]);
  });
});
