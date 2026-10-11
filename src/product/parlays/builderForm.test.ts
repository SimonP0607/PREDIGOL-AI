/// <reference types="bun" />
import { describe, expect, test } from "bun:test";
import type { BuilderLeg } from "@/lib/api/v1/types_builder";
import {
  DEFAULT_BUILDER,
  adviceFor,
  builtToSlip,
  formIssues,
  legsBody,
  parsePrice,
  toBuilderQuery,
  toggled,
  withLegs,
} from "./builderForm";

describe("the automatic parlay builder's form (REVIEW point 15)", () => {
  test("a price is typed with a comma or a point", () => {
    expect(parsePrice("")).toBeNull();
    expect(parsePrice(" 1,5 ")).toBe(1.5);
    expect(parsePrice("2.25")).toBe(2.25);
    expect(Number.isNaN(parsePrice("1,5,0") ?? 0)).toBe(true);
    expect(Number.isNaN(parsePrice("abc") ?? 0)).toBe(true);
  });

  test("the form says what is wrong before anything is asked", () => {
    expect(formIssues(DEFAULT_BUILDER)).toEqual([]);
    expect(formIssues({ ...DEFAULT_BUILDER, minOdds: "1" })).toEqual(["minOdds"]);
    expect(formIssues({ ...DEFAULT_BUILDER, minOdds: "3", maxOdds: "2" })).toEqual(["oddsOrder"]);
    expect(formIssues({ ...DEFAULT_BUILDER, maxTotal: "1" })).toEqual(["maxTotal"]);
    expect(formIssues({ ...DEFAULT_BUILDER, maxOdds: "x" })).toEqual(["maxOdds"]);
    expect(formIssues({ ...DEFAULT_BUILDER, minLegs: 5, maxLegs: 4 })).toEqual(["legs"]);
  });

  test("the query is canonical: the same request is the same cache entry", () => {
    const q = toBuilderQuery({
      ...DEFAULT_BUILDER,
      markets: ["OU", "1X2", "OU"],
      competitions: [9, 2, 9],
      minOdds: "1,5",
      maxTotal: "20",
    });
    expect(q).toEqual({
      hours: 24,
      min_legs: 2,
      max_legs: 4,
      market: ["1X2", "OU"],
      competition_id: [2, 9],
      min_odds: "1.5",
      max_odds: undefined,
      max_total_odds: "20",
    });
    expect(toBuilderQuery(DEFAULT_BUILDER).market).toBeUndefined();
  });

  test("the legs never make an impossible pair", () => {
    expect(withLegs(DEFAULT_BUILDER, "min", 6)).toMatchObject({ minLegs: 6, maxLegs: 6 });
    expect(withLegs({ ...DEFAULT_BUILDER, minLegs: 5, maxLegs: 6 }, "max", 3)).toMatchObject({
      minLegs: 3,
      maxLegs: 3,
    });
    expect(withLegs(DEFAULT_BUILDER, "max", 99).maxLegs).toBe(7);
    expect(withLegs(DEFAULT_BUILDER, "min", 0).minLegs).toBe(2);
  });

  test("a multi-choice filter toggles one item", () => {
    expect(toggled(["1X2"], "OU")).toEqual(["1X2", "OU"]);
    expect(toggled(["1X2", "OU"], "1X2")).toEqual(["OU"]);
  });

  test("the answer goes to Mi parlay and to the save request as the slip would send it", () => {
    const leg = {
      fixture_id: 7,
      market_key: "OU",
      selection: "Over",
      line: "2.50",
      home: { id: 1, name: "A", logo_url: null },
      away: { id: 2, name: "B", logo_url: null },
      kickoff_at: "2032-08-01T15:00:00Z",
      odds: "2.10",
      bookmaker: "Book",
      p_model: "0.55",
    } as unknown as BuilderLeg;
    const [slip] = builtToSlip([leg]);
    expect(slip).toMatchObject({ key: "7|OU|Over|2.5", line: "2.5", odds: "2.10", home: "A" });
    expect(legsBody([leg])).toEqual([
      { fixture_id: 7, market_key: "OU", selection: "Over", line: "2.5" },
    ]);
  });

  test("the advice follows the reason there is no parlay", () => {
    expect(adviceFor("no_match")).toBe("filters");
    expect(adviceFor("total_odds_cap")).toBe("cap");
    expect(adviceFor("no_growth")).toBe("widen");
    expect(adviceFor("no_candidates")).toBe("wait");
  });
});
