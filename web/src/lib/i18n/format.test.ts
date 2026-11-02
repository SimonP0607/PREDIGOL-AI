/// <reference types="bun" />
/**
 * Plan F13, one unit for the edge: p_model - p_market is a difference of probabilities, so it reads in percentage points
 * ("+7,5 pp"), never as a percentage; the expected value and a price gap are relative and stay "%".
 */
import { afterEach, describe, expect, test } from "bun:test";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { setLocale } from "./index";
import { DASH, fmtSignedPct, fmtSignedPp } from "./format";
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
