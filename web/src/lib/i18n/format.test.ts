/// <reference types="bun" />
/**
 * Plan F13, one unit for the edge: p_model - p_market is a difference of probabilities, so it reads in percentage points
 * ("+7,5 pp"), never as a percentage; the expected value and a price gap are relative and stay "%".
 */
import { afterEach, describe, expect, test } from "bun:test";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { setLocale } from "./index";
import { DASH, fmtSignedPct, fmtSignedPp, formatOdds } from "./format";
import { signedPp } from "@/lib/format";

afterEach(() => setLocale("es"));

const NBSP = "\u00a0";

describe("fmtSignedPp", () => {
  test("percentage points, signed, one decimal, in the reader's language", () => {
    setLocale("es");
    expect(fmtSignedPp(0.0745)).toBe(`+7,5${NBSP}pp`);
    expect(fmtSignedPp("0.07")).toBe(`+7,0${NBSP}pp`);
    expect(fmtSignedPp(-0.021)).toMatch(/^[-−]2,1\u00a0pp$/);
    setLocale("en");
    expect(fmtSignedPp(0.0745)).toBe(`+7.5${NBSP}pp`);
    expect(fmtSignedPp(0)).toBe(`0.0${NBSP}pp`);
  });

  test("a half rounds up as on paper (0.0745 * 100 is 7.4499... in binary)", () => {
    setLocale("en");
    expect(fmtSignedPp(0.0745)).toBe(`+7.5${NBSP}pp`);
    expect(fmtSignedPp(0.0005, 1)).toBe(`+0.1${NBSP}pp`);
  });

  test("two decimals when asked, and a dash for what is not a number", () => {
    setLocale("en");
    expect(fmtSignedPp(0.07456, 2)).toBe(`+7.46${NBSP}pp`);
    for (const none of [null, undefined, "", "n/a", Number.NaN])
      expect(fmtSignedPp(none)).toBe(DASH);
    expect(signedPp(null)).toBe(DASH);
    expect(signedPp(0.05)).toBe(`+5.0${NBSP}pp`);
  });

  test("the expected value stays a percentage: the same 0.07 is not the same thing", () => {
    setLocale("en");
    expect(fmtSignedPct(0.07)).toMatch(/^\+7\.0\s?%$/);
    expect(fmtSignedPp(0.07)).not.toContain("%");
  });
});

// ── the door: an edge is never shown as a percentage ─────────────────────────────────────────────────────────────

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "locales" ? [] : sourceFiles(path);
    return /\.(ts|tsx)$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
  });
}

describe("the edge is a difference of probabilities", () => {
  /** A percentage formatter handed the edge: `pick.edge`, `p.probability_edge`, `card.edge`... (not `price_edge`, a relative gap). */
  const PERCENT_OF_AN_EDGE =
    /\b(?:fmtSignedPct|fmtPct|signedPct|pct|decPct|localPct)\(\s*[\w$]+(?:\??\.[\w$]+)*\??\.(?:edge|probability_edge)\b/g;

  test("no source file formats a pick's edge or a probability_edge as a percentage", () => {
    const root = join(import.meta.dir, "..", "..");
    const offenders: string[] = [];
    for (const file of sourceFiles(root)) {
      const text = readFileSync(file, "utf8");
      for (const m of text.matchAll(PERCENT_OF_AN_EDGE))
        offenders.push(`${file.replace(root, "src")}: ${m[0]}`);
    }
    expect(offenders).toEqual([]);
  });

  test('the rule bites: it would have caught the cards that used to say "+7,4 %"', () => {
    const old = [
      "fmtSignedPct(pick.edge)",
      "signedPct(p.probability_edge)",
      "signedPct(pick.edge, 2)",
      "fmtPct(card.edge)",
    ];
    for (const line of old) expect([...line.matchAll(PERCENT_OF_AN_EDGE)].length).toBe(1);
    for (const fine of [
      "fmtSignedPct(p.price_edge)",
      "signedPct(p.ev)",
      "fmtSignedPp(pick.edge)",
      "fmtSignedPct(edge)",
    ]) {
      expect([...fine.matchAll(PERCENT_OF_AN_EDGE)].length).toBe(0);
    }
  });
});

// ── one formatter for a price (plan maestro UX/UI 2026, PR-09) ─────────────────────

describe("formatOdds", () => {
  /** What every price on a screen read before the single formatter, value by value: nothing may move. */
  const AS_BEFORE: Array<[number | string | null | undefined, string, string]> = [
    [1, "1,00", "1.00"],
    [1.05, "1,05", "1.05"],
    [2.1, "2,10", "2.10"],
    ["2.10", "2,10", "2.10"],
    [2.104, "2,10", "2.10"],
    [2.106, "2,11", "2.11"],
    [3.4, "3,40", "3.40"],
    [12, "12,00", "12.00"],
    [150.5, "150,50", "150.50"],
    [1001, "1001,00", "1,001.00"],
    [12500.5, "12.500,50", "12,500.50"],
    [null, DASH, DASH],
    [undefined, DASH, DASH],
    ["", DASH, DASH],
    ["nope", DASH, DASH],
    [Number.NaN, DASH, DASH],
  ];

  test("decimal odds with two places, in the reader's language, exactly as before", () => {
    for (const [value, es, en] of AS_BEFORE) {
      setLocale("es");
      expect(formatOdds(value)).toBe(es);
      setLocale("en");
      expect(formatOdds(value)).toBe(en);
    }
  });

  test("decimal is the format when none is given: the format changes the writing, never the price", () => {
    setLocale("es");
    expect(formatOdds(2.1, "decimal")).toBe(formatOdds(2.1));
  });

  test("it is the only one: no file keeps the old names or writes a price with toFixed", () => {
    const root = join(import.meta.dir, "..", "..");
    const offenders: string[] = [];
    // a price handed to toFixed: `x.odds.toFixed(`, `bestOdds.toFixed(`, `fair_odds).toFixed(`...
    const RAW_PRICE = /\b[\w$.?]*(?:odds|Odds|price|Price)\)?\.toFixed\(/g;
    for (const file of sourceFiles(root)) {
      // the generators of example data build numbers, they do not write prices on a screen
      if (/[\\/](mock|fake)[\\/.]|[\\/]fake\.ts$/.test(file)) continue;
      const text = readFileSync(file, "utf8");
      if (/\bfmtOdds\b/.test(text)) offenders.push(`${file}: fmtOdds`);
      for (const m of text.matchAll(RAW_PRICE)) offenders.push(`${file}: ${m[0]}`);
    }
    expect(readFileSync(join(root, "lib", "format.ts"), "utf8")).not.toMatch(
      /export function odds\b/,
    );
    expect(offenders).toEqual([]);
  });
});
