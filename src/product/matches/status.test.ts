/// <reference types="bun" />
/**
 * One answer to "what state is this match in?" in the web, the same as the API's
 * (fbi.core.match_state): every provider code, the time guard, and nothing that was not
 * played to the end ever reading "Final".
 */
import { describe, expect, test } from "bun:test";
import type { MatchPhase } from "@/lib/api/v1/types";
import { hasKey, setLocale } from "@/lib/i18n";
import {
  isInPlay,
  isLivePhase,
  isOffPhase,
  LIVE_STALE_MS,
  matchPhaseOf,
  phaseOf,
  START_GRACE_MS,
} from "./status";

const KO = "2026-10-09T18:00:00Z";
const ko = Date.parse(KO);

const EXPECTED: Record<string, MatchPhase> = {
  TBD: "scheduled",
  NS: "scheduled",
  "1H": "live",
  HT: "live",
  "2H": "live",
  ET: "live",
  BT: "live",
  P: "live",
  LIVE: "live",
  INT: "live",
  SUSP: "suspended",
  FT: "finished",
  AET: "finished",
  PEN: "finished",
  PST: "postponed",
  CANC: "cancelled",
  ABD: "abandoned",
  AWD: "not_played",
  WO: "not_played",
};

describe("the canonical phase", () => {
  test("every provider code has the API's phase", () => {
    for (const [code, phase] of Object.entries(EXPECTED)) {
      expect(matchPhaseOf(code, KO, ko + 60_000)).toBe(phase);
      expect(matchPhaseOf(code.toLowerCase(), KO, ko + 60_000)).toBe(phase);
    }
  });

  test("the API's phase wins when it sent one", () => {
    expect(matchPhaseOf("NS", KO, ko + 2 * 3_600_000, "live")).toBe("live");
  });

  test("a stale scheduled or live code is not believed; a suspension is never timed out", () => {
    expect(matchPhaseOf("NS", KO, ko + START_GRACE_MS - 1)).toBe("scheduled");
    expect(matchPhaseOf("NS", KO, ko + START_GRACE_MS)).toBe("awaiting");
    expect(matchPhaseOf("2H", KO, ko + LIVE_STALE_MS - 1)).toBe("live");
    expect(matchPhaseOf("HT", KO, ko + LIVE_STALE_MS)).toBe("awaiting");
    expect(matchPhaseOf("SUSP", KO, ko + 48 * 3_600_000)).toBe("suspended");
    expect(matchPhaseOf(null, KO, ko)).toBe("unknown");
  });

  test("live, off and in play agree", () => {
    expect(isLivePhase("live") && isLivePhase("suspended")).toBe(true);
    expect(isLivePhase("finished")).toBe(false);
    for (const p of ["postponed", "cancelled", "abandoned", "not_played"] as const) {
      expect(isOffPhase(p)).toBe(true);
    }
    expect(isOffPhase("finished")).toBe(false);
    for (const code of ["PST", "CANC", "ABD", "AWD", "WO"]) {
      expect(phaseOf(code)).toBe("off");
      expect(isInPlay(code)).toBe(false);
    }
    for (const code of ["FT", "AET", "PEN"]) expect(phaseOf(code)).toBe("over");
    expect(isInPlay("SUSP") && isInPlay("INT")).toBe(true);
  });

  test("every state has a label in both languages, and none of the off ones is Final", () => {
    for (const locale of ["es", "en"] as const) {
      setLocale(locale);
      for (const code of ["AET", "PEN", "PST", "CANC", "ABD", "AWD", "WO", "NS"]) {
        expect(hasKey(`matches.clock.${code}`)).toBe(true);
      }
      for (const phase of ["suspended", "abandoned", "not_played", "postponed", "cancelled"]) {
        expect(hasKey(`common.status.${phase}`)).toBe(true);
        expect(hasKey(`records.matchState.${phase}`)).toBe(true);
      }
      expect(hasKey("records.matchState.settling")).toBe(true);
    }
    setLocale("es");
  });
});
