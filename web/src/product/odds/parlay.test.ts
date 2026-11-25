/// <reference types="bun" />
/** "Mi parlay" from a price: what can go in. */
import { describe, expect, test } from "bun:test";
import { setLocale } from "@/lib/i18n";
import { parlayBlock } from "./parlay";
import { blockedText, isToggleable, parlayActionText, type ParlayLegState } from "./useParlayLeg";

const NOW = Date.parse("2026-10-08T12:00:00Z");
const LATER = "2026-10-08T20:00:00Z";
const EARLIER = "2026-10-08T11:00:00Z";

describe("parlayBlock: the 'can add to parlay' rule", () => {
  const ok = { market_key: "1X2", odds: "2.10", line: "0", kickoff_at: LATER };

  test("a priced selection on a whole or half line, before kick-off", () => {
    expect(parlayBlock(ok, NOW)).toBe(null);
    expect(parlayBlock({ ...ok, market_key: "AH", line: "-0.5" }, NOW)).toBe(null);
    expect(parlayBlock({ ...ok, market_key: "OU", line: "2.50" }, NOW)).toBe(null);
  });

  test("not without a real price", () => {
    expect(parlayBlock({ ...ok, odds: null }, NOW)).toBe("no_price");
    expect(parlayBlock({ ...ok, odds: "1.00" }, NOW)).toBe("no_price");
    expect(parlayBlock({ ...ok, odds: "abc" }, NOW)).toBe("no_price");
  });

  test("never a quarter line", () => {
    expect(parlayBlock({ ...ok, market_key: "AH", line: "-0.25" }, NOW)).toBe("quarter");
    expect(parlayBlock({ ...ok, market_key: "OU", line: "2.75" }, NOW)).toBe("quarter");
  });

  test("never an outlier price: one book's stale or mistaken quote (plan Cuotas, E2)", () => {
    expect(parlayBlock({ ...ok, outlier: true }, NOW)).toBe("outlier");
    expect(parlayBlock({ ...ok, outlier: false }, NOW)).toBe(null);
    expect(parlayBlock({ ...ok, outlier: null }, NOW)).toBe(null);
  });

  test("nothing after kick-off", () => {
    expect(parlayBlock({ ...ok, kickoff_at: EARLIER }, NOW)).toBe("started");
    expect(parlayBlock({ ...ok, status_group: "live" }, NOW)).toBe("started");
    expect(parlayBlock({ ...ok, status_group: "scheduled" }, NOW)).toBe(null);
  });

  test("only the markets a parlay takes", () => {
    expect(parlayBlock({ ...ok, market_key: "CORNERS" }, NOW)).toBe("market");
  });

  test("a tap does something when the selection can be added, or is in the slip", () => {
    const state = (block: ParlayLegState["block"], inSlip: boolean): ParlayLegState => ({
      inSlip,
      block,
      replaces: false,
      toggle: () => undefined,
    });
    expect(isToggleable(null)).toBe(false);
    expect(isToggleable(state(null, false))).toBe(true);
    expect(isToggleable(state("quarter", false))).toBe(false);
    // In the slip already: it can always be taken out.
    expect(isToggleable(state("started", true))).toBe(true);

    // And when it cannot be added, the reader is told why (an outlier price, a quarter line, kicked off).
    setLocale("es");
    expect(blockedText(state("outlier", false))).toBe("Los precios atípicos no van en un parlay");
    expect(blockedText(state("quarter", false))).toBe(
      "Las líneas de cuarto (.25 / .75) no van en un parlay",
    );
    expect(blockedText(state("started", false))).toBe("El partido ya empezó");
    expect(blockedText(state("started", true))).toBe(null);
    expect(blockedText(state("market", false))).toBe(null);
    expect(blockedText(null)).toBe(null);
    // An outlier already in the slip can still be taken out.
    expect(isToggleable(state("outlier", false))).toBe(false);
    expect(isToggleable(state("outlier", true))).toBe(true);
    setLocale("en");
    expect(blockedText(state("outlier", false))).toBe("Unusual prices cannot go in a parlay");
    setLocale("es");
  });

  test("a tap is named for what it does now: «Quitar de mi parlay» once it is in (plan Cuotas, E7)", () => {
    setLocale("es");
    expect(parlayActionText({ inSlip: true, replaces: false })).toBe("Quitar de mi parlay");
    expect(parlayActionText({ inSlip: false, replaces: false })).toBe("Agregar a mi parlay");
    expect(parlayActionText({ inSlip: false, replaces: true })).toBe(
      "Reemplaza la otra selección de este partido en tu parlay: una por partido",
    );
    setLocale("en");
    expect(parlayActionText({ inSlip: true, replaces: false })).toBe("Remove from my parlay");
    setLocale("es");
  });
});
