/// <reference types="bun" />
/**
 * PLAN F8, the memory in the Admin Console: what a series says (the numbers every row has and the figures of memory-v4), how far to
 * trust it, what it rests on, and how a day's post-mortems are counted. Both languages.
 */
import { afterAll, describe, expect, test } from "bun:test";
import { hasKey, setLocale } from "@/lib/i18n";
import type { PickPostmortem } from "@/lib/api/v1/types_ai_layer";
import type { IntelMemoryRow } from "@/lib/api/v1/types_intel";
import {
  ASPECTS,
  DASH,
  EVIDENCE_SAMPLE,
  HIGH,
  LOW,
  aspectLabel,
  confidenceText,
  confidenceTone,
  detailOf,
  evidenceParts,
  figureText,
  recordText,
  sampleOf,
  summarize,
} from "./memoryText";

afterAll(() => setLocale("es"));

function row(over: Partial<IntelMemoryRow>): IntelMemoryRow {
  return {
    entity_type: "team",
    entity_id: "1",
    entity_name: "Alpha",
    aspect: "corners",
    as_of_day: "2026-10-20",
    version: "memory-v4",
    stats: {},
    delta: {},
    confidence: 0.5,
    evidence_ref: null,
    ...over,
  };
}

describe("confidence", () => {
  test("a series from before memory-v4 says it has none, and is not coloured as a pattern", () => {
    setLocale("en");
    expect(confidenceText(null)).toBe("none");
    expect(confidenceTone(null)).toBe("neutral");
  });

  test("below the low mark it is a hint, from the high mark a pattern", () => {
    setLocale("en");
    expect(confidenceTone(LOW - 0.01)).toBe("warning");
    expect(confidenceTone(LOW)).toBe("info");
    expect(confidenceTone(HIGH - 0.01)).toBe("info");
    expect(confidenceTone(HIGH)).toBe("positive");
    expect(confidenceText(0.6283)).toMatch(/^63\s?%$/);
  });
});

describe("the sample of a series", () => {
  test("decisions, then matches, then reports of a player", () => {
    expect(sampleOf({ stats: { decisions: 12, matches: 99 } })).toBe(12);
    expect(sampleOf({ stats: { matches: 7 } })).toBe(7);
    expect(sampleOf({ stats: { reported_out: 4 } })).toBe(4);
    expect(sampleOf({ stats: { wins: 1 } })).toBeNull();
  });

  test("the record is wins / losses / voids, or a dash for a series that settles nothing", () => {
    expect(recordText({ stats: { wins: 5, losses: 3, voids: 1 } })).toBe("5 / 3 / 1");
    expect(recordText({ stats: { wins: 2 } })).toBe("2 / 0 / 0");
    expect(recordText({ stats: { matches: 7 } })).toBe(DASH);
  });
});

describe("the figures of memory-v4 (corners, cards, expected goals)", () => {
  test("a team's figure is shown shrunk toward its league's, with the league's for comparison", () => {
    setLocale("en");
    const text = figureText({
      entity_type: "team",
      stats: { own_rate: 6.1, opp_rate: 4.2, own_shrunk: 5.8, opp_shrunk: 4.9, prior: 5.1 },
    });
    expect(text).toBe("own 5.80, rivals 4.90 per match (league 5.10)");
  });

  test("with no league figure yet it says so and shows the team's own", () => {
    setLocale("en");
    const text = figureText({ entity_type: "team", stats: { own_rate: 6.1, opp_rate: 4.2 } });
    expect(text).toBe("own 6.10, rivals 4.20 per match (no league figure yet)");
  });

  test("a league is its mean per team and match; nothing known is a dash", () => {
    setLocale("en");
    expect(figureText({ entity_type: "competition", stats: { rate: 5.0123 } })).toBe(
      "5.01 per team per match",
    );
    expect(figureText({ entity_type: "competition", stats: {} })).toBe(DASH);
    expect(figureText({ entity_type: "team", stats: {} })).toBe(DASH);
  });

  test("Spanish uses the decimal comma", () => {
    setLocale("es");
    expect(
      figureText({ entity_type: "team", stats: { own_shrunk: 5.8, opp_shrunk: 4.9, prior: 5.1 } }),
    ).toBe("propios 5,80, del rival 4,90 por partido (liga 5,10)");
  });
});

describe("the detail of the other kinds of series", () => {
  test("referee, coach and player", () => {
    setLocale("en");
    expect(
      detailOf({
        entity_type: "referee",
        aspect: "discipline",
        stats: { cards_per_match: 4.256, fouls_per_match: 24.04 },
      }),
    ).toBe("4.26 cards and 24.0 fouls per match");
    expect(
      detailOf({
        entity_type: "coach",
        aspect: "profile",
        stats: { wins: 5, draws: 2, losses: 1, formations: { "4-3-3": 4, "4-4-2": 3, "3-5-2": 1 } },
      }),
    ).toBe("5W 2D 1L · 4-3-3, 4-4-2");
    expect(
      detailOf({
        entity_type: "player",
        aspect: "availability",
        stats: { started_anyway: 2, reported_out: 5 },
      }),
    ).toBe("2 of 5 reported out played");
    expect(detailOf({ entity_type: "market", aspect: "decisions", stats: {} })).toBe(DASH);
  });
});

describe("what a series rests on", () => {
  test("matches, or the decisions and the post-mortems that judged them; nothing before memory-v4", () => {
    setLocale("en");
    expect(evidenceParts(null)).toEqual([]);
    expect(evidenceParts({})).toEqual([]);
    const parts = evidenceParts({ decisions: [9, 8, 7], postmortems: [3] });
    expect(parts.map((p) => p.text)).toEqual(["3 decisions", "1 post-mortem"]);
    expect(parts.every((p) => !p.sample)).toBe(true);
    expect(evidenceParts({ fixtures: [5] })[0]?.text).toBe("1 match");
  });

  test("the memory keeps the newest 40 ids of a kind: a full list is a sample, not the count", () => {
    const ids = Array.from({ length: EVIDENCE_SAMPLE }, (_, i) => 1000 - i);
    const part = evidenceParts({ fixtures: ids })[0];
    expect(part?.sample).toBe(true);
    expect(part?.ids).toHaveLength(EVIDENCE_SAMPLE);
  });
});

describe("the aspects a filter offers", () => {
  test("each one has a label in both languages, or is shown as it is written (a market)", () => {
    for (const locale of ["es", "en"] as const) {
      setLocale(locale);
      for (const a of ASPECTS) {
        if (a.startsWith("market:")) expect(aspectLabel(a)).toBe(a);
        else expect(hasKey(`memory.entities.aspects.${a}`, locale)).toBe(true);
      }
    }
  });
});

describe("the day's post-mortems", () => {
  const pm = (verdict: string, classification: string | null): PickPostmortem =>
    ({ verdict, classification }) as PickPostmortem;

  test("verdicts and classes of a loss are counted, the most frequent first", () => {
    const { verdicts, classes } = summarize([
      pm("variance", "VARIANCE"),
      pm("variance", null),
      pm("deserved", null),
      pm("variance", "MARKET_ERROR"),
      pm("variance", "VARIANCE"),
    ]);
    expect(verdicts).toEqual([
      ["variance", 4],
      ["deserved", 1],
    ]);
    expect(classes).toEqual([
      ["VARIANCE", 2],
      ["MARKET_ERROR", 1],
    ]);
    expect(summarize([])).toEqual({ verdicts: [], classes: [] });
  });
});
