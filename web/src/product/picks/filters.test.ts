/// <reference types="bun" />
/** Filters become the API query; the API's own defaults stay out of it. */
import { describe, expect, test } from "bun:test";
import { DEFAULT_FILTERS, isDefault, toQuery } from "./filters";

describe("toQuery", () => {
  test("the page opens on the next 24 hours (REVIEW point 13), asked as such", () => {
    expect(DEFAULT_FILTERS.hours).toBe(24);
    expect(toQuery(DEFAULT_FILTERS)).toEqual({ hours: 24 });
    expect(isDefault(DEFAULT_FILTERS)).toBe(true);
  });

  test("every filter maps to its API parameter", () => {
    const q = toQuery({
      competition: { id: 40, name: "Liga Profesional Argentina" },
      market: "OU",
      odds: "1.5-2",
      hours: 168,
    });
    expect(q).toEqual({ competition_id: 40, market: "OU", min_odds: 1.5, max_odds: 2, hours: 168 });
  });

  test("72 h is the API's own default: left out; a wider window is a choice", () => {
    expect(toQuery({ ...DEFAULT_FILTERS, hours: 72 })).toEqual({});
    expect(isDefault({ ...DEFAULT_FILTERS, hours: 72 })).toBe(false);
  });

  test("an open-ended odds range has no maximum", () => {
    expect(toQuery({ ...DEFAULT_FILTERS, odds: "3+" })).toEqual({ min_odds: 3, hours: 24 });
  });
});
