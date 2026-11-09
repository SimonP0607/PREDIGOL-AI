/// <reference types="bun" />
/**
 * The two lines of why on a reader's pick (plan de Inicio, 2.3): the review's own words when a decision a reader may see
 * has them, the rule's otherwise - written from what the pick stores, never made up.
 */
import { describe, expect, test } from "bun:test";
import { setLocale } from "@/lib/i18n";
import type { DailyItem } from "@/lib/api/v1/types_records";
import { whyLines } from "./cardWhy";

setLocale("es");

function item(ai: DailyItem["ai"] = null): DailyItem {
  return { ai } as DailyItem;
}

describe("the why lines of a pick of the day", () => {
  test("without a review: the value in one line, never filled with something else", () => {
    expect(whyLines(item())).toEqual(["PrediGol ve este resultado más probable que el mercado."]);
  });

  test("a review with a decision lends its first positive and its first risk", () => {
    const ai = {
      decision: "APPROVE" as const,
      mode: "enforce" as const,
      enforced: true,
      positives: ["Llega con cinco partidos sin perder", "Otra"],
      risks: ["Baja del delantero titular", "Otra"],
    };
    expect(whyLines(item(ai))).toEqual([
      "Llega con cinco partidos sin perder",
      "Baja del delantero titular",
    ]);
  });

  test("a review without a decision lends nothing", () => {
    const ai = {
      decision: null,
      mode: "shadow" as const,
      enforced: false,
      positives: ["No debería verse"],
      risks: ["Tampoco"],
    };
    expect(whyLines(item(ai))).toEqual(["PrediGol ve este resultado más probable que el mercado."]);
  });
});
