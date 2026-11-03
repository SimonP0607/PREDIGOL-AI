/// <reference types="bun" />
/**
 * The rules of the screens of the shadow (plan IA, phase 3): shares are counts over counts, a share of nothing is nothing, the plan's thresholds are
 * counts against their numbers - there is no function that says "passed" -, the Opus cap, and the words of the arms in both languages.
 */
import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { hasKey, setLocale } from "@/lib/i18n";
import * as model from "./shadowModel";
import {
  ARMS,
  CONTRA_CODES,
  DECISION_KEYS,
  FILE_ENGINES,
  armLabel,
  contraLabel,
  decisionShares,
  disagrees,
  enoughState,
  invalidRate,
  invalidTone,
  opusLevel,
  progress,
  reasonLabel,
  ruleLine,
  share,
  sortedCounts,
  sumCounts,
} from "./shadowModel";

beforeEach(() => setLocale("es"));
afterEach(() => setLocale("es"));

describe("the arms and the engines", () => {
  test("seven arms in the order of the plan, and today's three reviewers before the shadow's three engines", () => {
    expect(ARMS).toEqual(["model", "rules", "gap", "llm", "council_solo", "ma-v1", "ma-v1-h"]);
    expect(FILE_ENGINES).toEqual(["rules", "llm", "combined", "ma-v1", "ma-v1-h", "cs-v1"]);
    expect(CONTRA_CODES).toHaveLength(8);
  });

  test("every arm, contradiction code and decision has its words in both languages", () => {
    for (const locale of ["es", "en"] as const) {
      for (const a of ARMS) expect(hasKey(`ai.arms.arm.${a}`, locale)).toBe(true);
      for (const c of CONTRA_CODES) expect(hasKey(`ai.contra.code.${c}`, locale)).toBe(true);
    }
    expect(armLabel("gap")).toBe("Filtro de brecha 0,20");
    setLocale("en");
    expect(armLabel("gap")).toBe("Gap filter 0.20");
    expect(contraLabel("C06")).toBe("Model against market");
  });

  test("a code the page does not know is shown as it is, never an empty word", () => {
    expect(armLabel("ma-v9")).toBe("ma-v9");
    expect(reasonLabel("something_new")).toBe("something_new");
    expect(reasonLabel("circuit_open")).toBe("Circuito abierto");
  });
});

describe("shares", () => {
  test("a share is a count over a count; over nothing it is nothing, not zero", () => {
    expect(share(1, 4)).toBe(0.25);
    expect(share(0, 4)).toBe(0);
    expect(share(3, 0)).toBeNull();
  });

  test("the share of each decision; an arm with no decisions (a rule) has none", () => {
    const d = { approved: 6, downgraded: 2, rejected: 1, abstained: 1 };
    expect(decisionShares(d, 10)).toEqual({
      approved: 0.6,
      downgraded: 0.2,
      rejected: 0.1,
      abstained: 0.1,
    });
    expect(decisionShares(null, 10)).toBeNull();
    expect(decisionShares(d, 0)?.approved).toBeNull();
    expect(DECISION_KEYS.map(([k]) => k)).toEqual([
      "approved",
      "downgraded",
      "rejected",
      "abstained",
    ]);
  });

  test("invalid outputs: not for a derived arm, and warned over the plan's 3 %", () => {
    expect(invalidRate({ kind: "derived", invalid: 0, reviews: 10 })).toBeNull();
    expect(invalidRate({ kind: "shadow", invalid: 0, reviews: 0 })).toBeNull();
    expect(invalidRate({ kind: "shadow", invalid: 1, reviews: 100 })).toBe(0.01);
    expect(invalidTone(0.03)).toBe("positive");
    expect(invalidTone(0.031)).toBe("warning");
    expect(invalidTone(null)).toBe("neutral");
  });

  test("counts are listed by size, then by name", () => {
    expect(sortedCounts({ b: 1, a: 1, c: 5 })).toEqual([
      ["c", 5],
      ["a", 1],
      ["b", 1],
    ]);
    expect(sumCounts({ a: 2, b: 3 })).toBe(5);
    expect(sumCounts({})).toBe(0);
  });
});

describe("enough data is a count, never a verdict", () => {
  test("the four states", () => {
    expect(enoughState({ days_reached: false, selections_reached: false })).toBe("none");
    expect(enoughState({ days_reached: true, selections_reached: false })).toBe("days");
    expect(enoughState({ days_reached: false, selections_reached: true })).toBe("selections");
    expect(enoughState({ days_reached: true, selections_reached: true })).toBe("both");
  });

  test("no export of the model answers pass / fail", () => {
    for (const name of Object.keys(model)) expect(name).not.toMatch(/pass(ed)?$|verdict|approve/i);
  });

  test("the words of every state never say that anything passed", () => {
    for (const locale of ["es", "en"] as const) {
      setLocale(locale);
      for (const s of ["none", "days", "selections", "both"]) {
        expect(hasKey(`ai.arms.enough.state.${s}`, locale)).toBe(true);
      }
    }
  });

  test("progress is capped at a whole bar and safe without a need", () => {
    expect(progress(150, 300)).toBe(50);
    expect(progress(900, 300)).toBe(100);
    expect(progress(5, 0)).toBe(0);
  });
});

describe("the Opus cap", () => {
  test("free, one left, spent", () => {
    expect(opusLevel({ calls: 0, cap: 3 })).toBe("free");
    expect(opusLevel({ calls: 2, cap: 3 })).toBe("last");
    expect(opusLevel({ calls: 3, cap: 3 })).toBe("spent");
    expect(opusLevel({ calls: 4, cap: 3 })).toBe("spent");
  });
});

describe("small helpers", () => {
  test("the rule that escalated, without repeats", () => {
    expect(ruleLine(null, [])).toBeNull();
    expect(ruleLine("E2", ["E2", "E5"])).toBe("E2 · E5");
    expect(ruleLine(null, ["E7"])).toBe("E7");
  });

  test("a verdict differs only when both exist and are not the same word", () => {
    expect(disagrees("APPROVE", "REJECT")).toBe(true);
    expect(disagrees("APPROVE", "APPROVE")).toBe(false);
    expect(disagrees("APPROVE", null)).toBe(false);
    expect(disagrees(null, "APPROVE")).toBe(false);
  });
});
