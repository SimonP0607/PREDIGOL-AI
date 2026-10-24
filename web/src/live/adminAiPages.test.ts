/// <reference types="bun" />
/**
 * Plan F13: Operación and Aprendizaje. Every tab and every view has its words in both languages and a body on its page, the menu has the two pages
 * and none of the five they replace, and each old address is a route that sends the reader to the new place.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { adminNav } from "@/components/layout/nav";
import { hasKey, setLocale, translate } from "@/lib/i18n";
import {
  AI_VIEWS,
  LEARNING_PATH,
  LEARNING_TABS,
  LEGACY_PAGES,
  MEMORY_VIEWS,
  OPERATION_PATH,
  OPERATION_TABS,
} from "./adminAi";

afterEach(() => setLocale("es"));

const SRC = join(import.meta.dir, "..");
const source = (relative: string) => readFileSync(join(SRC, relative), "utf8");

const LABELS = [
  { prefix: "admin.operation.tabs", ids: OPERATION_TABS },
  { prefix: "admin.operation.aiViews", ids: AI_VIEWS },
  { prefix: "admin.learning.tabs", ids: LEARNING_TABS },
  { prefix: "admin.learning.memoryViews", ids: MEMORY_VIEWS },
] as const;

describe("the words of the two pages", () => {
  test("every tab and every view is named in Spanish and in English, and no two of a set are named alike", () => {
    for (const { prefix, ids } of LABELS) {
      for (const locale of ["es", "en"] as const) {
        expect(hasKey(`${prefix}.label`, locale) || prefix.endsWith("memoryViews")).toBe(true);
        const names = ids.map((id) => {
          expect(hasKey(`${prefix}.${id}`, locale)).toBe(true);
          return translate(`${prefix}.${id}`, undefined, locale);
        });
        expect(new Set(names).size).toBe(names.length);
      }
    }
  });

  test("the two pages and their menu entries are named in both languages", () => {
    for (const locale of ["es", "en"] as const) {
      for (const key of [
        "admin.nav.operation",
        "admin.nav.learning",
        "admin.pages.operation.title",
        "admin.pages.operation.description",
        "admin.pages.learning.title",
        "admin.pages.learning.description",
      ]) {
        expect(hasKey(key, locale)).toBe(true);
      }
    }
  });
});

describe("every tab has a body on its page", () => {
  test("Operación shows each of its tabs and each view of its AI work", () => {
    const page = source("live/OperationLive.tsx");
    for (const tab of OPERATION_TABS) expect(page).toContain(`tab === "${tab}"`);
    for (const view of AI_VIEWS) expect(page).toContain(`view === "${view}"`);
  });

  test("Aprendizaje shows each of its tabs, and its memory each of its views", () => {
    const page = source("live/LearningLive.tsx");
    for (const tab of LEARNING_TABS) expect(page).toContain(`tab === "${tab}"`);
    const memory = source("live/MemoryLive.tsx");
    for (const view of MEMORY_VIEWS) expect(memory).toContain(`view === "${view}"`);
  });
});

describe("the menu and the old addresses", () => {
  const items = adminNav.flatMap((group) => group.items);

  test("the menu has Operación and Aprendizaje, in the intelligence group, and none of the five pages they replace", () => {
    const group = adminNav.find((g) => g.label === "admin.groups.intelligence");
    expect(group?.items.map((i) => i.to)).toEqual(
      expect.arrayContaining([OPERATION_PATH, LEARNING_PATH]),
    );
    for (const page of LEGACY_PAGES) {
      expect(items.some((i) => i.to === `/admin/${page}`)).toBe(false);
    }
    expect(items.filter((i) => i.to === OPERATION_PATH || i.to === LEARNING_PATH)).toHaveLength(2);
  });

  test("each of the two pages is a route, and each old address is a route that redirects to the new place", () => {
    expect(source("routes/admin.operation.tsx")).toContain(`createFileRoute("${OPERATION_PATH}")`);
    expect(source("routes/admin.learning.tsx")).toContain(`createFileRoute("${LEARNING_PATH}")`);
    for (const page of LEGACY_PAGES) {
      const route = source(`routes/admin.${page}.tsx`);
      expect(route).toContain(`createFileRoute("/admin/${page}")`);
      expect(route).toContain(`<LegacyRedirect page="${page}" />`);
    }
  });
});
