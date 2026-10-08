/// <reference types="bun" />
import { describe, expect, test } from "bun:test";
import {
  analysisLabel,
  canPromote,
  decisionsFor,
  groupOf,
  pct,
  promoteUnlocked,
  PROMOTE_WORD,
} from "./aiModel";

describe("the owner's answers", () => {
  test("a proposal can be rejected, investigated or approved as an experiment - nothing else", () => {
    expect(decisionsFor("PROPOSED")).toEqual(["reject", "investigate", "approve_experiment"]);
    expect(decisionsFor("INVESTIGATING")).toEqual(["reject", "approve_experiment"]);
    for (const s of ["ACCEPTED", "RUNNING", "SHADOW", "DONE", "PROMOTED", "REJECTED"] as const) {
      expect(decisionsFor(s)).toEqual([]);
    }
  });

  test("only a DONE experiment whose gate passed is promotable", () => {
    expect(canPromote({ status: "DONE", outcome: { gate_passed: true } })).toBe(true);
    expect(canPromote({ status: "DONE", outcome: { gate_passed: false } })).toBe(false);
    expect(canPromote({ status: "DONE", outcome: null })).toBe(false);
    expect(canPromote({ status: "SHADOW", outcome: { gate_passed: true } })).toBe(false);
  });

  test("groups follow the stages", () => {
    expect(groupOf({ status: "PROPOSED", outcome: null })).toBe("pending");
    expect(groupOf({ status: "INVESTIGATING", outcome: null })).toBe("pending");
    expect(groupOf({ status: "RUNNING", outcome: null })).toBe("experiment");
    expect(groupOf({ status: "DONE", outcome: { gate_passed: true } })).toBe("promotable");
    expect(groupOf({ status: "DONE", outcome: { gate_passed: false } })).toBe("closed");
    expect(groupOf({ status: "PROMOTED", outcome: { gate_passed: true } })).toBe("closed");
  });

  test("a promotion needs the typed word", () => {
    expect(promoteUnlocked("")).toBe(false);
    expect(promoteUnlocked("promover ")).toBe(true);
    expect(promoteUnlocked(PROMOTE_WORD)).toBe(true);
    expect(promoteUnlocked("PROMOTE")).toBe(false);
  });
});

describe("labels", () => {
  test("probabilities as percentages", () => {
    expect(pct("0.4512")).toBe(45.1);
    expect(pct(0.5)).toBe(50);
    expect(pct(null)).toBeNull();
    expect(pct("x")).toBeNull();
  });

  test("'Analizado por PrediGol AI' only when a language model took part", () => {
    expect(analysisLabel(true)).toBe("ai");
    expect(analysisLabel(false)).toBe("rules");
  });
});
