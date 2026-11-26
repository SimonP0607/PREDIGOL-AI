/// <reference types="bun" />
/** The line each selection of an odds row is quoted at (the one helper of the old board that Cuotas still uses). */
import { describe, expect, test } from "bun:test";
import { selectionLine } from "./board";

describe("selectionLine: each selection at its own line", () => {
  test("an Asian handicap's row carries the home line; its away side is the other face of the bet, at -h", () => {
    expect(selectionLine("AH", "Home", "-0.25")).toBe(-0.25);
    expect(selectionLine("AH", "Away", "-0.25")).toBe(0.25);
    expect(selectionLine("AH", "Away", "1.50")).toBe(-1.5);
    // a level handicap is 0 on both sides, never "-0"
    expect(Object.is(selectionLine("AH", "Away", "0.00"), 0)).toBe(true);
  });

  test("every other market keeps the row's line", () => {
    expect(selectionLine("OU", "Under", "2.50")).toBe(2.5);
    expect(selectionLine("1X2", "Away", "0.00")).toBe(0);
    expect(selectionLine("AH", "Away", null)).toBe(null);
  });
});
