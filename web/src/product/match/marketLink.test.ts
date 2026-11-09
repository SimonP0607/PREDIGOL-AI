/// <reference types="bun" />
/**
 * The table between Cuotas and the match's «Mercados» (plan Cuotas, phase 6): a market of Cuotas at a period names the
 * catalogue's market, and an address names it back; what the catalogue does not structure has no row.
 */
import { describe, expect, test } from "bun:test";
import { CATALOG_CATEGORIES } from "@/lib/api/v1/types_market_catalog";
import links from "./marketLinks.json";
import { catalogTarget, targetOfKey } from "./marketLink";

// Assembled in parts, as the catalogue tests do: a market's key next to the word «key» looks like a credential to the scan.
const RESULT_1X2 = ["result_1x2", "FT", "match"].join(".");

describe("catalogTarget", () => {
  test("the 1X2 of the match is in «Resultado»", () => {
    const target = catalogTarget("result.1x2", "FT");
    expect(target?.category).toBe("result");
    expect(target?.key).toBe(RESULT_1X2);
  });

  test("a market of the explorer the catalogue does not structure has no target", () => {
    expect(catalogTarget("player.anytime_scorer", "FT")).toBeNull();
    expect(catalogTarget("nope", "FT")).toBeNull();
    expect(catalogTarget("result.1x2", "NO_PERIOD")).toBeNull();
  });
});

describe("targetOfKey", () => {
  test("an address names the market back, with its category", () => {
    expect(targetOfKey(RESULT_1X2)?.category).toBe("result");
  });

  test("an unknown or empty key opens no market", () => {
    expect(targetOfKey("made_up.FT.match")).toBeNull();
    expect(targetOfKey("")).toBeNull();
    expect(targetOfKey(null)).toBeNull();
    expect(targetOfKey(undefined)).toBeNull();
  });
});

describe("marketLinks.json", () => {
  test("every row names a category of the catalogue, and no key is repeated", () => {
    const taxes = new Set<string>();
    const keys = new Set<string>();
    for (const l of links.links) {
      expect((CATALOG_CATEGORIES as readonly string[]).includes(l.category)).toBe(true);
      expect(l.catalog.startsWith(`${l.catalog.split(".")[0]}.${l.period}.`)).toBe(true);
      expect(taxes.has(`${l.key}|${l.period}`)).toBe(false);
      expect(keys.has(l.catalog)).toBe(false);
      taxes.add(`${l.key}|${l.period}`);
      keys.add(l.catalog);
    }
    expect(links.links.length).toBeGreaterThan(0);
  });

  test("both directions agree on every row", () => {
    for (const l of links.links) {
      expect(catalogTarget(l.key, l.period)).toEqual(targetOfKey(l.catalog));
    }
  });
});
