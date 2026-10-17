/// <reference types="bun" />
import { describe, expect, test } from "bun:test";
import { pageSlice } from "./paging";

describe("pages of 15 (REVIEW points 13 and 14)", () => {
  const all = Array.from({ length: 37 }, (_, i) => i + 1);

  test("15 per page, the last one short", () => {
    expect(pageSlice(all, 1).items).toEqual(all.slice(0, 15));
    const last = pageSlice(all, 3);
    expect([last.from, last.to, last.pages, last.items.length]).toEqual([31, 37, 3, 7]);
  });

  test("a page past the end is the last; before the first is the first", () => {
    expect(pageSlice(all, 9).page).toBe(3);
    expect(pageSlice(all, 0).page).toBe(1);
  });

  test("an empty list is one empty page", () => {
    expect(pageSlice([], 1)).toMatchObject({
      items: [],
      page: 1,
      pages: 1,
      total: 0,
      from: 0,
      to: 0,
    });
  });
});
