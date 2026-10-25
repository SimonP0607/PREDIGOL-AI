/// <reference types="bun" />
/**
 * The Agentes tab of Operación (plan IA, phase 1): the verdicts the page draws from its figures. A slice is judged against its cap, an audit rule
 * that never ran is not a clean one, an agent is in sync only when it has code to compare, and what the owner should look at comes most serious
 * first and empty when there is nothing.
 */
import { describe, expect, test } from "bun:test";
import type {
  AgentView,
  AgentsOverview,
  AuditRule,
  MatchStateRow,
  SliceStat,
} from "@/lib/api/v1/types_ai_agents";
import {
  AUDIT_TONE,
  NEAR_CAP,
  PASSES,
  RUN_STATUSES,
  SLICE_TONE,
  TASK_STATES,
  attention,
  auditVerdict,
  capShare,
  decisionChange,
  orderedCounts,
  promotionLine,
  registryCounts,
  sliceLevel,
  slicesOver,
  syncState,
  taskLine,
  totalTokens,
} from "./agentsModel";

function slice(over: Partial<SliceStat> = {}): SliceStat {
  return {
    name: "match",
    states: 10,
    tokens_p50: 4000,
    tokens_p95: 9000,
    tokens_max: 11000,
    cap: 18000,
    trimmed: 0,
    over_cap: 0,
    ...over,
  };
}

function agent(over: Partial<AgentView> = {}): AgentView {
  return {
    agent: "reviewer",
    status: "built",
    purpose: "reviews a pick",
    contract: "review-v2",
    reads: null,
    version: "review-v2",
    fingerprint: "ag0123456789",
    born_as: "CHAMPION",
    baseline: true,
    registered_at: "2026-10-25T00:00:00Z",
    in_sync: true,
    retire_phase: null,
    next_version: null,
    next_phase: null,
    phase: null,
    replaces: null,
    gate: null,
    history: ["review-v2"],
    tasks: [],
    ...over,
  };
}

function rule(over: Partial<AuditRule> = {}): AuditRule {
  return { rule: "slice_known", days: [], days_audited: 3, checked: 120, violations: 0, ...over };
}

function overview(over: Partial<AgentsOverview> = {}): AgentsOverview {
  return {
    registry: [agent(), agent({ agent: "brief", version: "brief-v8" })],
    problems: [],
    families: [],
    decisions: [],
    package: {
      days: 7,
      since: "2026-10-18T12:00:00Z",
      states: 40,
      matches: 20,
      by_pass: { first: 20, pre: 20 },
      blocked: 0,
      flagged: 0,
      slices: [slice()],
      build_ms: { p50: 120, p95: 300, max: 410 },
      per_day: [],
      cycles: { total: 5, ok: 5, partial: 0, failed: 0, running: 0, last: null },
      rule: {
        state_version: "ms-v1",
        package_version: "package-v1",
        window_days: 4,
        limit: 200,
        max_seconds: 90,
      },
    },
    queue: { days: 7, tasks: {}, runs: {}, open: 0, reserved_usd: "0" },
    audit: [rule()],
    settings: { mode: "shadow", package: true },
    ...over,
  };
}

function cycle(status: string) {
  return {
    id: 1,
    kind: "package",
    started_at: "2026-10-25T12:00:00Z",
    finished_at: "2026-10-25T12:01:00Z",
    status,
    mode: "shadow",
    budget_state: "NORMAL",
    counts: {},
    cost_usd: "0",
    error: null,
  };
}

describe("the vocabularies the page counts by", () => {
  test("a task is born planned and ends in one of four words; an attempt ends in one of seven", () => {
    expect([...TASK_STATES]).toEqual([
      "planned",
      "queued",
      "running",
      "done",
      "failed",
      "skipped",
      "expired",
    ]);
    expect([...RUN_STATUSES]).toEqual([
      "ok",
      "invalid",
      "timeout",
      "abstain",
      "skipped",
      "expired",
      "budget_skip",
    ]);
    expect([...PASSES]).toEqual(["first", "pre", "final", "request"]);
  });

  test("the counts come in the order of the vocabulary, not the order the server wrote them", () => {
    expect(orderedCounts({ done: 2, planned: 5, running: 1 }, TASK_STATES)).toEqual([
      ["planned", 5],
      ["running", 1],
      ["done", 2],
    ]);
  });

  test("with fill, a word the server did not send shows as zero; without it, it is left out", () => {
    expect(orderedCounts({ queued: 3 }, ["planned", "queued", "done"], true)).toEqual([
      ["planned", 0],
      ["queued", 3],
      ["done", 0],
    ]);
    expect(orderedCounts({ queued: 3 }, ["planned", "queued", "done"])).toEqual([["queued", 3]]);
  });

  test("a word the page does not know is never hidden: it follows the known ones, in alphabetical order", () => {
    expect(orderedCounts({ zeta: 1, done: 4, alpha: 2 }, ["planned", "done"])).toEqual([
      ["done", 4],
      ["alpha", 2],
      ["zeta", 1],
    ]);
    expect(orderedCounts({ ghost: 0 }, ["planned"], true)).toEqual([
      ["planned", 0],
      ["ghost", 0],
    ]);
    expect(orderedCounts({}, PASSES)).toEqual([]);
  });
});

describe("a slice against its cap", () => {
  test("the share is the 95th percentile over the cap, and none without a cap", () => {
    expect(capShare(slice({ tokens_p95: 9000, cap: 18000 }))).toBe(0.5);
    expect(capShare(slice({ tokens_p95: 18000, cap: 18000 }))).toBe(1);
    expect(capShare(slice({ cap: 0 }))).toBeNull();
    expect(capShare(slice({ cap: -5 }))).toBeNull();
  });

  test("room to spare is ok; at four fifths of the cap it is near it, and just under that it is still ok", () => {
    expect(NEAR_CAP).toBe(0.8);
    expect(sliceLevel(slice({ tokens_p95: 9000 }))).toBe("ok");
    expect(sliceLevel(slice({ tokens_p95: 14399, cap: 18000 }))).toBe("ok");
    expect(sliceLevel(slice({ tokens_p95: 14400, cap: 18000 }))).toBe("near");
    expect(sliceLevel(slice({ tokens_p95: 18000, cap: 18000 }))).toBe("near");
  });

  test("a slice that lost content to fit is cut, even when it is far from the cap now", () => {
    expect(sliceLevel(slice({ trimmed: 1 }))).toBe("cut");
    expect(sliceLevel(slice({ trimmed: 7, tokens_p95: 17900 }))).toBe("cut");
  });

  test("a slice that does not fit in some state is over, whatever else is true of it", () => {
    expect(sliceLevel(slice({ over_cap: 1 }))).toBe("over");
    expect(sliceLevel(slice({ over_cap: 1, trimmed: 9, tokens_p95: 18000 }))).toBe("over");
  });

  test("with no cap to compare, a slice that was neither cut nor refused is ok", () => {
    expect(sliceLevel(slice({ cap: 0, tokens_p95: 99999 }))).toBe("ok");
  });

  test("each level has its own tone, from calm to alarmed", () => {
    expect(SLICE_TONE).toEqual({
      over: "negative",
      cut: "warning",
      near: "info",
      ok: "positive",
    });
  });
});

describe("the audit", () => {
  test("a rule the audit never ran is not a clean record", () => {
    expect(auditVerdict(rule({ days_audited: 0, violations: 0, checked: 0 }))).toBe("never");
    expect(AUDIT_TONE.never).toBe("neutral");
  });

  test("a rule with audited days and no violations is clean; one violation makes it not", () => {
    expect(auditVerdict(rule({ days_audited: 1, violations: 0 }))).toBe("clean");
    expect(auditVerdict(rule({ days_audited: 1, violations: 1 }))).toBe("violations");
    expect(AUDIT_TONE.clean).toBe("positive");
    expect(AUDIT_TONE.violations).toBe("negative");
  });

  test("violations found on days that were audited count even when the days are many", () => {
    expect(auditVerdict(rule({ days_audited: 7, violations: 3 }))).toBe("violations");
  });
});

describe("the registry against the code", () => {
  test("a built agent whose code is the registered one is in sync; one whose code moved is not", () => {
    expect(syncState(agent({ in_sync: true }))).toBe("in_sync");
    expect(syncState(agent({ in_sync: false }))).toBe("drift");
  });

  test("an agent without code to compare is neither: planned, postponed, or built with nothing to say", () => {
    expect(syncState(agent({ status: "planned", in_sync: null }))).toBe("none");
    expect(syncState(agent({ status: "postponed", in_sync: null }))).toBe("none");
    expect(syncState(agent({ status: "built", in_sync: null }))).toBe("none");
    // a planned agent never counts as drifting, whatever the field says
    expect(syncState(agent({ status: "planned", in_sync: false }))).toBe("none");
  });

  test("the counts of the registry by status, and how many built agents drifted", () => {
    const registry = [
      agent({ agent: "a" }),
      agent({ agent: "b", in_sync: false }),
      agent({ agent: "c", in_sync: false }),
      agent({ agent: "d", status: "planned", in_sync: null }),
      agent({ agent: "e", status: "planned", in_sync: null }),
      agent({ agent: "f", status: "postponed", in_sync: null }),
    ];
    expect(registryCounts(registry)).toEqual({ built: 3, planned: 2, postponed: 1, drift: 2 });
    expect(registryCounts([])).toEqual({ built: 0, planned: 0, postponed: 0, drift: 0 });
  });
});

describe("what the owner should look at", () => {
  test("nothing, when the registry agrees, the audit is clean, every slice fits and the job runs", () => {
    expect(attention(overview())).toEqual([]);
  });

  test("a violation of the audit, summed over the rules", () => {
    const o = overview({
      audit: [rule({ violations: 2 }), rule({ rule: "review_known", violations: 3 })],
    });
    expect(attention(o)).toEqual([{ code: "audit_violations", n: 5 }]);
  });

  test("an agent whose code is not the registered one", () => {
    const o = overview({
      registry: [agent({ in_sync: false }), agent({ agent: "b", in_sync: false })],
    });
    expect(attention(o)).toEqual([{ code: "drift", n: 2 }]);
  });

  test("each finding of the registry against the code, and a registry that could not be read", () => {
    const problems = [
      { code: "fingerprint", subject: "reviewer", text: "the code is not the one registered" },
      { code: "unreadable", subject: "registry", text: "RuntimeError" },
    ];
    expect(attention(overview({ problems }))).toEqual([{ code: "registry_problems", n: 2 }]);
  });

  test("a slice that does not fit in some state - counted by slices, not by states", () => {
    const o = overview();
    o.package.slices = [
      slice({ over_cap: 12 }),
      slice({ name: "stats" }),
      slice({ name: "odds", over_cap: 1 }),
    ];
    expect(attention(o)).toEqual([{ code: "slices_over_cap", n: 2 }]);
  });

  test("a slice that was only cut, or is near its cap, is not a reason to look: the table already says it", () => {
    const o = overview();
    o.package.slices = [slice({ trimmed: 5 }), slice({ name: "stats", tokens_p95: 17000 })];
    expect(attention(o)).toEqual([]);
  });

  test("the last run of the state job: failed and partial each have their own line, ok and running have none", () => {
    for (const [status, code] of [
      ["failed", "job_failed"],
      ["partial", "job_partial"],
    ] as const) {
      const o = overview();
      o.package.cycles.last = cycle(status);
      expect(attention(o)).toEqual([{ code, n: 1 }]);
    }
    for (const status of ["ok", "running"]) {
      const o = overview();
      o.package.cycles.last = cycle(status);
      expect(attention(o)).toEqual([]);
    }
  });

  test("the job switched off is a line when the layer is on, and none when the whole layer is off", () => {
    expect(attention(overview({ settings: { mode: "shadow", package: false } }))).toEqual([
      { code: "job_off", n: 1 },
    ]);
    expect(attention(overview({ settings: { mode: "enforce", package: false } }))).toEqual([
      { code: "job_off", n: 1 },
    ]);
    expect(attention(overview({ settings: { mode: "off", package: false } }))).toEqual([]);
  });

  test("everything at once comes most serious first: leaks, code, registry, slices, the job", () => {
    const o = overview({
      audit: [rule({ violations: 1 })],
      registry: [agent({ in_sync: false })],
      problems: [{ code: "x", subject: "y", text: "z" }],
      settings: { mode: "shadow", package: false },
    });
    o.package.slices = [slice({ over_cap: 1 })];
    o.package.cycles.last = cycle("failed");
    expect(attention(o).map((a) => a.code)).toEqual([
      "audit_violations",
      "drift",
      "registry_problems",
      "slices_over_cap",
      "job_failed",
      "job_off",
    ]);
  });
});

describe("a decision and a state of a match", () => {
  test("a decision says what it changed; a first role has no origin", () => {
    expect(decisionChange({ from_role: "CHAMPION", to_role: "RETIRED" })).toBe(
      "CHAMPION → RETIRED",
    );
    expect(decisionChange({ from_role: null, to_role: "CHALLENGER" })).toBe("— → CHALLENGER");
  });

  const row = (slices: MatchStateRow["slices"]): Pick<MatchStateRow, "slices"> => ({ slices });
  const s = (name: string, tokens: number, fits = true) => ({
    name,
    hash: "h",
    tokens,
    cap: 18000,
    fits,
    trimmed: [],
    blocks: [],
  });

  test("the tokens of a state are those of all its slices", () => {
    expect(totalTokens(row([s("match", 1500), s("stats", 300), s("odds", 12)]))).toBe(1812);
    expect(totalTokens(row([]))).toBe(0);
  });

  test("the slices of a state that do not fit are named, in the order the state lists them", () => {
    expect(
      slicesOver(row([s("match", 1500), s("stats", 19000, false), s("odds", 20000, false)])),
    ).toEqual(["stats", "odds"]);
    expect(slicesOver(row([s("match", 1500)]))).toEqual([]);
  });
});

describe("a task and a promotion on one line", () => {
  const task = (over: Partial<Parameters<typeof taskLine>[0]> = {}) => ({
    task: "review_analysis",
    prompt_version: "review-v2",
    model: null,
    tier: "analysis",
    effort: "low",
    ...over,
  });

  test("a task says its name, its prompt, what it runs on and its effort", () => {
    expect(taskLine(task())).toBe("review_analysis · review-v2 · analysis · low");
  });

  test("a task that pins a model shows the model and not the tier of the old route", () => {
    expect(taskLine(task({ task: "council", model: "claude-sonnet-5-5", effort: "high" }))).toBe(
      "council · review-v2 · claude-sonnet-5-5 · high",
    );
  });

  test("a part the registry does not have is left out, with no empty place in the line", () => {
    expect(taskLine(task({ tier: null }))).toBe("review_analysis · review-v2 · low");
    expect(taskLine(task({ tier: null, effort: "" }))).toBe("review_analysis · review-v2");
  });

  test("a family that reads the language model names no promotion", () => {
    expect(promotionLine({ engine: "llm", promotion: null, agent: null })).toEqual({
      name: null,
      understood: true,
    });
  });

  test("a family that reads an agent shows the name the owner signed, whole", () => {
    expect(
      promotionLine({
        engine: "agent",
        promotion: "council@council-v1+match-v1",
        agent: "council",
      }),
    ).toEqual({ name: "council@council-v1+match-v1", understood: true });
  });

  test("a promotion name this code does not read is shown as it is and marked as not understood", () => {
    expect(promotionLine({ engine: "agent", promotion: "oracle@v9", agent: null })).toEqual({
      name: "oracle@v9",
      understood: false,
    });
  });
});
