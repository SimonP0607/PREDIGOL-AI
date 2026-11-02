/// <reference types="bun" />
import { describe, expect, test } from "bun:test";
import { hasKey } from "@/lib/i18n";
import type { PlayerNationalCap } from "@/lib/api/v1/types_center";
import { capRecord, capRole, capScore, isCurrent } from "./playerHistory";

const cap = (over: Partial<PlayerNationalCap>): PlayerNationalCap => ({
  fixture_id: 1,
  kickoff_at: "2026-09-01T19:00:00Z",
  team_id: 10,
  team: "Spain",
  opponent_id: 11,
  opponent: "Italy",
  competition: "Friendlies",
  is_starter: true,
  appeared: true,
  minutes: 90,
  goals_for: 2,
  goals_against: 1,
  ...over,
});

describe("capRole", () => {
  test("started, came on, stayed on the bench or waiting for the statistics", () => {
    expect(capRole(cap({}))).toBe("started");
    expect(capRole(cap({ is_starter: false, minutes: 20 }))).toBe("cameOn");
    expect(capRole(cap({ is_starter: false, appeared: false, minutes: null }))).toBe("unused");
    expect(capRole(cap({ appeared: null, minutes: null }))).toBe("waiting");
  });
});

describe("capRecord", () => {
  test("counts what he played, and keeps the entries still waiting apart", () => {
    const rows = [
      cap({ minutes: 90 }),
      cap({ is_starter: false, minutes: 15 }),
      cap({ is_starter: false, appeared: false, minutes: null }),
      cap({ appeared: null, minutes: null }),
    ];
    expect(capRecord(rows)).toEqual({ squads: 4, caps: 2, starts: 1, minutes: 105, waiting: 1 });
    expect(capRecord([])).toEqual({ squads: 0, caps: 0, starts: 0, minutes: 0, waiting: 0 });
  });
});

describe("capScore", () => {
  test("the result from the point of view of his team, null while it is not stored", () => {
    expect(capScore(cap({}))).toBe("2:1");
    expect(capScore(cap({ goals_for: null, goals_against: null }))).toBeNull();
    expect(capScore(cap({ goals_for: 0, goals_against: null }))).toBeNull();
  });
});

describe("isCurrent", () => {
  test("a streak with no end is where he is now", () => {
    expect(isCurrent({ valid_to: null })).toBe(true);
    expect(isCurrent({ valid_to: "2026-01-01" })).toBe(false);
  });
});

describe("texts", () => {
  test("every key the panels build at run time exists in both languages", () => {
    const keys = [
      ...["transfer", "lineup", "squad"].map((x) => `catalog.players.detail.history.source.${x}`),
      ...["started", "cameOn", "unused", "waiting"].map(
        (x) => `catalog.players.detail.history.caps.role.${x}`,
      ),
    ];
    for (const locale of ["es", "en"] as const)
      for (const key of keys)
        expect([locale, key, hasKey(key, locale)]).toEqual([locale, key, true]);
  });
});
