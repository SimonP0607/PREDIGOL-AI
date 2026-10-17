import { describe, expect, test } from "bun:test";
import { hasKey } from "@/lib/i18n";
import {
  dependencyOf,
  explainedReasons,
  hasStarted,
  isQuarterLine,
  normLine,
  parlayTone,
  parseSlip,
  resultTone,
  selectionKey,
  sharedTeamHint,
  slipEstimate,
  slipOdds,
  slipProbability,
  slipReduce,
  toProbability,
  DEPENDENCY_LEVELS,
  DEPENDENCY_REASONS,
  MAX_SLIP_LEGS,
  type SlipLeg,
} from "./model";

function leg(
  fixture: number,
  selection = "Home",
  odds: string | null = "2.00",
): Omit<SlipLeg, "key"> {
  return {
    fixture_id: fixture,
    market_key: "1X2",
    selection,
    line: "0",
    home: `H${fixture}`,
    away: `A${fixture}`,
    kickoff_at: "2032-08-01T18:00:00Z",
    odds,
    bookmaker: "Book",
  };
}

/** A leg as the summary reads it: its teams and PrediGol's probability. */
function teams(home: string, away: string, p_model: string | null = null) {
  return { home, away, p_model };
}

describe("selections", () => {
  test("lines compare as numbers", () => {
    expect(normLine("2.50")).toBe("2.5");
    expect(normLine("0.00")).toBe("0");
    expect(normLine(-0.75)).toBe("-0.75");
    expect(selectionKey({ fixture_id: 1, market_key: "OU", selection: "Over", line: "2.50" })).toBe(
      selectionKey({ fixture_id: 1, market_key: "OU", selection: "Over", line: 2.5 }),
    );
  });

  test("quarter lines", () => {
    expect(isQuarterLine("-0.25")).toBe(true);
    expect(isQuarterLine("2.75")).toBe(true);
    expect(isQuarterLine("2.5")).toBe(false);
    expect(isQuarterLine(0)).toBe(false);
  });

  test("tones", () => {
    expect(resultTone("HALF_WIN")).toBe("win");
    expect(resultTone("PUSH")).toBe("neutral");
    expect(resultTone("PENDING")).toBe("pending");
    expect(parlayTone("PARTIAL_VOID")).toBe("win");
    expect(parlayTone("ACTIVE")).toBe("live");
    expect(parlayTone("BUILDING")).toBe("pending");
  });

  test("a match has started at kick-off or once it is no longer scheduled", () => {
    const at = Date.parse("2032-08-01T18:00:00Z");
    expect(hasStarted({ kickoff_at: "2032-08-01T18:00:00Z" }, at - 1)).toBe(false);
    expect(hasStarted({ kickoff_at: "2032-08-01T18:00:00Z" }, at)).toBe(true);
    expect(
      hasStarted({ kickoff_at: "2032-08-01T18:00:00Z", status_group: "live" }, at - 60_000),
    ).toBe(true);
  });
});

describe("the slip", () => {
  test("adds, removes on a second tap, and keeps one leg per match", () => {
    let legs = slipReduce([], { type: "toggle", leg: leg(1) }).legs;
    legs = slipReduce(legs, { type: "toggle", leg: leg(2) }).legs;
    expect(legs.map((l) => l.fixture_id)).toEqual([1, 2]);
    const replaced = slipReduce(legs, { type: "toggle", leg: leg(1, "Draw") });
    expect(replaced.effect).toBe("replaced");
    expect(replaced.legs.map((l) => l.selection)).toEqual(["Draw", "Home"]);
    const removed = slipReduce(replaced.legs, { type: "toggle", leg: leg(1, "Draw") });
    expect(removed.effect).toBe("removed");
    expect(removed.legs.map((l) => l.fixture_id)).toEqual([2]);
  });

  test("never more than ten legs", () => {
    let legs: SlipLeg[] = [];
    for (let i = 1; i <= MAX_SLIP_LEGS; i++)
      legs = slipReduce(legs, { type: "toggle", leg: leg(i) }).legs;
    const full = slipReduce(legs, { type: "toggle", leg: leg(99) });
    expect(full.effect).toBe("full");
    expect(full.legs).toHaveLength(MAX_SLIP_LEGS);
  });

  test("combined odds only when every leg has a price", () => {
    const legs = [leg(1, "Home", "2.00"), leg(2, "Home", "1.50")].map(
      (l) => slipReduce([], { type: "toggle", leg: l }).legs[0]!,
    );
    expect(slipOdds(legs)).toBe(3);
    expect(
      slipOdds([...legs, slipReduce([], { type: "toggle", leg: leg(3, "Home", null) }).legs[0]!]),
    ).toBeNull();
    expect(slipOdds([])).toBeNull();
  });

  test("a stored slip is read defensively", () => {
    expect(parseSlip(null)).toEqual([]);
    expect(parseSlip("not json")).toEqual([]);
    expect(parseSlip('{"a":1}')).toEqual([]);
    const raw = JSON.stringify([
      { ...leg(1), line: "0.00" },
      { ...leg(1, "Away") },
      { fixture_id: "x", market_key: "1X2", selection: "Home", kickoff_at: "z" },
      { ...leg(2), market_key: "CORNERS" },
    ]);
    const legs = parseSlip(raw);
    expect(legs.map((l) => [l.fixture_id, l.selection, l.line])).toEqual([[1, "Home", "0"]]);
  });

  test("a stored slip keeps PrediGol's probability when it is text, and nothing else", () => {
    const raw = JSON.stringify([
      { ...leg(1), p_model: "0.5432" },
      { ...leg(2), p_model: 0.61 },
      { ...leg(3) },
      { ...leg(4), p_model: null },
    ]);
    expect(parseSlip(raw).map((l) => [l.fixture_id, l.p_model])).toEqual([
      [1, "0.5432"],
      [2, null],
      [3, null],
      [4, null],
    ]);
  });
});

describe("what the slip adds up to", () => {
  test("a probability is a number in (0, 1]", () => {
    expect(toProbability("0.25")).toBe(0.25);
    expect(toProbability(1)).toBe(1);
    for (const bad of [null, undefined, "", "abc", "0", "-0.1", "1.2", "NaN", "Infinity"]) {
      expect(toProbability(bad)).toBeNull();
    }
  });

  test("the plain probability is the product of the legs', or nothing when one is unknown", () => {
    expect(slipProbability([{ p_model: "0.5" }, { p_model: "0.4" }])).toBeCloseTo(0.2, 12);
    expect(slipProbability([{ p_model: "0.5" }])).toBe(0.5);
    expect(slipProbability([{ p_model: "0.5" }, { p_model: null }])).toBeNull();
    expect(slipProbability([{ p_model: "0.5" }, {}])).toBeNull();
    expect(slipProbability([{ p_model: "0.5" }, { p_model: "1.5" }])).toBeNull();
    expect(slipProbability([{ p_model: "0.5" }, { p_model: "x" }])).toBeNull();
    expect(slipProbability([])).toBeNull();
  });

  test("two legs share a team by name, whatever the case or spacing, home or away", () => {
    expect(sharedTeamHint([teams("Real Madrid", "Getafe"), teams("Sevilla", "Betis")])).toBe(false);
    expect(sharedTeamHint([teams("Real Madrid", "Getafe"), teams("Betis", " real  MADRID ")])).toBe(
      true,
    );
    expect(sharedTeamHint([teams("Real Madrid", "Getafe"), teams("Getafe", "Betis")])).toBe(true);
    expect(sharedTeamHint([teams("Real Madrid", "Getafe")])).toBe(false);
    // A leg with the same name twice (bad data) does not match itself; unknown names never match.
    expect(sharedTeamHint([teams("Nacional", "nacional"), teams("Peñarol", "Defensor")])).toBe(
      false,
    );
    expect(sharedTeamHint([teams("", ""), teams("", "")])).toBe(false);
  });

  test("the server's dependence, typed: known levels and reasons only, each once", () => {
    expect(
      dependencyOf({
        dependency: {
          level: "medium",
          reasons: [
            "measured_dependence",
            "made_up",
            "measured_dependence",
            "same_competition_day",
          ],
        },
      }),
    ).toEqual({ level: "medium", reasons: ["measured_dependence", "same_competition_day"] });
    // An answer without a level only said whether the legs were independent.
    expect(dependencyOf({ correlation: { independent: false } })).toEqual({
      level: "medium",
      reasons: [],
    });
    expect(dependencyOf({ correlation: { independent: true } })).toEqual({
      level: "low",
      reasons: [],
    });
    expect(dependencyOf({})).toBeNull();
  });

  test("a measured dependence already says the legs share a competition and day", () => {
    expect(explainedReasons(["measured_dependence", "same_competition_day"])).toEqual([
      "measured_dependence",
    ]);
    expect(explainedReasons(["shared_team", "same_competition_day"])).toEqual([
      "shared_team",
      "same_competition_day",
    ]);
    expect(explainedReasons([])).toEqual([]);
  });

  test("before the server answers: the product at once, unless two legs share a team", () => {
    const independent = [teams("Real Madrid", "Getafe", "0.5"), teams("Sevilla", "Betis", "0.4")];
    const now = slipEstimate(independent, null);
    expect(now.dependency).toBeNull();
    expect(now.probability?.source).toBe("product");
    expect(now.probability?.value).toBeCloseTo(0.2, 12);

    const linked = [teams("Real Madrid", "Getafe", "0.5"), teams("Getafe", "Betis", "0.4")];
    expect(slipEstimate(linked, null)).toEqual({
      dependency: { level: "high", reasons: ["shared_team"], source: "hint" },
      probability: null,
    });

    const unknown = [teams("Real Madrid", "Getafe", "0.5"), teams("Sevilla", "Betis")];
    expect(slipEstimate(unknown, null).probability).toBeNull();
    // A check that failed cannot vouch for independence: no product.
    expect(slipEstimate(independent, null, true).probability).toBeNull();
  });

  test("the server's estimate, adjusted for dependence, replaces the product", () => {
    const legs = [teams("Real Madrid", "Getafe", "0.5"), teams("Sevilla", "Betis", "0.4")];
    expect(
      slipEstimate(legs, {
        estimated_probability: "0.231",
        dependency: { level: "medium", reasons: ["measured_dependence"] },
      }),
    ).toEqual({
      dependency: { level: "medium", reasons: ["measured_dependence"], source: "server" },
      probability: { value: 0.231, source: "server" },
    });
  });

  test("never a blind product of dependent legs", () => {
    const legs = [teams("Real Madrid", "Getafe", "0.5"), teams("Sevilla", "Betis", "0.4")];
    for (const level of ["medium", "high"] as const) {
      const out = slipEstimate(legs, { estimated_probability: null, dependency: { level } });
      expect(out.dependency?.level).toBe(level);
      expect(out.probability).toBeNull();
    }
    // Independent by the server's word: the product stands.
    const low = slipEstimate(legs, { dependency: { level: "low", reasons: [] } });
    expect(low.probability?.source).toBe("product");
    // The server said nothing about dependence: it cannot be vouched for.
    expect(slipEstimate(legs, { estimated_probability: null }).probability).toBeNull();
  });

  test("the server's word replaces the client's hint (two clubs may share a name)", () => {
    const legs = [teams("Nacional", "Peñarol", "0.5"), teams("Nacional", "Millonarios", "0.4")];
    const out = slipEstimate(legs, {
      estimated_probability: "0.2",
      dependency: { level: "low", reasons: [] },
    });
    expect(out.dependency).toEqual({ level: "low", reasons: [], source: "server" });
    expect(out.probability).toEqual({ value: 0.2, source: "server" });
    // Without a word on dependence, the hint stays.
    expect(slipEstimate(legs, { estimated_probability: "0.2" }).dependency?.source).toBe("hint");
  });

  test("every dependence level and reason has a label in Spanish and English", () => {
    const keys = [
      ...DEPENDENCY_LEVELS.map((l) => `records.slip.dependency.level.${l}`),
      ...DEPENDENCY_REASONS.map((r) => `records.slip.dependency.reason.${r}`),
    ];
    for (const key of keys) {
      expect([key, hasKey(key, "es"), hasKey(key, "en")]).toEqual([key, true, true]);
    }
  });
});
