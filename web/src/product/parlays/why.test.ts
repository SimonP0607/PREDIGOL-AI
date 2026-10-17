/// <reference types="bun" />
import { describe, expect, test } from "bun:test";
import { fairOf } from "./why";

describe("a leg's price against its fair price (REVIEW point 15)", () => {
  test("fair = 1 / p_market; edge = odds x p_market - 1", () => {
    const { fair, edge } = fairOf("2.30", "0.43");
    expect(fair).toBeCloseTo(2.3256, 4);
    expect(edge).toBeCloseTo(-0.011, 3);
  });
  test("no market probability: nothing to compare", () => {
    expect(fairOf("2.30", "0")).toEqual({ fair: null, edge: null });
    expect(fairOf("2.30", null as unknown as string)).toEqual({ fair: null, edge: null });
  });
});
