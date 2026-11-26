/// <reference types="bun" />
/**
 * «Solo fútbol» and the pause on the screens that carry prices among football (plan PM, PM-14-07): the one place a price is written
 * writes none, the pick and parlay blocks draw nothing, the tabs that ARE a price leave the Match Center, and no screen writes a price
 * by a way that does not pass the gate.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import type { ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { AuthContextForTests } from "@/lib/auth/AuthProvider";
import { displayKey, setPricesOff } from "@/lib/display";
import { setLocale } from "@/lib/i18n";
import { formatOdds } from "@/lib/i18n/format";
import { DailySetBlock } from "@/product/records/DailySetBlock";
import { PicksTab } from "@/product/match/PicksTab";
import { tabsFor, tabsForCoverage } from "@/product/match/useMatchTab";
import { PickCard } from "@/product/shared/PickCard";
import { PriceNowLine } from "@/product/shared/PriceNowLine";
import { StartedPickCard } from "@/product/shared/StartedPickCard";

setLocale("es");
afterEach(() => setPricesOff(false));

/** A signed-in reader: with the mode on, or with nothing chosen. */
function reader(active: boolean, node: ReactElement): string {
  const user = { wellbeing: { available: true, active } };
  return renderToStaticMarkup(
    <AuthContextForTests.Provider value={{ user } as never}>{node}</AuthContextForTests.Provider>,
  );
}

describe("the one place a price is written", () => {
  test("outside the mode a price is written as always, in every format", () => {
    expect(formatOdds("2.10", "decimal")).toBe("2,10");
    expect(formatOdds("2.10", "american")).toBe("+110");
    expect(formatOdds("2.10", "fractional")).toBe("11/10");
  });

  test("inside it nothing is written, in any format", () => {
    setPricesOff(true);
    for (const f of ["decimal", "american", "fractional"] as const)
      expect(formatOdds("2.10", f)).toBe("—");
  });

  test("the pages are drawn again when the mode changes", () => {
    expect(displayKey(undefined, true)).not.toBe(displayKey(undefined, false));
  });
});

describe("what a reader in the mode is not shown", () => {
  test("a price line, a pick card, a started pick and the day's picks draw nothing", () => {
    const now = { odds: "2.07", as_of: new Date().toISOString(), freshness: "fresh", change: "0" };
    expect(reader(true, <PriceNowLine now={now as never} />)).toBe("");
    expect(reader(false, <PriceNowLine now={now as never} />)).not.toBe("");
    expect(reader(true, <PickCard pick={{} as never} />)).toBe("");
    expect(reader(true, <StartedPickCard pick={{} as never} />)).toBe("");
    expect(reader(true, <DailySetBlock query={{} as never} />)).toBe("");
    expect(reader(true, <PicksTab ctx={{} as never} />)).toBe("");
  });

  test("the Match Center loses Mercados and Análisis, keeps the football", () => {
    expect(tabsFor()).toEqual(["summary", "analysis", "stats", "markets", "lineups", "news"]);
    expect(tabsFor(true)).toEqual(["summary", "stats", "lineups", "news"]);
    const open = { blocks: [], markets: [] };
    expect(tabsForCoverage(open, { pricesShown: true })).toContain("markets");
    expect(tabsForCoverage(open, { pricesShown: true, noPrices: true })).toEqual([
      "summary",
      "stats",
      "lineups",
      "news",
    ]);
    expect(tabsForCoverage(null, { pricesShown: true, noPrices: true })).toEqual(tabsFor(true));
  });
});

describe("no screen writes a price by another way", () => {
  /** Every source file of the product screens, without tests and without the owner's consoles. */
  function sources(dir: string, out: string[] = []): string[] {
    for (const name of readdirSync(dir)) {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) {
        if (name === "admin" || name === "fixtures") continue;
        sources(path, out);
      } else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name)) out.push(path);
    }
    return out;
  }

  test("a price is a child of its element only through formatOdds or OddsPill, never raw", () => {
    const root = join(import.meta.dir, "..");
    // a raw price drawn as the child of an element: `>{pick.best_odds}<`, `>{price.odds}<`
    const RAW =
      />\s*\{\s*[\w.?!]*(best_odds|odds_taken|user_odds|published_odds|fair_odds|minimum_odds)\s*\}/;
    const offenders = sources(root).filter((f) => RAW.test(readFileSync(f, "utf8")));
    expect(offenders.map((f) => f.slice(root.length))).toEqual([]);
  });
});
