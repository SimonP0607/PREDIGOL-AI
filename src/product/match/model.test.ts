/// <reference types="bun" />
/**
 * The Match Center's logic on small, real-shaped payloads: which price is best and how
 * lines pair up, what the live state says, how goals are credited, and the form order.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { setLocale } from "@/lib/i18n";
import type { MarketQuote } from "@/lib/api/v1/types";
import type {
  LineupPlayer,
  LiveQuote,
  LiveState,
  MatchEvent,
  TeamLineup,
} from "@/lib/api/v1/types_center";
import {
  absenceReason,
  bestPrices,
  eventKind,
  goalCredit,
  h2hSummary,
  lastFive,
  liveMarkets,
  liveSnapshot,
  marketBoards,
  matchPhase,
  normalizeStatus,
  pitchSpots,
  priceRows,
  roundLabel,
  scorerName,
  shownScore,
  statRows,
  subDirection,
  timeline,
  visibleRows,
} from "./model";

afterEach(() => setLocale("es"));

function quote(p: Partial<MarketQuote>): MarketQuote {
  return {
    bookmaker_id: 1,
    bookmaker: "Book A",
    market_key: "1X2",
    selection: "Home",
    line: "0.00",
    odds_decimal: "2.000",
    implied_probability: "0.5",
    captured_at: "2026-10-03T17:00:00Z",
    minutes_to_ko: 60,
    source: "prematch",
    payload_hash: "h",
    ...p,
  };
}

function state(p: Partial<LiveState>): LiveState {
  return {
    observed_at: "2026-10-03T18:00:00Z",
    source: "fixture_feed",
    status: "1H",
    elapsed: 10,
    extra: null,
    goals_home: 0,
    goals_away: 0,
    ...p,
  };
}

function event(p: Partial<MatchEvent>): MatchEvent {
  return {
    seq: 0,
    minute: 10,
    extra_minute: null,
    side: "home",
    player: "Player",
    player_id: null,
    assist: null,
    type: "Goal",
    detail: "Normal Goal",
    comments: null,
    ...p,
  };
}

function player(p: Partial<LineupPlayer>): LineupPlayer {
  return {
    provider_player_id: 1,
    player_id: 1,
    name: "P",
    number: 1,
    position: "G",
    grid: "1:1",
    starter: true,
    ...p,
  };
}

describe("phase and live state", () => {
  test("the phase follows the status group; a kicked-off fixture still marked NS awaits its result", () => {
    expect(matchPhase({ status_group: "live", awaiting_result: false })).toBe("live");
    expect(matchPhase({ status_group: "scheduled", awaiting_result: true })).toBe("awaiting");
    expect(matchPhase({ status_group: "scheduled", awaiting_result: false })).toBe("scheduled");
    expect(matchPhase({ status_group: "postponed", awaiting_result: false })).toBe("postponed");
    // The API's phase (fbi.core.match_state) wins: a suspension is in play, an abandoned or
    // awarded match is neither cancelled nor finished.
    expect(
      matchPhase({ status_group: "postponed", awaiting_result: false, phase: "suspended" }),
    ).toBe("live");
    expect(
      matchPhase({ status_group: "cancelled", awaiting_result: false, phase: "abandoned" }),
    ).toBe("abandoned");
    expect(
      matchPhase({ status_group: "cancelled", awaiting_result: false, phase: "not_played" }),
    ).toBe("not_played");
    expect(matchPhase({ status_group: "live", awaiting_result: true, phase: "awaiting" })).toBe(
      "awaiting",
    );
  });

  test("the odds feed's spelled-out states map to the short codes", () => {
    expect(normalizeStatus("Halftime")).toBe("HT");
    expect(normalizeStatus("Second Half")).toBe("2H");
    expect(normalizeStatus("1H")).toBe("1H");
  });

  test("minute from the newest observation, score from the newest one that has it", () => {
    const snap = liveSnapshot([
      state({ observed_at: "2026-10-03T18:40:00Z", status: "1H", elapsed: 40, goals_home: 1 }),
      state({
        observed_at: "2026-10-03T18:48:00Z",
        source: "odds_feed",
        status: "Halftime",
        elapsed: 45,
        goals_home: null,
        goals_away: null,
      }),
    ]);
    expect(snap?.status).toBe("HT");
    expect(snap?.elapsed).toBe(45);
    expect(snap?.goals).toEqual({ home: 1, away: 0 });
    expect(liveSnapshot([])).toBeNull();
  });

  test("live shows the in-play score, else the recorded one; nothing before kick-off", () => {
    const score = {
      home: 2,
      away: 1,
      ht_home: 1,
      ht_away: 0,
      et_home: null,
      et_away: null,
      pen_home: null,
      pen_away: null,
      outcome_1x2: "Home" as const,
      total_goals: 3,
      btts: true,
      source_payload_hash: null,
      source_fetched_at: null,
    };
    const live = { status: "2H", elapsed: 70, extra: null, goals: { home: 1, away: 1 }, at: "x" };
    expect(shownScore({ score: null }, live, "live")).toEqual({ home: 1, away: 1 });
    expect(shownScore({ score }, null, "finished")).toEqual({ home: 2, away: 1 });
    expect(shownScore({ score: null }, null, "live")).toBeNull();
    expect(shownScore({ score }, live, "scheduled")).toBeNull();
  });
});

describe("best prices across bookmakers", () => {
  const quotes = [
    quote({ bookmaker_id: 1, bookmaker: "A", selection: "Home", odds_decimal: "2.10" }),
    quote({ bookmaker_id: 2, bookmaker: "B", selection: "Home", odds_decimal: "2.25" }),
    quote({ bookmaker_id: 3, bookmaker: "C", selection: "Home", odds_decimal: "2.20" }),
    quote({ bookmaker_id: 1, bookmaker: "A", selection: "Draw", odds_decimal: "3.40" }),
    quote({
      bookmaker_id: 9,
      bookmaker: "Z",
      selection: "Home",
      odds_decimal: "9.00",
      source: "live",
    }),
  ];

  test("the highest price wins, with who offers it and how many quote it", () => {
    const home = bestPrices(quotes, "prematch").find((p) => p.selection === "Home");
    expect(home?.odds).toBe("2.25");
    expect(home?.bookmaker).toBe("B");
    expect(home?.books).toBe(3);
  });

  test("in-play quotes never mix into the pre-match prices", () => {
    expect(bestPrices(quotes, "live").map((p) => p.odds)).toEqual(["9.00"]);
  });

  test("Asian handicap: home -1.5 and away +1.5 are the same row", () => {
    const rows = priceRows("AH", [
      { selection: "Home", line: -1.5 },
      { selection: "Away", line: 1.5 },
      { selection: "Home", line: -0.5 },
    ]);
    expect(rows.map((r) => r.line)).toEqual([-1.5, -0.5]);
    expect(rows[0]?.cells.every((c) => c !== null)).toBe(true);
    expect(rows[1]?.cells[1]).toBeNull();
  });

  test("the main over/under line is the most balanced one, shown in a window around it", () => {
    const table: Array<[string, string, string]> = [
      ["1.50", "1.20", "4.50"],
      ["2.50", "1.80", "2.00"],
      ["3.50", "2.90", "1.40"],
    ];
    const ou = table.flatMap(([line, over, under]) => [
      quote({ market_key: "OU", selection: "Over", line, odds_decimal: over }),
      quote({ market_key: "OU", selection: "Under", line, odds_decimal: under }),
    ]);
    const board = marketBoards(ou, "prematch").find((b) => b.market === "OU");
    expect(board?.rows[board.main]?.line).toBe(2.5);
    expect(visibleRows([1, 2, 3, 4, 5, 6, 7, 8], 7, false)).toEqual([4, 5, 6, 7, 8]);
    expect(visibleRows([1, 2, 3, 4, 5, 6, 7, 8], 0, false)).toEqual([1, 2, 3, 4, 5]);
    expect(visibleRows([1, 2, 3], 1, false)).toEqual([1, 2, 3]);
  });
});

describe("in-play prices", () => {
  function lq(p: Partial<LiveQuote>): LiveQuote {
    return {
      market_key: "OU",
      provider_bet_id: 36,
      selection: "Over",
      line: "2.50",
      odds: "1.90",
      suspended: false,
      main_line: null,
      captured_at: "2026-10-03T18:40:00Z",
      minute: 40,
      ...p,
    };
  }

  test("a line withdrawn on both sides is dropped; the flagged main line is kept first", () => {
    const m = liveMarkets([
      lq({ line: "1.50", odds: null }),
      lq({ line: "1.50", selection: "Under", odds: null }),
      lq({ line: "2.75", main_line: true }),
      lq({ line: "2.75", selection: "Under", odds: "1.85", main_line: true }),
      lq({ market_key: null, selection: "Other" }),
    ]);
    expect(m.map((x) => x.market)).toEqual(["OU"]);
    const ou = m[0];
    expect(ou?.rows.map((r) => r.line)).toEqual([2.75]);
    expect(ou?.main).toBe(0);
  });
});

describe("events", () => {
  test("kinds from the provider's type and detail", () => {
    expect(eventKind({ type: "Goal", detail: "Own Goal" })).toBe("ownGoal");
    expect(eventKind({ type: "Goal", detail: "Missed Penalty" })).toBe("missedPenalty");
    expect(eventKind({ type: "Card", detail: "Second Yellow card" })).toBe("secondYellow");
    expect(eventKind({ type: "subst", detail: "Substitution 1" })).toBe("sub");
    expect(eventKind({ type: "Var", detail: "Goal cancelled" })).toBe("var");
  });

  test("an own goal is credited the way that matches the score", () => {
    const events = [
      event({ seq: 1, minute: 20, side: "home" }),
      event({ seq: 2, minute: 60, side: "away", detail: "Own Goal" }),
    ];
    const asOther = goalCredit(events, { home: 2, away: 0 });
    expect(asOther.reliable).toBe(true);
    expect(asOther.credit.get(2)).toBe("home");
    const asFiled = goalCredit(events, { home: 1, away: 1 });
    expect(asFiled.credit.get(2)).toBe("away");
    const unknown = goalCredit(events, null);
    expect(unknown.reliable).toBe(false);
    expect(unknown.credit.has(2)).toBe(false);
  });

  test("timeline: half-time mark between the halves, running score when it adds up", () => {
    const items = timeline(
      [event({ seq: 1, minute: 30 }), event({ seq: 2, minute: 70, side: "away" })],
      {
        score: { home: 1, away: 1 },
        halfTime: { home: 1, away: 0 },
        reachedHalfTime: true,
        reachedExtraTime: false,
        finished: true,
        newestFirst: false,
      },
    );
    expect(items.map((i) => (i.kind === "divider" ? i.label : i.event.seq))).toEqual([
      1,
      "ht",
      2,
      "ft",
    ]);
    const second = items[2];
    expect(second?.kind === "event" ? second.running : null).toEqual({ home: 1, away: 1 });
  });

  test("a substitution's direction comes from the line-ups", () => {
    const lineups: TeamLineup[] = [
      {
        side: "home",
        formation: "4-4-2",
        coach: null,
        players: [
          player({ player_id: 10, starter: true }),
          player({ player_id: 20, starter: false }),
        ],
      },
    ];
    expect(subDirection({ player_id: 20 }, lineups)).toBe("playerIn");
    expect(subDirection({ player_id: 10 }, lineups)).toBe("playerOut");
    expect(subDirection({ player_id: 99 }, lineups)).toBeNull();
  });
});

describe("form, head to head, line-ups", () => {
  test("the last five, oldest first, from the stored matches", () => {
    const chips = lastFive(
      {
        side: "home",
        team: "A",
        matches: ["W", "L", "D", "W", "W", "L"].map((result, i) => ({
          fixture_id: i,
          kickoff_at: `2026-09-${String(28 - i).padStart(2, "0")}T18:00:00Z`,
          opponent: `T${i}`,
          venue: "H" as const,
          goals_for: 1,
          goals_against: 0,
          result: result as "W" | "D" | "L",
        })),
      },
      undefined,
    );
    // Newest is W (28 Sep); the oldest of the five is W (24 Sep).
    expect(chips.map((c) => c.result)).toEqual(["W", "W", "D", "L", "W"]);
  });

  test("the table's form string is newest first, so it is reversed", () => {
    const chips = lastFive(undefined, {
      side: "home",
      team: "A",
      rank: 1,
      points: 3,
      played: 1,
      wins: 1,
      draws: 0,
      losses: 0,
      goals_for: 1,
      goals_against: 0,
      form: "LWDWW",
      group: null,
      snapshot_at: "x",
      before_kickoff: true,
    });
    expect(chips.map((c) => c.result)).toEqual(["W", "W", "D", "W", "L"]);
  });

  test("head to head counts wins by team, wherever they played", () => {
    const row = (home: string, away: string, gh: number, ga: number) => ({
      fixture_id: gh * 10 + ga,
      kickoff_at: "2025-01-01T00:00:00Z",
      competition: "L",
      home,
      away,
      goals_home: gh,
      goals_away: ga,
    });
    expect(
      h2hSummary([row("A", "B", 2, 0), row("B", "A", 1, 0), row("B", "A", 1, 1)], "A", "B"),
    ).toEqual({ homeWins: 1, draws: 1, awayWins: 1, counted: 3 });
  });

  test("the away side is mirrored on the pitch; no grid, no pitch", () => {
    const lineup = (side: "home" | "away"): TeamLineup => ({
      side,
      formation: "1-2",
      coach: null,
      players: [
        player({ provider_player_id: 1, grid: "1:1" }),
        player({ provider_player_id: 2, grid: "2:1", position: "D" }),
        player({ provider_player_id: 3, grid: "2:2", position: "D" }),
      ],
    });
    const home = pitchSpots(lineup("home"), "bottom");
    const away = pitchSpots(lineup("away"), "top");
    expect(home?.find((s) => s.player.provider_player_id === 2)?.x).toBe(25);
    expect(away?.find((s) => s.player.provider_player_id === 2)?.x).toBe(75);
    expect(home?.find((s) => s.player.provider_player_id === 1)?.y).toBe(93);
    expect(away?.find((s) => s.player.provider_player_id === 1)?.y).toBe(7);
    const noGrid = lineup("home");
    noGrid.players.push(player({ provider_player_id: 4, grid: null }));
    expect(pitchSpots(noGrid, "bottom")).toBeNull();
  });
});

describe("labels", () => {
  test("rounds in the reader's language", () => {
    setLocale("es");
    expect(roundLabel("Regular Season - 31")).toBe("Jornada 31");
    expect(roundLabel("Clausura - 11")).toBe("Clausura · Jornada 11");
    expect(roundLabel("Group Stage")).toBe("Fase de grupos");
    expect(roundLabel("Group A - 2")).toBe("Grupo A · Jornada 2");
    setLocale("en");
    expect(roundLabel("Regular Season - 9")).toBe("Matchday 9");
    expect(roundLabel("Something New")).toBe("Something New");
    expect(roundLabel(null)).toBeNull();
  });

  test("absence reasons fall into a few plain categories", () => {
    expect(absenceReason("Knee Injury")).toBe("injury");
    expect(absenceReason("Suspended")).toBe("suspension");
    expect(absenceReason("Yellow Cards")).toBe("suspension");
    expect(absenceReason("Illness")).toBe("illness");
    expect(absenceReason(null)).toBe("other");
  });

  test("compact scorer names and stat rows that skip what nobody reported", () => {
    expect(scorerName("Jesse van de Haar")).toBe("van de Haar");
    expect(scorerName("J. Nap")).toBe("Nap");
    expect(scorerName("Neymar")).toBe("Neymar");
    const rows = statRows([
      {
        side: "home",
        shots: 6,
        shots_on_target: 4,
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
        possession_pct: "46.00",
        passes: 200,
        passes_accurate: 150,
        expected_goals: null,
        fetched_at: "x",
      },
    ]);
    expect(rows.map((r) => r.key)).toEqual([
      "possession",
      "shots",
      "shotsOnTarget",
      "passes",
      "passesAccurate",
      "passAccuracy",
    ]);
    expect(rows.find((r) => r.key === "passAccuracy")?.home).toBe(75);
  });
});
