/// <reference types="bun" />
/**
 * Plan F2, the header of a leg of a tie: "Vuelta", "Ida 0–1" before the match, "Global 1–2" once it is on, and who went through
 * only when the match is over. The API orients every score to THIS match's home and away.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import type { MatchTie } from "@/lib/api/v1/types_center";
import { tieView } from "./tie";
import { TieLines } from "./TieLines";

afterEach(() => setLocale("es"));

const NAMES = { home: "Villarreal", away: "Juventus" };

function tie(over: Partial<MatchTie> = {}): MatchTie {
  return {
    format: "two_legged",
    state: "in_progress",
    leg: 2,
    legs: 2,
    played: 1,
    aggregate_before: { home: 0, away: 2 },
    aggregate: { home: 0, away: 2 },
    outcome: null,
    legs_list: [],
    ...over,
  };
}

describe("a second leg", () => {
  test("before the match it names the leg and what the first leg left", () => {
    const v = tieView(tie(), "scheduled", null, NAMES);

    expect(v).toEqual({ place: "Vuelta", score: "Ida 0–2", outcome: null });
  });

  test("while it is played the aggregate moves with the goals of the match", () => {
    expect(tieView(tie(), "live", { home: 1, away: 0 }, NAMES)?.score).toBe("Global 1–2");
    expect(tieView(tie(), "live", { home: 3, away: 0 }, NAMES)?.score).toBe("Global 3–2");
    expect(tieView(tie(), "live", null, NAMES)?.score).toBe("Ida 0–2");
  });

  test("a match waiting for its result keeps showing the first leg, not a sum it cannot confirm", () => {
    expect(tieView(tie(), "awaiting", { home: 1, away: 0 }, NAMES)?.score).toBe("Ida 0–2");
  });

  test("once over it shows the API's aggregate and who went through, and how", () => {
    const decided = tie({
      state: "decided",
      played: 2,
      aggregate: { home: 4, away: 2 },
      outcome: { winner: "home", decided_by: "aggregate", shootout: null, contradicted: false },
    });

    const v = tieView(decided, "finished", { home: 4, away: 0 }, NAMES);

    expect(v).toEqual({
      place: "Vuelta",
      score: "Global 4–2",
      outcome: "Pasa Villarreal · por el global",
    });
  });

  test.each([
    ["extra_time", "Pasa Juventus · tras tiempo extra"],
    ["penalties", "Pasa Juventus · en penales"],
    ["away_goals", "Pasa Juventus · por gol de visitante"],
    ["tiebreak", "Pasa Juventus · por desempate"],
    ["walkover", "Pasa Juventus · por decisión administrativa"],
    ["series", "Pasa Juventus · por la serie"],
    ["normal_time", "Pasa Juventus"],
  ] as const)("the way it was decided (%s) is said in words", (decidedBy, text) => {
    const decided = tie({
      state: "decided",
      aggregate: { home: 1, away: 1 },
      outcome: { winner: "away", decided_by: decidedBy, shootout: null, contradicted: false },
    });

    expect(tieView(decided, "finished", { home: 0, away: 0 }, NAMES)?.outcome).toBe(text);
  });

  test("the verdict of a tie never shows on the page of a match that is not over", () => {
    const stale = tie({
      state: "decided",
      outcome: { winner: "home", decided_by: "aggregate", shootout: null, contradicted: false },
    });

    for (const phase of ["scheduled", "live", "awaiting"] as const) {
      expect(tieView(stale, phase, null, NAMES)?.outcome).toBeNull();
    }
  });

  test("a finished match whose aggregate the API does not know says nothing about it", () => {
    const v = tieView(tie({ aggregate: null }), "finished", { home: 1, away: 1 }, NAMES);

    expect(v).toEqual({ place: "Vuelta", score: null, outcome: null });
  });
});

describe("a first leg", () => {
  test("is named, and shows no aggregate while the tie is open", () => {
    const first = tie({
      leg: 1,
      aggregate_before: null,
      aggregate: { home: 2, away: 0 },
      played: 1,
    });

    expect(tieView(first, "scheduled", null, NAMES)).toEqual({
      place: "Ida",
      score: null,
      outcome: null,
    });
    expect(tieView(first, "finished", { home: 2, away: 0 }, NAMES)).toEqual({
      place: "Ida",
      score: null,
      outcome: null,
    });
  });

  test("seen after the tie was decided, it tells the final aggregate and who went through", () => {
    const first = tie({
      leg: 1,
      state: "decided",
      played: 2,
      aggregate_before: null,
      aggregate: { home: 3, away: 2 },
      outcome: { winner: "home", decided_by: "aggregate", shootout: null, contradicted: false },
    });

    expect(tieView(first, "finished", { home: 2, away: 0 }, NAMES)).toEqual({
      place: "Ida",
      score: "Global 3–2",
      outcome: "Pasa Villarreal · por el global",
    });
  });
});

describe("the other formats", () => {
  test("a single match says nothing: its score and its penalties line already do", () => {
    const single = tie({
      format: "single",
      legs: 1,
      leg: 1,
      aggregate_before: null,
      aggregate: null,
      state: "decided",
      outcome: {
        winner: "home",
        decided_by: "penalties",
        shootout: { home: 4, away: 3 },
        contradicted: false,
      },
    });

    expect(tieView(single, "finished", { home: 1, away: 1 }, NAMES)).toBeNull();
  });

  test("a replay is named from its second match and is not added up", () => {
    const replay = tie({ format: "replay", leg: 2, aggregate_before: null, aggregate: null });

    expect(tieView(replay, "scheduled", null, NAMES)).toEqual({
      place: "Repetición",
      score: null,
      outcome: null,
    });
    expect(tieView({ ...replay, leg: 1 }, "scheduled", null, NAMES)).toBeNull();
  });

  test("a series counts its games", () => {
    const series = tie({
      format: "series",
      leg: 3,
      legs: 3,
      aggregate_before: null,
      aggregate: null,
    });

    expect(tieView(series, "scheduled", null, NAMES)?.place).toBe("Partido 3 de la serie");
  });

  test("a match with no tie says nothing", () => {
    expect(tieView(null, "finished", { home: 1, away: 0 }, NAMES)).toBeNull();
    expect(tieView(undefined, "scheduled", null, NAMES)).toBeNull();
  });
});

describe("in English", () => {
  test("the same words in the other language", () => {
    setLocale("en");
    const decided = tie({
      state: "decided",
      aggregate: { home: 3, away: 2 },
      outcome: { winner: "away", decided_by: "penalties", shootout: null, contradicted: false },
    });

    expect(tieView(tie(), "scheduled", null, NAMES)).toEqual({
      place: "Second leg",
      score: "First leg 0–2",
      outcome: null,
    });
    expect(tieView(decided, "finished", null, NAMES)).toEqual({
      place: "Second leg",
      score: "Aggregate 3–2",
      outcome: "Juventus go through · on penalties",
    });
  });
});

describe("the lines under the score", () => {
  test("render the aggregate and the verdict, each in its own line", () => {
    const html = renderToStaticMarkup(
      <TieLines
        view={{ place: "Vuelta", score: "Global 4–2", outcome: "Pasa Villarreal · por el global" }}
      />,
    );

    expect(html).toContain('data-testid="match-tie"');
    expect(html).toContain("Global 4–2");
    expect(html).toContain("Pasa Villarreal · por el global");
  });

  test("render nothing when there is neither", () => {
    expect(
      renderToStaticMarkup(<TieLines view={{ place: "Ida", score: null, outcome: null }} />),
    ).toBe("");
  });
});
