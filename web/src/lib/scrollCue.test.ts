/// <reference types="bun" />
/** Mobile UX audit: a strip that scrolls shows where it hides content (the Match Center's tabs at 390 px). */
import { describe, expect, test } from "bun:test";
import { scrollCue } from "./scrollCue";

describe("scrollCue", () => {
  test("a strip that fits hides nothing", () => {
    expect(scrollCue(0, 358, 358)).toEqual({ start: false, end: false });
    expect(scrollCue(0, 359, 358)).toEqual({ start: false, end: false }); // a sub-pixel rounding, not content
  });

  test("at the start, only the end fades; in the middle both; at the end only the start", () => {
    expect(scrollCue(0, 520, 358)).toEqual({ start: false, end: true });
    expect(scrollCue(80, 520, 358)).toEqual({ start: true, end: true });
    expect(scrollCue(162, 520, 358)).toEqual({ start: true, end: false });
    expect(scrollCue(161.5, 520, 358)).toEqual({ start: true, end: false });
  });
});
