/// <reference types="bun" />
/**
 * «Añadir a Mi parlay» on a recorded parlay (plan AP-L03): beside what the slip already has, never replacing; what is left
 * out is counted so the screen can say it.
 */
import { describe, expect, test } from "bun:test";
import type { ParlayRecordLeg } from "@/lib/api/v1/types_records";
import { MAX_SLIP_LEGS, selectionKey, type SlipLeg } from "@/product/records/model";
import { addable, mergeParlay } from "./addToSlip";

const NOW = Date.parse("2026-11-23T15:00:00Z");
const HOUR = 3_600_000;

function leg(
  fixture: number,
  over: Partial<ParlayRecordLeg> = {},
  kickoffIn = 5 * HOUR,
  group = "scheduled",
): ParlayRecordLeg {
  return {
    leg_no: fixture,
    pick_id: fixture,
    match: {
      fixture_id: fixture,
      kickoff_at: new Date(NOW + kickoffIn).toISOString(),
      status_group: group,
      home: { id: 1, name: `Local ${fixture}`, logo_url: null },
      away: { id: 2, name: `Visita ${fixture}`, logo_url: null },
    },
    market_key: "1X2",
    selection: "Home",
    line: "0",
    odds: "1.80",
    bookmaker: "Bet365",
    p_model: "0.60",
    ...over,
  } as ParlayRecordLeg;
}

function slipLeg(fixture: number, selection = "Home"): SlipLeg {
  const base = { fixture_id: fixture, market_key: "1X2" as const, selection, line: "0" };
  return {
    ...base,
    key: selectionKey(base),
    home: "L",
    away: "V",
    kickoff_at: new Date(NOW + 5 * HOUR).toISOString(),
    odds: "1.5",
    bookmaker: null,
  };
}

describe("«Añadir a Mi parlay»", () => {
  test("the legs still to be played go in, beside what the slip has", () => {
    const merge = mergeParlay([slipLeg(99)], [leg(1), leg(2)], NOW);
    expect(merge.added).toBe(2);
    expect(merge.legs.map((l) => l.fixture_id)).toEqual([99, 1, 2]);
    expect(merge.legs[1]).toMatchObject({
      fixture_id: 1,
      selection: "Home",
      odds: "1.80",
      bookmaker: "Bet365",
      key: "1|1X2|Home|0",
    });
  });

  test("nothing is replaced and nothing doubles: the same selection stays, another of the same match is not touched", () => {
    const merge = mergeParlay([slipLeg(1), slipLeg(2, "Away")], [leg(1), leg(2), leg(3)], NOW);
    expect(merge).toMatchObject({ added: 1, already: 1, sameMatch: 1 });
    expect(merge.legs.find((l) => l.fixture_id === 2)?.selection).toBe("Away");
  });

  test("a match that has started, or a market the slip does not take, is left out and counted", () => {
    const merge = mergeParlay(
      [],
      [
        leg(1, {}, -HOUR),
        leg(2, {}, 5 * HOUR, "live"),
        leg(3, { market_key: "player.shots" }),
        leg(4),
      ],
      NOW,
    );
    expect(merge).toMatchObject({ added: 1, started: 2, unsupported: 1 });
  });

  test("a full slip takes no more, and says so", () => {
    const full = Array.from({ length: MAX_SLIP_LEGS }, (_, i) => slipLeg(100 + i));
    const merge = mergeParlay(full, [leg(1), leg(2)], NOW);
    expect(merge).toMatchObject({ added: 0, full: 2 });
    expect(merge.legs).toHaveLength(MAX_SLIP_LEGS);
  });

  test("the button exists only while something can still be added", () => {
    expect(addable([], [leg(1)], NOW)).toBe(1);
    expect(addable([slipLeg(1)], [leg(1)], NOW)).toBe(0);
    expect(addable([], [leg(1, {}, -HOUR)], NOW)).toBe(0);
  });
});
