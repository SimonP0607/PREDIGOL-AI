/// <reference types="bun" />
/** Plan F13: a page's tab is in the address, so a reload keeps it and a link can name it. */
import { describe, expect, test } from "bun:test";
import { hashWithTab, tabFromHash } from "./useUrlTab";

const TABS = ["audit_v2", "datasets", "runs"] as const;

describe("tabFromHash", () => {
  test("the tab the address names", () => {
    expect(tabFromHash("#tab=datasets", TABS)).toBe("datasets");
    expect(tabFromHash("tab=runs", TABS)).toBe("runs");
  });

  test("nothing, or something that is not a tab of this page, is no tab", () => {
    expect(tabFromHash("", TABS)).toBeNull();
    expect(tabFromHash("#", TABS)).toBeNull();
    expect(tabFromHash("#tab=hack", TABS)).toBeNull();
    expect(tabFromHash("#tab=", TABS)).toBeNull();
    expect(tabFromHash("#other=datasets", TABS)).toBeNull();
  });

  test("a page with two sets of tabs gives each its own parameter", () => {
    expect(
      tabFromHash(
        "#page=Historical%20market&odds=Movement",
        ["Captured by us", "Historical market"],
        "page",
      ),
    ).toBe("Historical market");
    expect(
      tabFromHash("#page=Historical%20market&odds=Movement", ["Board", "Movement"], "odds"),
    ).toBe("Movement");
  });
});

describe("hashWithTab", () => {
  test("sets the tab, keeps what else the hash says, and encodes it", () => {
    expect(hashWithTab("", "tab", "datasets")).toBe("#tab=datasets");
    expect(hashWithTab("#tab=runs", "tab", "datasets")).toBe("#tab=datasets");
    expect(hashWithTab("#odds=Movement", "page", "Historical market")).toBe(
      "#odds=Movement&page=Historical+market",
    );
  });

  test("the first tab leaves the address clean", () => {
    expect(hashWithTab("#tab=runs", "tab", null)).toBe("");
    expect(hashWithTab("#tab=runs&odds=Movement", "tab", null)).toBe("#odds=Movement");
  });

  test("what it writes is what tabFromHash reads", () => {
    for (const tab of ["Captured by us", "Historical market", "Near-close", "Ingestion runs"]) {
      expect(tabFromHash(hashWithTab("", "tab", tab), [tab])).toBe(tab);
    }
  });
});
