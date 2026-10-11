/// <reference types="bun" />
import { afterAll, describe, expect, test } from "bun:test";
import { setLocale } from "@/lib/i18n";
import { profileText } from "./profile";

describe("pre-match profile figures (REVIEW point 5)", () => {
  afterAll(() => setLocale("es"));

  test("a count reads as the example: 8 (100 %)", () => {
    setLocale("es");
    expect(
      profileText({ key: "wins", kind: "count" }, { value: "1.0000", count: 8, n: 8 }),
    ).toMatch(/^8 \(100\s?%\)$/);
  });

  test("an average with two decimals; possession as a share", () => {
    setLocale("es");
    expect(profileText({ key: "corners", kind: "average" }, { value: "7.2500", n: 8 })).toBe(
      "7,25",
    );
    expect(profileText({ key: "possession", kind: "average" }, { value: "55.5000", n: 4 })).toMatch(
      /^56\s?%$/,
    );
  });

  test("penalties as scored/taken", () => {
    expect(
      profileText({ key: "penalties", kind: "ratio" }, { value: null, count: 5, total: 7, n: 8 }),
    ).toBe("5/7");
  });

  test("no match with the data is no figure - never a zero", () => {
    expect(profileText({ key: "xg_for", kind: "average" }, { value: null, n: 0 })).toBeNull();
    expect(
      profileText({ key: "penalties", kind: "ratio" }, { value: null, count: 0, total: 0, n: 0 }),
    ).toBeNull();
  });
});
