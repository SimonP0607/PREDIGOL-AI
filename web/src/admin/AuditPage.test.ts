/// <reference types="bun" />
import { describe, expect, test } from "bun:test";
import { sumOf, TODAY_FIGURES } from "./AuditPage";

describe("«Hoy en cifras» of the audit (plan maestro UX/UI 2026, decision 12)", () => {
  const counts = new Map([
    ["login.succeeded", 14],
    ["login.failed", 4],
    ["login.refused", 1],
    ["login.locked", 1],
    ["admin.write", 6],
    ["membership.payment_recorded", 1],
    ["user.created", 9],
  ]);

  test("each figure adds up the rows of its own actions, and nothing else", () => {
    const figures = Object.fromEntries(TODAY_FIGURES.map((f) => [f.key, sumOf(counts, f.actions)]));
    expect(figures).toEqual({ logins: 14, failed: 5, locked: 1, console: 6, payments: 1 });
  });

  test("an action the day did not record counts zero: never a guess", () => {
    expect(sumOf(new Map(), ["login.locked"])).toBe(0);
  });

  test("no action is counted in two figures", () => {
    const all = TODAY_FIGURES.flatMap((f) => f.actions);
    expect(new Set(all).size).toBe(all.length);
  });
});
