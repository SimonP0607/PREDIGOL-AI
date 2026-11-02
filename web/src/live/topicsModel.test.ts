/// <reference types="bun" />
/**
 * The "Por entidad y tema" view of Operación (plan IA, phase 2): the verdicts the page draws from its figures. What the owner should look at comes
 * most serious first and empty when there is nothing; `on` asked and not in force is held, not on; a gate that cannot be judged yet is a lack of time
 * and not a failure; the vocabularies the page counts by keep the order of the code that writes them and never hide a word they do not know.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { setLocale } from "@/lib/i18n";
import type { ResearchDay, ResearchWord } from "@/lib/api/v1/types_ai_research";
import {
  CLAIM_STATUSES,
  CLAIM_TYPES,
  CLASS_TONE,
  ENTITY_KINDS,
  GATE_CHECKS,
  MODES,
  PREVIEW_FIGURES,
  SERIOUS,
  SOURCE_CLASSES,
  STATUS_TONE,
  SWITCH_TONE,
  TIERS,
  TOPICS,
  VERDICTS,
  WORD_TONE,
  answerKey,
  attention,
  checkTone,
  dayTotals,
  detailPairs,
  entityName,
  failing,
  figureText,
  freshShare,
  hoursText,
  markKey,
  missedLine,
  pctText,
  previewFigures,
  reuseShare,
  silentClasses,
  statusCells,
  switchState,
  tierCounts,
  usedStatuses,
  verdictKey,
  verdictTone,
  type Looked,
} from "./topicsModel";

afterEach(() => setLocale("es"));

function day(over: Partial<ResearchDay> = {}): ResearchDay {
  return {
    day: "2026-10-25",
    passes: 4,
    passes_v2: 4,
    passes_failed: 0,
    passes_cut: 0,
    searches: 6,
    demand: 3,
    paid: 2,
    shared: 1,
    reused: 5,
    pages: 7,
    pages_known: 2,
    claims: 9,
    claims_new: 4,
    exa_v1_usd: "0.0300",
    exa_v2_usd: "0.0100",
    ...over,
  };
}

/** A system with nothing to look at: both parts computed, v2 ran, nothing failed, nothing flagged. */
function quiet(over: Partial<Looked> = {}): Looked {
  return {
    comparison: { status: "ok" },
    gate: { status: "ok" },
    per_day: [day()],
    switch: { asked: "shadow", mode: "shadow" },
    claims: { flagged: 0 },
    pages: { flagged: 0 },
    freshness: { unreadable: 0 },
    ...over,
  };
}

describe("the vocabularies the page counts by", () => {
  test("the owner's words for the switch, from the least trusted to the most", () => {
    expect([...MODES]).toEqual(["off", "shadow", "on"]);
    expect(Object.keys(WORD_TONE)).toEqual([...MODES]);
  });

  test("the topics of the research, in the code's order, and what an answer can be about", () => {
    expect([...TOPICS]).toEqual(["availability", "confirmation", "preview"]);
    expect([...ENTITY_KINDS]).toEqual([
      "TEAM",
      "PLAYER",
      "COACH",
      "REFEREE",
      "MATCH",
      "COMPETITION",
    ]);
  });

  test("a claim ends in one of five states, from the surest to the oldest", () => {
    expect([...CLAIM_STATUSES]).toEqual([
      "CONFIRMED",
      "PROBABLE",
      "RUMOR",
      "CONTRADICTORY",
      "OUTDATED",
    ]);
    expect(Object.keys(STATUS_TONE)).toEqual([...CLAIM_STATUSES]);
  });

  test("eight classes of source, from the one that settles a fact to the one that settles none", () => {
    expect([...SOURCE_CLASSES]).toEqual([
      "OFFICIAL",
      "PROVIDER",
      "JOURNALIST",
      "RELIABLE_MEDIA",
      "LOCAL_MEDIA",
      "AGGREGATOR",
      "SOCIAL",
      "UNKNOWN",
    ]);
    expect(Object.keys(CLASS_TONE)).toEqual([...SOURCE_CLASSES]);
  });

  test("nine types of claim and nine tiers of a domain", () => {
    expect([...CLAIM_TYPES]).toEqual([
      "OUT",
      "DOUBT",
      "AVAILABLE",
      "STARTER",
      "SUSPENSION",
      "COACH",
      "SCHEDULE",
      "VENUE",
      "OTHER",
    ]);
    expect([...TIERS]).toEqual([
      "official",
      "competition",
      "club",
      "provider",
      "journalist",
      "media",
      "aggregator",
      "social",
      "unknown",
    ]);
  });

  test("the gate judges seven checks in this order, and has three verdicts in its own words", () => {
    expect([...GATE_CHECKS]).toEqual([
      "window",
      "fewer_searches",
      "coverage",
      "coverage_players",
      "shadow_invisible",
      "evidence_known",
      "sample",
    ]);
    expect([...VERDICTS]).toEqual(["PASA", "NO PASA", "PENDIENTE POR TIEMPO REAL"]);
  });
});

describe("the switch", () => {
  test("what was asked is what is in force, except `on` before the gate has passed: that is held", () => {
    const cases: Array<[ResearchWord, ResearchWord, string]> = [
      ["off", "off", "off"],
      ["shadow", "shadow", "shadow"],
      ["on", "on", "on"],
      ["on", "shadow", "held"],
      ["on", "off", "held"],
    ];
    for (const [asked, mode, state] of cases) {
      expect(switchState({ asked, mode })).toBe(state as ReturnType<typeof switchState>);
    }
  });

  test("a switch asked for shadow is never held, whatever the cycle does", () => {
    expect(switchState({ asked: "shadow", mode: "off" })).toBe("off");
    expect(switchState({ asked: "off", mode: "shadow" })).toBe("shadow");
  });

  test("every state has a tone, and a held switch is a warning, not an alarm", () => {
    expect(Object.keys(SWITCH_TONE).sort()).toEqual(["held", "off", "on", "shadow"]);
    expect(SWITCH_TONE.held).toBe("warning");
    expect(SWITCH_TONE.on).toBe("positive");
    expect(SWITCH_TONE.off).toBe("neutral");
  });
});

describe("the verdict of the gate", () => {
  test("a pass is positive, a failure is negative and a lack of time is a warning, never a failure", () => {
    expect(verdictTone("PASA")).toBe("positive");
    expect(verdictTone("NO PASA")).toBe("negative");
    expect(verdictTone("PENDIENTE POR TIEMPO REAL")).toBe("warning");
  });

  test("a verdict this page does not know is a warning and is shown as the server wrote it", () => {
    expect(verdictTone("QUIZÁ")).toBe("warning");
    expect(verdictKey("QUIZÁ")).toBe("unknown");
    expect(verdictKey("pasa")).toBe("unknown");
  });

  test("each verdict is read by a word the catalog translates", () => {
    expect(verdictKey("PASA")).toBe("pass");
    expect(verdictKey("NO PASA")).toBe("fail");
    expect(verdictKey("PENDIENTE POR TIEMPO REAL")).toBe("pending");
  });

  test("a check holds, does not, or cannot be judged yet - and that last one is not a failure", () => {
    expect(markKey(true)).toBe("yes");
    expect(markKey(false)).toBe("no");
    expect(markKey(null)).toBe("pending");
    expect(checkTone(true)).toBe("positive");
    expect(checkTone(false)).toBe("negative");
    expect(checkTone(null)).toBe("warning");
  });

  test("the checks that failed are the ones with `ok` false, not the ones still pending", () => {
    expect(
      failing([
        { id: "window", ok: true },
        { id: "coverage", ok: false },
        { id: "sample", ok: null },
        { id: "fewer_searches", ok: false },
      ]),
    ).toEqual(["coverage", "fewer_searches"]);
    expect(failing([])).toEqual([]);
  });
});

describe("what to look at", () => {
  test("a system with nothing wrong says nothing", () => {
    expect(attention(quiet())).toEqual([]);
  });

  test("the only code that is a fault of ours is a part of the page that could not be computed", () => {
    expect([...SERIOUS]).toEqual(["part_unavailable"]);
  });

  test("parts of the page that could not be computed are counted, whichever they are", () => {
    expect(attention(quiet({ comparison: { status: "not_available" } }))).toEqual([
      { code: "part_unavailable", n: 1 },
    ]);
    expect(
      attention(
        quiet({ comparison: { status: "not_available" }, gate: { status: "not_available" } }),
      ),
    ).toEqual([{ code: "part_unavailable", n: 2 }]);
  });

  test("an empty or insufficient section is not a fault: only `not_available` is", () => {
    expect(attention(quiet({ comparison: { status: "empty" } }))).toEqual([]);
    expect(attention(quiet({ gate: { status: "insufficient_data" } }))).toEqual([]);
  });

  test("passes that failed or were cut short are added up over the days", () => {
    const days = [
      day({ day: "2026-10-25", passes_failed: 1, passes_cut: 0 }),
      day({ day: "2026-10-24", passes_failed: 2, passes_cut: 3 }),
      day({ day: "2026-10-23", passes_failed: 0, passes_cut: 1 }),
    ];
    expect(attention(quiet({ per_day: days }))).toEqual([
      { code: "v2_failed", n: 3 },
      { code: "v2_cut", n: 4 },
    ]);
  });

  test("a switch that is not off, with no pass that ran v2, is a switch nobody obeys", () => {
    const none = [day({ passes: 3, passes_v2: 0 })];
    expect(attention(quiet({ per_day: none }))).toEqual([{ code: "not_running", n: 1 }]);
    expect(attention(quiet({ per_day: none, switch: { asked: "off", mode: "off" } }))).toEqual([]);
    expect(attention(quiet({ per_day: [] }))).toEqual([{ code: "not_running", n: 1 }]);
  });

  test("`on` asked and held as shadow is a thing to look at, once", () => {
    expect(attention(quiet({ switch: { asked: "on", mode: "shadow" } }))).toEqual([
      { code: "held_as_shadow", n: 1 },
    ]);
    expect(attention(quiet({ switch: { asked: "on", mode: "on" } }))).toEqual([]);
  });

  test("claims and pages that read like an order to a model, and rows of the cache nobody reads, are counted", () => {
    expect(
      attention(
        quiet({
          claims: { flagged: 4 },
          pages: { flagged: 2 },
          freshness: { unreadable: 7 },
        }),
      ),
    ).toEqual([
      { code: "claims_flagged", n: 4 },
      { code: "pages_flagged", n: 2 },
      { code: "unreadable", n: 7 },
    ]);
  });

  test("everything at once comes most serious first", () => {
    const all = attention({
      comparison: { status: "not_available" },
      gate: { status: "ok" },
      per_day: [day({ passes_v2: 0, passes_failed: 2, passes_cut: 1 })],
      switch: { asked: "on", mode: "shadow" },
      claims: { flagged: 1 },
      pages: { flagged: 1 },
      freshness: { unreadable: 1 },
    });
    expect(all.map((a) => a.code)).toEqual([
      "part_unavailable",
      "v2_failed",
      "v2_cut",
      "not_running",
      "held_as_shadow",
      "claims_flagged",
      "pages_flagged",
      "unreadable",
    ]);
  });
});

describe("hours, shares and keys", () => {
  test("hours are written as the rules of the cache are: whole, or with one decimal", () => {
    expect(hoursText(24)).toBe("24 h");
    expect(hoursText(4)).toBe("4 h");
    expect(hoursText(1.5)).toBe("1,5 h");
    setLocale("en");
    expect(hoursText(1.5)).toBe("1.5 h");
  });

  test("the fresh share of a topic is fresh over kept, and none when nothing is kept", () => {
    expect(freshShare({ entries: 4, fresh: 3 })).toBe(0.75);
    expect(freshShare({ entries: 5, fresh: 0 })).toBe(0);
    expect(freshShare({ entries: 0, fresh: 0 })).toBeNull();
  });

  test("the reuse share is reused over everything v2 needed, and none when it needed nothing", () => {
    expect(reuseShare({ reused: 6, demand: 2 })).toBe(0.75);
    expect(reuseShare({ reused: 0, demand: 3 })).toBe(0);
    expect(reuseShare({ reused: 4, demand: 0 })).toBe(1);
    expect(reuseShare({ reused: 0, demand: 0 })).toBeNull();
  });

  test("an answer is told from another by its entity and its topic: the same id can be a team and a player", () => {
    expect(answerKey({ kind: "TEAM", id: 1, topic: "availability" })).toBe("TEAM:1:availability");
    expect(answerKey({ kind: "PLAYER", id: 1, topic: "availability" })).not.toBe(
      answerKey({ kind: "TEAM", id: 1, topic: "availability" }),
    );
    expect(answerKey({ kind: "TEAM", id: 1, topic: "confirmation" })).not.toBe(
      answerKey({ kind: "TEAM", id: 1, topic: "availability" }),
    );
  });

  test("an entity is named by what the server named it, else by its number - never guessed", () => {
    expect(entityName({ kind: "TEAM", id: 7, name: "Liverpool" })).toBe("Liverpool");
    expect(entityName({ kind: "PLAYER", id: 7, name: null })).toBe("#7");
  });
});

describe("the counts of a row", () => {
  test("the results of an answer come by tier in the order of the tiers, then any tier the page does not know", () => {
    expect(tierCounts({ tiers: { media: 3, official: 1, zeta: 2, alpha: 1, club: 4 } })).toEqual([
      ["official", 1],
      ["club", 4],
      ["media", 3],
      ["alpha", 1],
      ["zeta", 2],
    ]);
    expect(tierCounts({ tiers: {} })).toEqual([]);
  });

  test("a row of the claims tables has a cell for every state, in the order of the states, zero where nothing was counted", () => {
    expect(statusCells({ by_status: { RUMOR: 2, CONFIRMED: 5 } })).toEqual([
      ["CONFIRMED", 5],
      ["PROBABLE", 0],
      ["RUMOR", 2],
      ["CONTRADICTORY", 0],
      ["OUTDATED", 0],
    ]);
  });

  test("a state the page does not know is a cell too, after the known ones", () => {
    expect(statusCells({ by_status: { CONFIRMED: 1, WITHDRAWN: 3 } }).slice(-1)).toEqual([
      ["WITHDRAWN", 3],
    ]);
  });

  test("a column nobody used is not drawn: the states with something in them, in the order of the states", () => {
    expect(
      usedStatuses([
        { by_status: { RUMOR: 1, CONFIRMED: 0 } },
        { by_status: { CONFIRMED: 0, OUTDATED: 2 } },
      ]),
    ).toEqual(["RUMOR", "OUTDATED"]);
    expect(usedStatuses([{ by_status: { CONFIRMED: 0 } }])).toEqual([]);
    expect(usedStatuses([])).toEqual([]);
  });

  test("a state the page does not know is drawn too, once everything it knows has been", () => {
    expect(
      usedStatuses([{ by_status: { ZEBRA: 1, CONFIRMED: 2 } }, { by_status: { ALPHA: 4 } }]),
    ).toEqual(["CONFIRMED", "ALPHA", "ZEBRA"]);
  });

  test("the classes of source that wrote nothing are a finding, named in the order given", () => {
    expect(
      silentClasses([
        { key: "OFFICIAL", total: 2 },
        { key: "PROVIDER", total: 0 },
        { key: "SOCIAL", total: 0 },
      ]),
    ).toEqual(["PROVIDER", "SOCIAL"]);
    expect(silentClasses([{ key: "OFFICIAL", total: 1 }])).toEqual([]);
  });
});

describe("the days added up", () => {
  test("every count is the sum of the days, and the money is the sum of the dollars the server sent as text", () => {
    const total = dayTotals([
      day({ day: "2026-10-25" }),
      day({
        day: "2026-10-24",
        passes: 1,
        passes_v2: 1,
        passes_failed: 1,
        passes_cut: 2,
        searches: 1,
        demand: 1,
        paid: 1,
        shared: 0,
        reused: 0,
        pages: 1,
        pages_known: 0,
        claims: 1,
        claims_new: 1,
        exa_v1_usd: "0.0050",
        exa_v2_usd: "0.0070",
      }),
    ]);
    const { exa_v1_usd: v1, exa_v2_usd: v2, ...counts } = total;
    expect(counts).toEqual({
      passes: 5,
      passes_v2: 5,
      passes_failed: 1,
      passes_cut: 2,
      searches: 7,
      demand: 4,
      paid: 3,
      shared: 1,
      reused: 5,
      pages: 8,
      pages_known: 2,
      claims: 10,
      claims_new: 5,
    });
    expect(v1).toBe(0.035);
    expect(v2).toBe(0.017);
  });

  test("no days add up to zero, and a figure that is not a number counts as none", () => {
    const zero = dayTotals([]);
    expect(zero.passes).toBe(0);
    expect(zero.exa_v1_usd).toBe(0);
    expect(dayTotals([day({ exa_v1_usd: "n/a", exa_v2_usd: "" })]).exa_v1_usd).toBe(0);
  });

  test("the reuse of the total is the reuse of its sums, not the mean of the days", () => {
    const days = [day({ reused: 9, demand: 1 }), day({ reused: 0, demand: 9 })];
    const mean = ((reuseShare(days[0]!) ?? 0) + (reuseShare(days[1]!) ?? 0)) / 2;
    expect(mean).toBeCloseTo(0.45, 10);
    expect(reuseShare(dayTotals(days))).toBeCloseTo(9 / 19, 10);
  });
});

describe("figures in the reader's language", () => {
  test("a percentage the server sent as text (50.00 = fifty percent) is written in Spanish and in English", () => {
    expect(pctText("50.00")).toBe("50,0 %");
    expect(pctText("33.33")).toBe("33,3 %");
    expect(pctText("100.00", 0)).toBe("100 %");
    setLocale("en");
    expect(pctText("50.00")).toBe("50.0%");
    expect(pctText("0.00")).toBe("0.0%");
  });

  test("a percentage that could not be computed is a dash, never a zero", () => {
    for (const none of [null, undefined, "", "n/a"]) expect(pctText(none)).toBe("—");
    expect(pctText("0.00")).not.toBe("—");
  });

  test("a figure the server sent is written with the decimal mark of the reader", () => {
    expect(figureText(4)).toBe("4");
    expect(figureText("2.50")).toBe("2,50");
    expect(figureText(null)).toBe("—");
    expect(figureText(undefined)).toBe("—");
    expect(figureText("")).toBe("—");
    setLocale("en");
    expect(figureText("2.50")).toBe("2.50");
  });

  test("a fact of v1 that v2 did not find is one line", () => {
    expect(missedLine([9370001, "home", "Marcus Rashford", "OUT"])).toBe(
      "9370001 · home · Marcus Rashford · OUT",
    );
    expect(missedLine([])).toBe("");
    expect(missedLine([null, 3])).toBe("null · 3");
  });
});

describe("the detail of a check", () => {
  test("a scalar is shown as it is, a missing value as a dash, anything else as JSON", () => {
    expect(
      detailPairs({ days_audited: 6, note: "late", ok: true, none: null, list: [1, 2] }),
    ).toEqual([
      ["days_audited", "6"],
      ["note", "late"],
      ["ok", "true"],
      ["none", "—"],
      ["list", "[1,2]"],
    ]);
  });

  test("the first dozen pairs, so that one check cannot take the page", () => {
    const many = Object.fromEntries(Array.from({ length: 30 }, (_, i) => [`k${i}`, i]));
    expect(detailPairs(many)).toHaveLength(12);
    expect(detailPairs(many, 3).map(([k]) => k)).toEqual(["k0", "k1", "k2"]);
    expect(detailPairs({})).toEqual([]);
  });

  test("a long structure is cut to a line, with the cut marked", () => {
    const [pair] = detailPairs({ missed_examples: Array.from({ length: 80 }, (_, i) => [i, "x"]) });
    expect(pair?.[1].endsWith("…")).toBe(true);
    expect(pair?.[1].length).toBe(121);
    const [short] = detailPairs({ a: "x".repeat(300) });
    expect(short?.[1].length).toBe(300);
  });
});

describe("what the days gone show while the verdict is pending", () => {
  const preview = {
    note: "NOT evidence of the gate: only what the days gone show",
    stable_complete_days: 2,
    searches: {
      passes_compared: 8,
      searches_v1: 20,
      searches_v2_alone: 12,
      saved_pct: "40.00",
      reuse_pct: "55.50",
      saved: 8,
    },
    coverage: {
      fixtures: 14,
      facts_v1: 30,
      facts_v2: 29,
      coverage_pct: "96.67",
      coverage_players_pct: null,
      missed_examples: [[1, "home", "x", "OUT"]],
    },
  };

  test("a few named figures, read out of the free-form record, in the order the page lists them", () => {
    expect(previewFigures(preview).map((f) => `${f.group}.${f.key}`)).toEqual([
      "searches.passes_compared",
      "searches.searches_v1",
      "searches.searches_v2_alone",
      "searches.saved_pct",
      "searches.reuse_pct",
      "coverage.fixtures",
      "coverage.facts_v1",
      "coverage.facts_v2",
      "coverage.coverage_pct",
    ]);
  });

  test("a figure that is not a number or a text is left out: a null is not a zero", () => {
    const keys = previewFigures(preview).map((f) => f.key);
    expect(keys).not.toContain("coverage_players_pct");
    expect(keys).not.toContain("saved");
    expect(keys).not.toContain("missed_examples");
  });

  test("numbers and texts come through as text, and the percentages are the server's own", () => {
    const byKey = Object.fromEntries(previewFigures(preview).map((f) => [f.key, f.value]));
    expect(byKey["passes_compared"]).toBe("8");
    expect(byKey["saved_pct"]).toBe("40.00");
  });

  test("with no days gone there is nothing to show, and a part that is not an object is skipped", () => {
    expect(previewFigures({})).toEqual([]);
    expect(previewFigures({ note: "x", stable_complete_days: 0 })).toEqual([]);
    expect(previewFigures({ searches: null, coverage: 4 })).toEqual([]);
    expect(PREVIEW_FIGURES).toHaveLength(10);
  });
});
