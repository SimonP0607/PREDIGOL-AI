/// <reference types="bun" />
/**
 * Plan F13 (section 16): the five pages of the Admin Console that talked about the AI are two now. Every tab of the old pages has a home in the
 * new ones, and the addresses people kept (`/admin/ai-layer#tab=costs`) open what they opened.
 */
import { describe, expect, test } from "bun:test";
import { tabFromHash } from "@/lib/useUrlTab";
import {
  AI_VIEWS,
  LEARNING_PATH,
  LEARNING_TABS,
  LEGACY_PAGES,
  LEGACY_TABS,
  MEMORY_VIEWS,
  OPERATION_PATH,
  OPERATION_TABS,
  VIEW_PARAM,
  addressOf,
  isPlace,
  legacyAddress,
  legacyMoves,
  legacyPlace,
  strayAddress,
  type Place,
} from "./adminAi";

const TABS = { [OPERATION_PATH]: OPERATION_TABS, [LEARNING_PATH]: LEARNING_TABS } as const;
const VIEWS = {
  [OPERATION_PATH]: { ai: AI_VIEWS },
  [LEARNING_PATH]: { memory: MEMORY_VIEWS },
} as const;

/** Every place the two pages have: each tab, and each view of the tabs that hold views. */
function everyPlace(): Place[] {
  const places: Place[] = [];
  for (const path of [OPERATION_PATH, LEARNING_PATH] as const) {
    for (const tab of TABS[path]) {
      const views: readonly string[] | undefined = (
        VIEWS[path] as Record<string, readonly string[]>
      )[tab];
      if (views) for (const view of views) places.push({ path, tab, view });
      else places.push({ path, tab });
    }
  }
  return places;
}

describe("the old pages and their tabs", () => {
  test("every tab of every old page has a home, and every home is a place of the new pages", () => {
    const moves = legacyMoves();
    for (const page of LEGACY_PAGES) {
      const homes = moves.filter((move) => move.page === page);
      // the page itself (opened with no tab) and each of its tabs
      expect(homes.filter((move) => move.tab === null)).toHaveLength(1);
      for (const tab of LEGACY_TABS[page]) {
        expect(homes.some((move) => move.tab === tab)).toBe(true);
      }
      // and nothing in the table that the old page never had
      for (const move of homes) {
        if (move.tab !== null) expect(LEGACY_TABS[page]).toContain(move.tab);
        expect(isPlace(move.place)).toBe(true);
      }
    }
  });

  test("the five old pages are all in the table, and Evolución, which had no tabs, goes to what was learned", () => {
    expect([...LEGACY_PAGES].sort()).toEqual(
      ["ai-analyst", "ai-layer", "evolution", "intelligence", "memory"].sort(),
    );
    expect(LEGACY_TABS.evolution).toEqual([]);
    expect(legacyPlace("evolution", "")).toEqual({ path: LEARNING_PATH, tab: "learned" });
    expect(legacyPlace("evolution", "#tab=costs")).toEqual({ path: LEARNING_PATH, tab: "learned" });
  });

  test("an old page opened with no tab, or with one it never had, opens on the tab it opened on", () => {
    const opened = {
      intelligence: { path: OPERATION_PATH, tab: "day" },
      "ai-layer": { path: OPERATION_PATH, tab: "ai", view: "reviews" },
      "ai-analyst": { path: OPERATION_PATH, tab: "ai", view: "today" },
      evolution: { path: LEARNING_PATH, tab: "learned" },
      memory: { path: LEARNING_PATH, tab: "memory", view: "entities" },
    } as const;
    for (const page of LEGACY_PAGES) {
      expect(legacyPlace(page, "")).toEqual(opened[page]);
      expect(legacyPlace(page, "#")).toEqual(opened[page]);
      expect(legacyPlace(page, "#tab=hack")).toEqual(opened[page]);
      expect(legacyPlace(page, "#other=costs")).toEqual(opened[page]);
    }
  });

  test("the saved links keep opening what they opened", () => {
    // the three costs views of the old pages are the costs of Operación now
    for (const page of ["intelligence", "ai-layer", "ai-analyst"] as const) {
      expect(legacyAddress(page, "#tab=costs")).toEqual({ to: OPERATION_PATH, hash: "tab=costs" });
    }
    expect(legacyAddress("intelligence", "#tab=decisions")).toEqual({
      to: OPERATION_PATH,
      hash: "tab=decisions",
    });
    expect(legacyAddress("intelligence", "#tab=match")).toEqual({
      to: OPERATION_PATH,
      hash: "tab=match",
    });
    expect(legacyAddress("intelligence", "#tab=calibration")).toEqual({
      to: LEARNING_PATH,
      hash: "tab=calibration",
    });
    expect(legacyAddress("intelligence", "#tab=markets")).toEqual({
      to: LEARNING_PATH,
      hash: "tab=markets",
    });
    expect(legacyAddress("ai-layer", "#tab=evidence")).toEqual({
      to: OPERATION_PATH,
      hash: "tab=ai&view=evidence",
    });
    expect(legacyAddress("ai-layer", "#tab=shadow")).toEqual({
      to: LEARNING_PATH,
      hash: "tab=shadow",
    });
    expect(legacyAddress("ai-analyst", "#tab=close")).toEqual({
      to: LEARNING_PATH,
      hash: "",
    });
    expect(legacyAddress("ai-analyst", "#tab=learning")).toEqual({
      to: LEARNING_PATH,
      hash: "tab=learned",
    });
    expect(legacyAddress("ai-analyst", "#tab=research")).toEqual({
      to: OPERATION_PATH,
      hash: "tab=ai&view=research",
    });
    expect(legacyAddress("ai-analyst", "#tab=sources")).toEqual({
      to: OPERATION_PATH,
      hash: "tab=ai&view=sources",
    });
    expect(legacyAddress("memory", "#tab=postmortems")).toEqual({
      to: LEARNING_PATH,
      hash: "tab=postmortems",
    });
    expect(legacyAddress("memory", "#tab=events")).toEqual({
      to: LEARNING_PATH,
      hash: "tab=memory&view=notes",
    });
    expect(legacyAddress("memory", "#tab=research")).toEqual({
      to: LEARNING_PATH,
      hash: "tab=memory&view=findings",
    });
  });

  test("a hash with other parameters is read for its tab, and only for its tab", () => {
    expect(legacyAddress("ai-layer", "#day=2026-10-20&tab=costs")).toEqual({
      to: OPERATION_PATH,
      hash: "tab=costs",
    });
  });
});

describe("the address of a place", () => {
  test("the first tab, and the first view of a tab, leave the address clean", () => {
    expect(addressOf({ path: OPERATION_PATH, tab: "day" })).toEqual({
      to: OPERATION_PATH,
      hash: "",
    });
    expect(addressOf({ path: LEARNING_PATH, tab: "close" })).toEqual({
      to: LEARNING_PATH,
      hash: "",
    });
    expect(addressOf({ path: OPERATION_PATH, tab: "ai", view: "today" }).hash).toBe("tab=ai");
    expect(addressOf({ path: LEARNING_PATH, tab: "memory", view: "entities" }).hash).toBe(
      "tab=memory",
    );
  });

  test("a view other than the first is named, after its tab", () => {
    expect(addressOf({ path: OPERATION_PATH, tab: "ai", view: "sources" }).hash).toBe(
      `tab=ai&${VIEW_PARAM}=sources`,
    );
    expect(addressOf({ path: LEARNING_PATH, tab: "memory", view: "findings" }).hash).toBe(
      `tab=memory&${VIEW_PARAM}=findings`,
    );
  });

  test("a view of a tab that holds none is not written", () => {
    expect(addressOf({ path: OPERATION_PATH, tab: "costs", view: "reviews" }).hash).toBe(
      "tab=costs",
    );
  });

  test("what an address says is what the page reads back: every place round-trips through tabFromHash", () => {
    for (const place of everyPlace()) {
      expect(isPlace(place)).toBe(true);
      const { to, hash } = addressOf(place);
      expect(to).toBe(place.path);
      const tabs = TABS[place.path];
      expect(tabFromHash(hash, tabs)).toBe(place.tab === tabs[0] ? null : place.tab);
      const views = (VIEWS[place.path] as Record<string, readonly string[]>)[place.tab];
      if (views && place.view !== undefined) {
        expect(tabFromHash(hash, views, VIEW_PARAM)).toBe(
          place.view === views[0] ? null : place.view,
        );
      } else {
        expect(tabFromHash(hash, ["x"], VIEW_PARAM)).toBeNull();
      }
    }
  });

  test("every address of a place is distinct from every other", () => {
    const seen = new Set<string>();
    for (const place of everyPlace()) {
      const { to, hash } = addressOf(place);
      const key = `${to}#${hash}`;
      expect(seen.has(key)).toBe(false);
      seen.add(key);
    }
  });
});

describe("isPlace", () => {
  test("a tab of its page, with a view the tab holds or none", () => {
    expect(isPlace({ path: OPERATION_PATH, tab: "costs" })).toBe(true);
    expect(isPlace({ path: OPERATION_PATH, tab: "ai", view: "research" })).toBe(true);
    expect(isPlace({ path: OPERATION_PATH, tab: "ai" })).toBe(true);
  });

  test("a tab of the other page, a tab nobody has, or a view the tab does not hold, is none", () => {
    expect(isPlace({ path: OPERATION_PATH, tab: "calibration" })).toBe(false);
    expect(isPlace({ path: LEARNING_PATH, tab: "day" })).toBe(false);
    expect(isPlace({ path: LEARNING_PATH, tab: "nothing" })).toBe(false);
    expect(isPlace({ path: OPERATION_PATH, tab: "ai", view: "entities" })).toBe(false);
    expect(isPlace({ path: OPERATION_PATH, tab: "costs", view: "today" })).toBe(false);
  });
});

describe("an address that names a tab of the other page", () => {
  test("is sent to the page that has it, tab and view kept", () => {
    expect(strayAddress(OPERATION_PATH, "#tab=calibration")).toEqual({
      to: LEARNING_PATH,
      hash: "tab=calibration",
    });
    expect(strayAddress(OPERATION_PATH, "#tab=memory&view=notes")).toEqual({
      to: LEARNING_PATH,
      hash: "tab=memory&view=notes",
    });
    expect(strayAddress(LEARNING_PATH, "#tab=ai&view=reviews")).toEqual({
      to: OPERATION_PATH,
      hash: "tab=ai&view=reviews",
    });
    expect(strayAddress(LEARNING_PATH, "#tab=day")).toEqual({ to: OPERATION_PATH, hash: "" });
  });

  test("a view the other tab does not hold is dropped, and the tab opens on its first", () => {
    expect(strayAddress(OPERATION_PATH, "#tab=memory&view=reviews")).toEqual({
      to: LEARNING_PATH,
      hash: "tab=memory",
    });
  });

  test("nothing to move when the hash names a tab of this page, none, or something that is no tab", () => {
    expect(strayAddress(OPERATION_PATH, "")).toBeNull();
    expect(strayAddress(OPERATION_PATH, "#")).toBeNull();
    expect(strayAddress(OPERATION_PATH, "#tab=costs")).toBeNull();
    expect(strayAddress(OPERATION_PATH, "#tab=ai&view=reviews")).toBeNull();
    expect(strayAddress(OPERATION_PATH, "#tab=hack")).toBeNull();
    expect(strayAddress(LEARNING_PATH, "#tab=experiments")).toBeNull();
    expect(strayAddress(LEARNING_PATH, "#other=day")).toBeNull();
  });

  test("a tab both pages have is read as a tab of this page", () => {
    // no tab is shared today; the rule is that the page asked keeps what it can show
    const shared = OPERATION_TABS.filter((tab) =>
      (LEARNING_TABS as readonly string[]).includes(tab),
    );
    expect(shared).toEqual([]);
  });
});
