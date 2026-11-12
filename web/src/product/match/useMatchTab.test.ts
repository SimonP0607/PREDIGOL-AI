import { describe, expect, test } from "bun:test";
import { initialTab, sectionsFor, tabFromLink, tabOf, tabsFor } from "./useMatchTab";

describe("the Match Center's tabs (decision 11)", () => {
  test("always six, whatever the match's state and whoever reads it", () => {
    expect(tabsFor()).toEqual(["summary", "analysis", "stats", "markets", "lineups", "news"]);
  });
  test("the research view is a section of the owner's alone, never a tab", () => {
    expect(sectionsFor(false)).toEqual(tabsFor());
    expect(sectionsFor(true)).toEqual([...tabsFor(), "advanced"]);
  });
  test("the Postpartido lives in the Resumen: its old links open it there", () => {
    expect(tabOf("postmatch")).toBe("summary");
    for (const link of ["postpartido", "Postpartido", "postmatch", "picks", "resumen"]) {
      const named = tabFromLink(link);
      expect(named === null ? null : tabOf(named)).toBe("summary");
    }
    expect(tabOf("markets")).toBe("markets");
  });
  test("a match opens on its Resumen, or on Estadísticas while it is played", () => {
    expect(initialTab("finished")).toBe("summary");
    expect(initialTab("live")).toBe("stats");
    expect(initialTab("scheduled")).toBe("summary");
    expect(initialTab(null)).toBe("summary");
  });
});
