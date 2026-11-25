/// <reference types="bun" />
/**
 * Mi parlay's rule for 1.000 selections, fixed to the byte (PM-13-07, limpieza de restos de la página antigua de Cuotas).
 *
 * The selections come from a seeded generator (no clock, no random source) and cover every market the slip takes plus the
 * catalogue's, whole/half/quarter lines, missing and unit prices, outliers, started and future matches. For each one the
 * test takes `parlayBlock` (why it cannot be added, or null) and `pickableLeg` (the leg it adds) and compares the SHA-256 of
 * the whole result with the one recorded from `main` BEFORE the dead code of the old Odds page was removed. If this test
 * ever fails, Mi parlay's verdict changed: that is a behaviour change and needs its own decision, never a cleanup.
 */
import { createHash } from "node:crypto";
import { describe, expect, test } from "bun:test";
import type { Pickable } from "@/product/records/pickable";
import { normLine } from "@/product/records/model";
import { pickableLeg, parlayBlock, type ParlayCandidate } from "./parlay";

const NOW = Date.parse("2026-10-08T12:00:00Z");

/** A small deterministic generator (mulberry32): the same 1.000 selections on every machine. */
function seeded(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const MARKETS = [
  "1X2",
  "OU",
  "BTTS",
  "AH",
  "DC",
  "CORNERS",
  "result_1x2.FT.match",
  "corners_ou.1H.home",
  "cards_ou.FT.away",
  "Bad Key",
];
const LINES = [
  "0",
  "0.00",
  "-0.25",
  "-0.5",
  "0.75",
  "1",
  "1.5",
  "2.25",
  "2.5",
  "2.75",
  "3",
  "-1.5",
  "abc",
  null,
];
const ODDS = ["2.10", "1.00", "0.95", "1.01", "3.30", "abc", null, undefined, 12, "55.5"];
const KICKOFFS = [
  "2026-10-08T11:00:00Z",
  "2026-10-08T12:00:00Z",
  "2026-10-08T12:00:01Z",
  "2026-10-08T20:00:00Z",
  "2026-10-09T18:30:00Z",
];
const STATUS = [undefined, null, "scheduled", "live", "finished", "postponed"];
const FLAGS = [undefined, null, true, false];

function pick<T>(r: () => number, xs: readonly T[]): T {
  return xs[Math.floor(r() * xs.length)] as T;
}

function selections(n: number): ParlayCandidate[] {
  const r = seeded(20261125);
  const out: ParlayCandidate[] = [];
  for (let i = 0; i < n; i++) {
    out.push({
      market_key: pick(r, MARKETS),
      odds: pick(r, ODDS),
      line: pick(r, LINES),
      kickoff_at: pick(r, KICKOFFS),
      status_group: pick(r, STATUS),
      outlier: pick(r, FLAGS),
      parlay_allowed: pick(r, FLAGS),
    });
  }
  return out;
}

describe("Mi parlay: the verdict and the leg of 1.000 selections do not change", () => {
  const sels = selections(1000);

  test("the generator covers every verdict", () => {
    const seen = new Set(sels.map((s) => parlayBlock(s, NOW)));
    for (const verdict of ["market", "no_price", "outlier", "quarter", "started", null]) {
      expect(seen.has(verdict as never)).toBe(true);
    }
  });

  test("parlayBlock and pickableLeg, byte for byte", () => {
    const rows = sels.map((s, i) => {
      const odds = s.odds === null || s.odds === undefined ? null : String(s.odds);
      const p: Pickable = {
        fixture_id: 1000 + i,
        market_key: s.market_key as Pickable["market_key"],
        selection: i % 3 === 0 ? "Over" : i % 3 === 1 ? "Home" : "Yes",
        line: s.line === null || s.line === undefined ? "0" : s.line,
        kickoff_at: s.kickoff_at,
        status_group: s.status_group,
        home: `Local ${i % 17}`,
        away: `Visita ${i % 13}`,
        odds,
        bookmaker: i % 5 === 0 ? null : `Casa ${i % 7}`,
        p_model: i % 4 === 0 ? "0.4" : null,
        ...(i % 6 === 0 ? { label: "Más de 2,5", market_label: "Goles" } : {}),
      };
      return [parlayBlock(s, NOW), pickableLeg(p), normLine(p.line)];
    });
    const digest = createHash("sha256").update(JSON.stringify(rows)).digest("hex");
    expect(rows.length).toBe(1000);
    expect(digest).toBe("baf2f6a782b418d071c9b3e25c752a2c8689593ef2869986cdb5a9f31326405f");
  });
});
