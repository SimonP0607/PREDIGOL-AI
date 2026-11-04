/// <reference types="bun" />
/**
 * The views of the shadow (plan IA, phase 3), in both languages, given the figures the server sends: the seven arms side by side, the enough-data
 * counts that never say "passed", the empty state that names the owner's three words, the contradictions with what each engine did with them, the
 * agent runs against the Opus cap, and the file of a match with each engine's verdict beside today's reviewers. Codes only: nothing here may show a
 * model's text or an address. The views read: they have no button that writes.
 */
import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { hasKey, setLocale } from "@/lib/i18n";
import { localInt } from "@/lib/i18n/format";
import type {
  AgentRunItem,
  AgentRuns,
  ArmId,
  ArmRow,
  Cell,
  Contradictions,
  ShadowArms,
  ShadowFile,
  ShadowSwitches,
} from "@/lib/api/v1/types_ai_shadow";
import { AgentRunsBody } from "./AgentRunsPanel";
import { ContradictionsBody } from "./ContradictionsLive";
import { ShadowArmsBody } from "./ShadowArmsPanel";
import { ShadowFileBody } from "./ShadowFilePanel";
import { ARMS, CONTRA_CODES } from "./shadowModel";

const text = (html: string) =>
  html
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, "&")
    .replace(/&gt;/g, ">")
    .replace(/&lt;/g, "<")
    .replace(/\s+/g, " ");

beforeEach(() => setLocale("es"));
afterEach(() => setLocale("es"));

const WORDS = ["FBI_AI_ENGINES", "FBI_AI_SHADOW_SAMPLE", "FBI_AI_AGENTS"];

function switches(on: boolean): ShadowSwitches {
  return {
    mode: on ? "shadow" : "off",
    orchestrate: on,
    words: [
      { name: WORDS[0] ?? "", value: on ? "rules,llm,combined,ma-v1" : "", on },
      { name: WORDS[1] ?? "", value: on ? "0.2" : "", on },
      { name: WORDS[2] ?? "", value: on ? "match,council" : "", on },
    ],
    engines: on ? ["rules", "llm", "combined", "ma-v1"] : [],
    shadow_engines: on ? ["ma-v1"] : [],
    shadow_sample: on ? "0.2" : "",
    agents: on ? ["match", "council"] : [],
  };
}

const D = { approved: 6, downgraded: 2, rejected: 1, abstained: 1 };

function arm(id: ArmId, over: Partial<ArmRow> = {}): ArmRow {
  const lab = id === "ma-v1" || id === "ma-v1-h" || id === "council_solo";
  return {
    arm: id,
    engine: id === "rules" ? "rules" : lab ? (id === "council_solo" ? "cs-v1" : id) : null,
    kind: lab ? "shadow" : id === "llm" ? "production" : "derived",
    scope: lab ? "lab" : null,
    reviews: 10,
    selections: 10,
    decisions: id === "rules" || id === "gap" ? null : D,
    statuses: { ok: 9, invalid_output: 1 },
    invalid: lab ? 1 : 0,
    on_sample: 10,
    selections_on_sample: 10,
    decisions_on_sample: id === "rules" || id === "gap" ? null : D,
    cost_usd: lab ? "0.0420" : null,
    ledger_usd: lab ? "0.0500" : null,
    calls: lab ? 12 : 0,
    latency_p95_ms: lab ? 2400 : null,
    latency_n: lab ? 12 : 0,
    paused: lab ? { invalid_over_3pct: 2 } : {},
    not_answered: {},
    settled: null,
    ...over,
  };
}

function arms(on: boolean, over: Partial<ShadowArms> = {}): ShadowArms {
  return {
    days: 30,
    since: "2026-10-04T00:00:00Z",
    switches: switches(on),
    assignments: {
      experiment: "ma-shadow-v1",
      arms_version: "arms-v1",
      assigned: on ? 40 : 0,
      sampled: on ? 8 : 0,
      unsampled: on ? 32 : 0,
      council_solo: on ? 2 : 0,
      sampled_share: on ? 0.2 : null,
      by_share: on ? [{ share: "0.2", assigned: 40, sampled: 8, council_solo: 2 }] : [],
      first_assigned_at: null,
      last_assigned_at: null,
    },
    arms: on ? ARMS.map((a) => arm(a)) : [],
    enough: {
      days: 30,
      days_need: 30,
      days_reached: false,
      since: null,
      days_running: 12,
      selections: 120,
      selections_need: 300,
      selections_reached: false,
    },
    lab: { window_usd: "1.2300", shadow_usd: "0.4000", calls: 55 },
    last_cycle: null,
    ...over,
  };
}

describe("Sombra con brazos", () => {
  test("off: says the shadow is off and names the owner's three words", () => {
    for (const locale of ["es", "en"] as const) {
      setLocale(locale);
      const html = renderToStaticMarkup(<ShadowArmsBody d={arms(false)} />);
      expect(html).toContain('data-testid="shadow-off"');
      expect(html).toContain('data-off="true"');
      for (const w of WORDS) expect(html).toContain(w);
      expect(text(html)).toContain(
        locale === "es" ? "La sombra está apagada" : "The shadow is off",
      );
      expect(html).not.toContain('data-testid="arm-ma-v1"');
    }
  });

  test("on: the seven arms, in the plan's order, with their figures", () => {
    const html = renderToStaticMarkup(<ShadowArmsBody d={arms(true)} />);
    const at = ARMS.map((a) => html.indexOf(`data-testid="arm-${a}"`));
    expect(at.every((i) => i > 0)).toBe(true);
    expect([...at].sort((a, b) => a - b)).toEqual(at);
    const t = text(html);
    for (const name of [
      "Modelo solo",
      "Reglas",
      "Filtro de brecha 0,20",
      "IA actual",
      "Council solo",
    ]) {
      expect(t).toContain(name);
    }
    expect(t).toContain("Multiagente ma-v1-h".replace("Multiagente ", "Multiagente + Haiku "));
    // approved 6 of 10 is 60 %
    expect(t).toContain("60");
    // the cost of a LAB arm, and a dash for an arm that is not the LAB's
    expect(t).toContain("0,04");
  });

  test("an arm without decisions of its own says so instead of showing zeros", () => {
    const html = renderToStaticMarkup(<ShadowArmsBody d={arms(true)} />);
    expect(html).toContain('colSpan="4"');
    expect(text(html)).toContain("Sin decisiones propias");
  });

  test("enough data: counts and days, never a verdict", () => {
    const d = arms(true, {
      enough: {
        days: 30,
        days_need: 30,
        days_reached: true,
        since: "2026-09-01T00:00:00Z",
        days_running: 61,
        selections: 410,
        selections_need: 300,
        selections_reached: true,
      },
    });
    for (const locale of ["es", "en"] as const) {
      setLocale(locale);
      const html = renderToStaticMarkup(<ShadowArmsBody d={d} />);
      const t = text(html);
      expect(t).toContain("61 / 30");
      expect(t).toContain("410 / 300");
      expect(html).toContain('data-testid="arms-enough-state"');
      // reaching both thresholds is "enough to look", not "passed"
      expect(t).not.toMatch(/\b(PASS|passed|aprobó|superó la puerta)\b/i);
      expect(t).toContain(
        locale === "es" ? "datos suficientes para mirar" : "enough data to look at",
      );
    }
  });

  test("pause reasons and assignment counts are shown", () => {
    const t = text(renderToStaticMarkup(<ShadowArmsBody d={arms(true)} />));
    expect(t).toContain("Más de 3 % de salidas inválidas");
    expect(t).toContain("En la muestra");
    expect(t).toContain("Fuera de la muestra");
  });

  test("on but nothing written yet: says so, with the words, and shows no table", () => {
    const html = renderToStaticMarkup(
      <ShadowArmsBody
        d={arms(true, {
          arms: arms(true).arms.map((a) => arm(a.arm, { reviews: 0 })),
          assignments: { ...arms(true).assignments, assigned: 0 },
        })}
      />,
    );
    expect(html).toContain('data-off="false"');
    expect(text(html)).toContain("La sombra aún no ha escrito nada");
  });
});

const NOW = "2026-11-02T15:00:00Z";

function contradictions(on: boolean): Contradictions {
  return {
    days: 7,
    since: "2026-10-26T00:00:00Z",
    switches: switches(on),
    passes: on ? 14 : 0,
    with_contradictions: on ? 5 : 0,
    total: on ? 6 : 0,
    counts: on
      ? [
          {
            code: "C06",
            n: 4,
            passes: 3,
            matches: 3,
            confirmed: 4,
            treatment: {
              "ma-v1": { kept: 1, lowered: 3 },
              "ma-v1-h": { abstained: 2, none: 2 },
              "cs-v1": { kept: 4 },
            },
          },
        ]
      : [],
    recent: on
      ? [
          {
            code: "C06",
            fixture_id: 77,
            match: "Alfa - Beta",
            kickoff_at: NOW,
            pass_kind: "final",
            known_at: NOW,
            created_at: NOW,
            subject: "pair:c1+c1",
            candidates: [{ key: "c1", market: "OU", selection: "Over", line: "2.5" }],
            refs: ["P:market", "P:models"],
            confirmed: true,
            official_lineup: false,
            starters_out: 0,
            gap: "0.31",
            requires: null,
            treatment: { "ma-v1": { c1: "lowered" }, "cs-v1": { c1: "kept" } },
          },
        ]
      : [],
  };
}

describe("Contradicciones", () => {
  test("off: the empty state with the words, and no table", () => {
    const html = renderToStaticMarkup(<ContradictionsBody d={contradictions(false)} />);
    expect(html).toContain('data-testid="shadow-off"');
    for (const w of WORDS) expect(html).toContain(w);
    expect(html).not.toContain('data-testid="contra-count-C01"');
  });

  test("on: all eight codes have a row, those that never fired say so, and the Council's treatment is shown", () => {
    const html = renderToStaticMarkup(<ContradictionsBody d={contradictions(true)} />);
    for (const c of CONTRA_CODES) expect(html).toContain(`data-testid="contra-count-${c}"`);
    const t = text(html);
    expect(t).toContain("No saltó en esta ventana");
    expect(t).toContain("mantuvo 1");
    expect(t).toContain("rebajó 3");
    expect(t).toContain("se abstuvo 2");
    expect(t).toContain("sin veredicto 2");
  });

  test("the recent list: match, candidates by name with the server's id, confirmation, refs - and a link only when given a way to open", () => {
    const html = renderToStaticMarkup(<ContradictionsBody d={contradictions(true)} />);
    const t = text(html);
    expect(t).toContain("Alfa - Beta");
    expect(t).toContain("c1");
    expect(t).toContain("Confirmada");
    expect(t).toContain("P:market");
    expect(html).not.toContain("<button");
    const withOpen = renderToStaticMarkup(
      <ContradictionsBody d={contradictions(true)} onMatch={() => {}} />,
    );
    expect(withOpen).toContain("<button");
  });

  test("English", () => {
    setLocale("en");
    const t = text(renderToStaticMarkup(<ContradictionsBody d={contradictions(true)} />));
    expect(t).toContain("Confirmed");
    expect(t).toContain("lowered 3");
    expect(t).toContain("Model against market");
  });
});

function run(over: Partial<AgentRunItem> = {}): AgentRunItem {
  return {
    id: 1,
    run_kind: "shadow",
    started_at: NOW,
    fixture_id: 77,
    match: "Alfa - Beta",
    pass_kind: "final",
    agent: "council",
    agent_version: "council-v1",
    task_kind: "council",
    model: "claude-haiku-4-5",
    effort: null,
    status: "ok",
    verdict: "APPROVE",
    input_tokens: 1200,
    output_tokens: 300,
    cached_tokens: 0,
    cost_usd: "0.0210",
    latency_ms: 1800,
    escalation: null,
    fired: [],
    error: null,
    idem: "abc",
    workspace: null,
    parent_run_id: null,
    ...over,
  };
}

function runs(calls: number, over: Partial<AgentRuns> = {}): AgentRuns {
  return {
    day: "2026-11-02",
    switches: switches(true),
    opus: {
      day: "2026-11-02",
      calls,
      cap: 3,
      remaining: Math.max(0, 3 - calls),
      skipped: 1,
      cost_usd: "0.4100",
    },
    total: 2,
    cost_usd: "0.4310",
    by_status: { ok: 1, invalid: 1 },
    runs: [
      run(),
      run({
        id: 2,
        model: "claude-opus-4-5",
        task_kind: "escalation",
        status: "invalid",
        escalation: "E2",
        fired: ["E2", "E5"],
        error: "schema",
      }),
    ],
    ...over,
  };
}

describe("Ejecuciones de los agentes", () => {
  test("a run shows agent, task, model, status, tokens, cost, latency and the rule", () => {
    const html = renderToStaticMarkup(<AgentRunsBody d={runs(1)} />);
    expect(html.match(/data-testid="agent-run"/g)).toHaveLength(2);
    const t = text(html);
    for (const w of ["claude-opus-4-5", "Inválida", localInt(1200), "E2 · E5", "schema", "0,02"]) {
      expect(t).toContain(w);
    }
  });

  test("Opus of the day against the cap of 3, in three levels", () => {
    expect(text(renderToStaticMarkup(<AgentRunsBody d={runs(1)} />))).toContain("1 / 3");
    expect(text(renderToStaticMarkup(<AgentRunsBody d={runs(2)} />))).toContain("Queda una");
    const spent = text(renderToStaticMarkup(<AgentRunsBody d={runs(3)} />));
    expect(spent).toContain("3 / 3");
    expect(spent).toContain("Tope alcanzado");
  });

  test("no runs: says so and, with the shadow off, names the words", () => {
    const html = renderToStaticMarkup(
      <AgentRunsBody
        d={runs(0, { runs: [], total: 0, by_status: {}, switches: switches(false) })}
      />,
    );
    expect(html).toContain('data-testid="shadow-off"');
    expect(text(html)).toContain("Ninguna ejecución");
  });
});

function cell(engine: string, decision: Cell["decision"], over: Partial<Cell> = {}): Cell {
  return {
    engine,
    decision,
    confidence: decision ? "0.62" : null,
    level: decision ? "MEDIUM" : null,
    status: decision ? "ok" : null,
    model: null,
    drivers: [],
    risks: [],
    refs: [],
    contradictions: [],
    stances: {},
    escalation: null,
    reason: decision ? null : "paused",
    cost_usd: null,
    review_id: null,
    ...over,
  };
}

function file(over: Partial<ShadowFile> = {}): ShadowFile {
  return {
    fixture_id: 77,
    match: "Alfa - Beta",
    kickoff_at: NOW,
    competition: "Liga",
    switches: switches(true),
    assignment: {
      experiment: "ma-shadow-v1",
      bucket: 31,
      sampled: true,
      council_solo: false,
      share: "0.2",
      assigned_at: NOW,
      engines: ["ma-v1", "cs-v1"],
    },
    passes: [
      {
        id: 1,
        pass_kind: "pre",
        known_at: NOW,
        created_at: NOW,
        packet_id: 9,
        status: "ran",
        reason: null,
        elapsed_ms: 4100,
      },
      {
        id: 2,
        pass_kind: "final",
        known_at: NOW,
        created_at: NOW,
        packet_id: 10,
        status: "ran",
        reason: null,
        elapsed_ms: 3900,
      },
    ],
    selected: {
      id: 2,
      pass_kind: "final",
      known_at: NOW,
      created_at: NOW,
      packet_id: 10,
      status: "ran",
      reason: null,
      elapsed_ms: 3900,
    },
    candidates: [
      {
        key: "c1",
        family: "GOALS",
        market: "OU",
        selection: "Over",
        line: "2.5",
        odds: "1.90",
        p_model: "0.58",
        p_market: "0.52",
        edge: "0.06",
        ev: "0.10",
        left_out: null,
      },
      {
        key: "c2",
        family: "GOALS",
        market: "BTTS",
        selection: "Yes",
        line: "0",
        odds: "1.80",
        p_model: "0.55",
        p_market: "0.54",
        edge: "0.01",
        ev: "-0.01",
        left_out: "slice_over_its_cap",
      },
    ],
    assessments: [
      {
        label: "ma-v1/match",
        mode: "EVALUATION",
        model: "claude-sonnet-4-5",
        status: "ok",
        quality: "GOOD",
        signals: [{ code: "KEY_PLAYER_OUT", direction: "UNDER", strength: "HIGH", refs: ["E:12"] }],
        candidates: [
          {
            candidate: "c1",
            stance: "CONCERN",
            drivers: ["KEY_PLAYER_OUT"],
            risks: [],
            refs: ["E:12"],
          },
        ],
      },
    ],
    contradictions: [
      {
        code: "C01",
        subject: "player:5",
        candidates: ["c1"],
        refs: ["E:12"],
        confirmed: true,
        detail: {},
      },
    ],
    arms: [
      {
        engine: "ma-v1",
        status: "ok",
        reason: null,
        paused: [],
        escalated: {},
        escalation_skipped: {},
        view: null,
      },
    ],
    verdicts: [
      {
        candidate: "c1",
        cells: [
          cell("rules", "APPROVE"),
          cell("llm", "APPROVE"),
          cell("combined", "APPROVE"),
          cell("ma-v1", "DOWNGRADE", {
            drivers: ["KEY_PLAYER_OUT"],
            refs: ["E:12"],
            cost_usd: "0.0300",
          }),
          cell("ma-v1-h", null),
          cell("cs-v1", "APPROVE"),
        ],
      },
    ],
    evidence_ids: [12, 14],
    calls: [run()],
    cost_usd: "0.0510",
    ...over,
  };
}

describe("Expediente de la sombra", () => {
  test("an unassigned match with no passes: the empty state with the words", () => {
    const html = renderToStaticMarkup(
      <ShadowFileBody
        d={file({ assignment: null, passes: [], selected: null, switches: switches(false) })}
      />,
    );
    expect(html).toContain('data-testid="file-shadow-off"');
    for (const w of WORDS) expect(html).toContain(w);
    expect(html).not.toContain('data-testid="file-candidate"');
  });

  test("candidates c1..cN with the server's numbers, and the one left out with its code", () => {
    const html = renderToStaticMarkup(<ShadowFileBody d={file()} />);
    expect(html.match(/data-testid="file-candidate"/g)).toHaveLength(2);
    const t = text(html);
    for (const w of ["c1", "c2", "1.90", "0.58", "0.52", "Porción sobre su tope"])
      expect(t).toContain(w);
  });

  test("each engine's verdict beside today's three reviewers, and where the shadow differs from the combined one", () => {
    const html = renderToStaticMarkup(<ShadowFileBody d={file()} />);
    const row = html.slice(html.indexOf('data-testid="verdict-row-c1"'));
    for (const e of ["rules", "llm", "combined", "ma-v1", "cs-v1"]) {
      expect(row).toContain(`data-testid="verdict-${e}"`);
    }
    expect(row).not.toContain('data-testid="verdict-ma-v1-h"');
    expect(row).toMatch(/data-testid="verdict-ma-v1" data-differs="true"/);
    expect(row).toMatch(/data-testid="verdict-cs-v1" data-differs="false"/);
    expect(text(row)).toContain("Distinto de Combinada");
  });

  test("assignment, assessment in codes, contradictions, evidence ids and calls with cost", () => {
    const html = renderToStaticMarkup(<ShadowFileBody d={file()} />);
    const t = text(html);
    expect(html).toContain('data-testid="file-assignment"');
    expect(t).toContain("KEY_PLAYER_OUT");
    expect(t).toContain("Preocupa");
    expect(t).toContain("C01");
    expect(t).toContain("E:12");
    expect(t).toContain("E:14");
    expect(t).toContain("0,05");
    expect(html).toContain('data-testid="file-call"');
  });

  test("codes only: no link, no form, no input that writes", () => {
    const html = renderToStaticMarkup(<ShadowFileBody d={file()} />);
    expect(html).not.toMatch(/<a\s|href=|<form|<textarea|<input/);
    const onArms = renderToStaticMarkup(<ShadowArmsBody d={arms(true)} />);
    expect(onArms).not.toMatch(/<form|<textarea|<input|<button/);
  });

  test("the pass selector shows only with more than one pass kind and a way to choose", () => {
    const one = renderToStaticMarkup(<ShadowFileBody d={file()} pass="" onPass={() => {}} />);
    expect(one).toContain("<select");
    const none = renderToStaticMarkup(<ShadowFileBody d={file()} />);
    expect(none).not.toContain("<select");
  });
});

describe("every word the views use exists in both languages", () => {
  test("statuses, treatments, levels, directions and stances", () => {
    const keys = [
      ...["ok", "fallback", "invalid_output", "failed", "over_budget"].map(
        (s) => `ai.arms.status.${s}`,
      ),
      ...["derived", "production", "shadow"].map((s) => `ai.arms.kind.${s}`),
      ...["first", "pre", "final", "request"].map((s) => `ai.arms.pass.${s}`),
      ...["kept", "lowered", "abstained", "none"].map((s) => `ai.contra.treatment.${s}`),
      ...["ok", "invalid", "timeout", "abstain", "skipped", "expired", "budget_skip"].map(
        (s) => `ai.agentRuns.status.${s}`,
      ),
      ...["match", "council"].map((s) => `ai.agentRuns.agent.${s}`),
      ...["context", "evaluation", "council", "escalation"].map((s) => `ai.agentRuns.task.${s}`),
      ...["LOW", "MEDIUM", "HIGH", "GOOD", "FAIR", "POOR"].map((s) => `ai.shadowFile.level.${s}`),
      ...["HOME", "DRAW", "AWAY", "OVER", "UNDER", "BOTH_SCORE", "NOT_BOTH_SCORE", "NEUTRAL"].map(
        (s) => `ai.shadowFile.direction.${s}`,
      ),
      ...["SUPPORT", "NEUTRAL", "CONCERN", "REJECT_SIGNAL"].map((s) => `ai.shadowFile.stance.${s}`),
      ...["free", "last", "spent"].map((s) => `ai.agentRuns.opus.level.${s}`),
      ...["ran", "not_run"].map((s) => `ai.shadowFile.pass.${s}`),
    ];
    for (const locale of ["es", "en"] as const) {
      for (const k of keys) expect(hasKey(k, locale)).toBe(true);
    }
  });
});
