/// <reference types="bun" />
/**
 * Every code the API can put on a reader's screen has its words, in Spanish and English (plan UX, A1, defects F08
 * and F16: a code without a text showed as itself - "PARTIAL_VOID", "no_value_now" - through translateOr's
 * fallback). The unions are the API's own types, checked complete at compile time; the reasons and the parlay
 * checks are the backend's (api/services/product.py, userdata/records.py), listed here.
 */
import { describe, expect, test } from "bun:test";
import type { AiDecision, CardVerdict } from "@/lib/api/v1/types_ai_layer";
import type { ParlayProgress, ParlayStatus, ResultStatus } from "@/lib/api/v1/types_records";
import { hasKey } from "./index";

/** Compile-time: the array names every member of the union (a member left out is a type error here). */
function all<T extends string>() {
  return <const A extends readonly T[]>(
    values: A & ([Exclude<T, A[number]>] extends [never] ? unknown : never),
  ): readonly T[] => values;
}

const RESULT = all<ResultStatus>()([
  "PENDING",
  "WIN",
  "LOSS",
  "PUSH",
  "VOID",
  "HALF_WIN",
  "HALF_LOSS",
]);
const PARLAY = all<ParlayStatus>()([
  "BUILDING",
  "READY",
  "ACTIVE",
  "WON",
  "LOST",
  "VOID",
  "PARTIAL_VOID",
]);
const PROGRESS = all<ParlayProgress>()([
  "OPEN",
  "PARTIAL_WON",
  "PARTIAL_LOST",
  "WON",
  "LOST",
  "VOID",
]);
const VERDICT = all<CardVerdict>()(["recommended", "caution", "not_recommended", "no_market"]);
const DECISION = all<AiDecision>()(["APPROVE", "DOWNGRADE", "REJECT", "ABSTAIN"]);
/** The reasons of an empty section the product's endpoints send (backend api/services/product.py). */
const EMPTY_REASONS = [
  "no_qualified_picks",
  "no_value_now",
  "no_best_prices",
  "no_live_matches",
  "no_upcoming_matches",
];
/** The checks of a parlay (backend userdata/records.py, validate_parlay). */
const SLIP_ERRORS = [
  "leg_count",
  "invalid_selection",
  "quarter_line",
  "outlier_price",
  "same_fixture",
  "started",
  "unknown_fixture",
];
const SLIP_WARNINGS = ["shared_team", "no_price", "same_competition_day", "very_unlikely"];

const EXPECTED: ReadonlyArray<readonly [string, readonly string[]]> = [
  ["records.status", RESULT],
  ["records.parlayStatus", PARLAY],
  ["records.progress", PROGRESS],
  ["match.analysis.verdict", VERDICT],
  ["match.analysis.decision", DECISION],
  ["markets.reason", EMPTY_REASONS],
  ["records.slip.error", SLIP_ERRORS],
  ["records.slip.warning", SLIP_WARNINGS],
];

describe("every code the API can show a reader has its words", () => {
  for (const locale of ["es", "en"] as const) {
    test(locale, () => {
      const missing = EXPECTED.flatMap(([prefix, codes]) =>
        codes.map((code) => `${prefix}.${code}`).filter((key) => !hasKey(key, locale)),
      );
      expect(missing).toEqual([]);
    });
  }
});
