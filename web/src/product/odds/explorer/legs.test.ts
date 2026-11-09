/// <reference types="bun" />
/**
 * Mi Parlay from the explorer: the rules of today. Only the five classic markets at the full time go in, never from a stale
 * row, an outlier, a quarter line or a match under way; a leg carries the selection's own line (an Asian handicap's away side
 * at -h) and the price on show; a screen reader is told each leg in or out and how many the parlay holds.
 */
import { afterAll, describe, expect, test } from "bun:test";
import { setLocale } from "@/lib/i18n";
import type { SlipLeg } from "@/product/records/model";
import { FAKE_NOW, fakeRows } from "./fake";
import { blockText, explorerLeg, marketTakesParlay, priceBlock, slipAnnouncement } from "./legs";
import type { OddsMarketInfo } from "./model";

setLocale("es");
afterAll(() => setLocale("es"));

const HOUR = 3_600_000;

function info(key: string, kind: string, parlay = true): OddsMarketInfo {
  return {
    key,
    family: "result",
    kind,
    subject: "match",
    periods: ["FT"],
    has_line: kind !== "plain",
    fair: true,
    parlay,
    fixtures: 5,
    max_books: 8,
  };
}

const AH = info("result.asian_handicap", "signed_line");
const X12 = info("result.1x2", "plain");
const OU = info("goals.total", "line");
const ahRows = fakeRows("result.asian_handicap", "FT", "main");
const row = (rows: ReturnType<typeof fakeRows>, id: number) =>
  rows.find((r) => r.fixture_id === id)!;

describe("what can be tapped in", () => {
  test("a classic price the API marks parlay_ok, at the full time, before kick-off", () => {
    const madrid = row(ahRows, 7820);
    expect(madrid.selections.map((s) => priceBlock(AH, "FT", madrid, s, FAKE_NOW))).toEqual([
      null,
      null,
    ]);
  });

  test("a stale row, an outlier, a quarter line, a kicked-off match: never", () => {
    const stale = row(ahRows, 7821);
    expect(priceBlock(AH, "FT", stale, stale.selections[0]!, FAKE_NOW)).toBe("stale");
    const quarter = row(ahRows, 7819);
    expect(quarter.line).toBe("-0.25");
    expect(priceBlock(AH, "FT", quarter, quarter.selections[1]!, FAKE_NOW)).toBe("quarter");
    const x12 = fakeRows("result.1x2", "FT", "main");
    const arsenal = row(x12, 7822);
    expect(priceBlock(X12, "FT", arsenal, arsenal.selections[0]!, FAKE_NOW)).toBe("outlier");
    expect(priceBlock(X12, "FT", arsenal, arsenal.selections[1]!, FAKE_NOW)).toBeNull();
    const madrid = row(ahRows, 7820);
    expect(priceBlock(AH, "FT", madrid, madrid.selections[0]!, FAKE_NOW + 6 * HOUR)).toBe(
      "started",
    );
  });

  test("another market or period: only to look at; the API's refusal is the last word", () => {
    const corners = info("corners.total", "line", false);
    const r = row(fakeRows("corners.total", "FT", "main"), 7820);
    expect(priceBlock(corners, "FT", r, r.selections[0]!, FAKE_NOW)).toBe("lookup");
    expect(priceBlock(X12, "1H", r, r.selections[0]!, FAKE_NOW)).toBe("lookup");
    expect(marketTakesParlay(corners, "FT")).toBe(false);
    expect(marketTakesParlay(X12, "FT")).toBe(true);
    const madrid = row(ahRows, 7820);
    expect(
      priceBlock(AH, "FT", madrid, { ...madrid.selections[0]!, parlay_ok: false }, FAKE_NOW),
    ).toBe("server");
  });

  test("each block in words", () => {
    expect(blockText("lookup")).toBe("Solo consulta");
    expect(blockText("server")).toBe("Solo consulta");
    expect(blockText("stale")).toBe("Antiguo · no entra al parlay");
    expect(blockText("outlier")).toBe("Los precios atípicos no van en un parlay");
    expect(blockText("quarter")).toContain("no van en un parlay");
    expect(blockText(null)).toBeNull();
  });
});

describe("the leg a price adds", () => {
  test("an Asian handicap's away side at -h, with the price and its bookmaker on show", () => {
    const madrid = row(ahRows, 7820);
    const away = madrid.selections[1]!;
    expect(explorerLeg(AH, "FT", madrid, away, "Bwin")).toEqual({
      fixture_id: 7820,
      market_key: "AH",
      selection: "Away",
      line: "1.5",
      home: "Real Madrid",
      away: "Sevilla",
      kickoff_at: madrid.kickoff_at,
      odds: away.best_odds,
      bookmaker: "Bwin",
      p_model: null,
    });
  });

  test("an over/under at its total; a 1X2 at line 0; another market adds nothing", () => {
    const ou = row(fakeRows("goals.total", "FT", "main"), 7820);
    expect(explorerLeg(OU, "FT", ou, ou.selections[0]!, "Bet365")?.line).toBe("3.5");
    const x12 = row(fakeRows("result.1x2", "FT", "main"), 7820);
    expect(explorerLeg(X12, "FT", x12, x12.selections[1]!, "Bet365")).toMatchObject({
      market_key: "1X2",
      selection: "Draw",
      line: "0",
    });
    const corners = info("corners.total", "line", false);
    expect(explorerLeg(corners, "FT", ou, ou.selections[0]!, "Bet365")).toBeNull();
    expect(explorerLeg(X12, "2H", x12, x12.selections[0]!, "Bet365")).toBeNull();
  });
});

describe("what a screen reader is told", () => {
  const leg = (key: string, selection: string, line: string): SlipLeg => ({
    key,
    fixture_id: 1,
    market_key: "AH",
    selection,
    line,
    home: "Brighton",
    away: "Brentford",
    kickoff_at: new Date(FAKE_NOW + HOUR).toISOString(),
    odds: "1.95",
    bookmaker: "Bet365",
  });
  const a = leg("a", "Away", "0.5");
  const b = leg("b", "Home", "-0.5");

  test("a leg in, a leg out, a leg that replaced another, and the count", () => {
    expect(slipAnnouncement([], [a])).toBe(
      "Agregada: Brentford +0,5 a 1,95. Mi parlay: 1 selección.",
    );
    expect(slipAnnouncement([a, b], [b])).toBe(
      "Quitada: Brentford +0,5 a 1,95. Mi parlay: 1 selección.",
    );
    expect(slipAnnouncement([a], [b])).toBe(
      "Agregada: Brighton -0,5 a 1,95, en lugar de la otra selección de ese partido. Mi parlay: 1 selección.",
    );
    expect(slipAnnouncement([a, b], [])).toBe("Mi parlay: 0 selecciones.");
    expect(slipAnnouncement([a], [a])).toBeNull();
  });
});
