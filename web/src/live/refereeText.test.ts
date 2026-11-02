/// <reference types="bun" />
import { describe, expect, test } from "bun:test";
import { hasKey } from "@/lib/i18n";
import {
  canUndo,
  isConflict,
  keepOptions,
  pickedAliases,
  reasonLabel,
  REASONS,
  settledShare,
} from "./refereeText";

const side = (id: number, name: string, matches: number) => ({
  id,
  name,
  country: "England",
  matches,
});

describe("keepOptions", () => {
  test("the busier name is kept first, and each option merges the other into it", () => {
    const [first, second] = keepOptions(side(1, "M. Oliver", 12), side(2, "Michael Oliver", 80));
    expect(first).toEqual({ keepId: 2, mergeId: 1, name: "Michael Oliver" });
    expect(second).toEqual({ keepId: 1, mergeId: 2, name: "M. Oliver" });
  });

  test("a tie keeps the order of the pair", () => {
    const [first] = keepOptions(side(1, "A", 5), side(2, "B", 5));
    expect(first.keepId).toBe(1);
  });
});

describe("isConflict", () => {
  test("only a 409 asks for the force", () => {
    expect(isConflict({ status: 409 })).toBe(true);
    expect(isConflict({ status: 404 })).toBe(false);
    expect(isConflict(new Error("x"))).toBe(false);
    expect(isConflict(null)).toBe(false);
    expect(isConflict("409")).toBe(false);
  });
});

describe("canUndo", () => {
  test("a merge nothing has taken back", () => {
    expect(canUndo({ action: "merge", undone_by: null })).toBe(true);
    expect(canUndo({ action: "merge", undone_by: 7 })).toBe(false);
    expect(canUndo({ action: "split", undone_by: null })).toBe(false);
    expect(canUndo({ action: "undo", undone_by: null })).toBe(false);
  });
});

describe("settledShare", () => {
  test("is a fraction and never leaves 0..1", () => {
    expect(settledShare({ settled_share: 0.97 })).toBe(0.97);
    expect(settledShare({ settled_share: 1.4 })).toBe(1);
    expect(settledShare({ settled_share: -1 })).toBe(0);
    expect(settledShare({ settled_share: Number.NaN })).toBe(0);
  });
});

describe("pickedAliases", () => {
  test("keeps the order of the list, whatever the order of the ticks", () => {
    expect(pickedAliases([5, 3, 9, 1], new Set([9, 5]))).toEqual([5, 9]);
    expect(pickedAliases([5, 3], new Set())).toEqual([]);
  });
});

describe("reasonLabel", () => {
  test("every reason the rules give has a text, and an unknown one shows its code", () => {
    for (const code of REASONS) expect(reasonLabel(code)).not.toBe(code);
    expect(reasonLabel("something_new")).toBe("something_new");
  });
});

describe("texts", () => {
  test("every key the pages build at run time exists in both languages", () => {
    const keys = [
      ...REASONS.map((r) => `referees.reasons.${r}`),
      ...["identity", "extension", "initial", "foreign", "unscoped", "stored", "manual"].map(
        (b) => `referees.basis.${b}`,
      ),
      ...["open", "rejected", "merged"].map((x) => `referees.queue.status.${x}`),
      ...["merge", "undo", "split", "reject", "reopen", "rename"].map(
        (a) => `referees.action.names.${a}`,
      ),
    ];
    for (const locale of ["es", "en"] as const)
      for (const key of keys)
        expect([locale, key, hasKey(key, locale)]).toEqual([locale, key, true]);
  });
});
