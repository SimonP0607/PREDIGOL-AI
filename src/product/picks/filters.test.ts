/// <reference types="bun" />
/** Filters become the API query; the defaults stay out so the Top 5 and the list share a request. */
import { describe, expect, test } from "bun:test";
import { DEFAULT_FILTERS, isDefault, toQuery } from "./filters";

describe("toQuery", () => {
  test("no filter set: the same (empty) query the Top 5 uses", () => {
    expect(toQuery(DEFAULT_FILTERS)).toEqual({});
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

  test("an open-ended odds range has no maximum", () => {
    expect(toQuery({ ...DEFAULT_FILTERS, odds: "3+" })).toEqual({ min_odds: 3 });
    expect(isDefault({ ...DEFAULT_FILTERS, hours: 24 })).toBe(false);
  });
});
