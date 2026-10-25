/// <reference types="bun" />
/**
 * The Agentes tab of Operación and the state of a match for the agents (plan IA, phase 1): what the page says of the figures it is given, in both
 * languages. A quiet system says there is nothing to look at and a loud one lists what, most serious first; a rule of the audit that never ran is
 * not shown as clean; a slice is shown against its cap; a name of promotion the page does not read is shown as it is; every word the page counts
 * by has its translation. The tab reads only: the figures come from the server.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { hasKey, setLocale } from "@/lib/i18n";
import { localInt } from "@/lib/i18n/format";
import type {
  AgentRunRow,
  AgentTaskRow,
  AgentView,
  AgentsOverview,
  MatchState,
  MatchStateRow,
  StateSlice,
} from "@/lib/api/v1/types_ai_agents";
import { AgentsBody } from "./AgentsLive";
import { MatchStateBody } from "./MatchStatePanel";
import { PASSES, RUN_STATUSES, TASK_STATES } from "./agentsModel";

const text = (html: string) =>
  html
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, "&")
    .replace(/&gt;/g, ">")
    .replace(/&lt;/g, "<")
    .replace(/\s+/g, " ");

afterEach(() => setLocale("es"));

const FINGERPRINT = "ag0123456789";

function built(over: Partial<AgentView> = {}): AgentView {
  return {
    agent: "reviewer",
    status: "built",
    purpose: "Reviews a pick",
    contract: "review-v2",
    reads: null,
    version: "review-v2",
    fingerprint: FINGERPRINT,
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
    tasks: [
      {
        task: "review_analysis",
        prompt_version: "review-v2",
        schema_version: "review-v2",
        model: null,
        tier: "analysis",
        effort: "low",
      },
    ],
    ...over,
  };
}

const PLANNED = built({
  agent: "match",
  status: "planned",
  purpose: "Assesses a match",
  contract: "aa-v1",
  version: "match-v1",
  fingerprint: null,
  born_as: null,
  baseline: null,
  registered_at: null,
  in_sync: null,
  history: [],
  tasks: [],
  phase: 3,
  replaces: "brief-v8",
});

const POSTPONED = built({
  agent: "player",
  status: "postponed",
  purpose: "Reads a player",
  contract: null,
  version: null,
  fingerprint: null,
  born_as: null,
  baseline: null,
  registered_at: null,
  in_sync: null,
  history: [],
  tasks: [],
  gate: "Gate F-Player: not before the plan is done",
});

function overview(over: Partial<AgentsOverview> = {}): AgentsOverview {
  return {
    registry: [
      built({
        agent: "brief",
        version: "brief-v8",
        retire_phase: 9,
        next_version: "match-v1",
        next_phase: 3,
      }),
      built(),
      PLANNED,
      POSTPONED,
    ],
    problems: [],
    families: [
      {
        family: "1X2",
        engine: "llm",
        promotion: null,
        agent: null,
        version: null,
        upstream: [],
        since: null,
        promotion_id: null,
      },
      {
        family: "OU",
        engine: "llm",
        promotion: null,
        agent: null,
        version: null,
        upstream: [],
        since: null,
        promotion_id: null,
      },
    ],
    decisions: [],
    package: {
      days: 7,
      since: "2026-10-18T12:00:00Z",
      states: 40,
      matches: 20,
      by_pass: { pre: 18, first: 20, final: 2 },
      blocked: 3,
      flagged: 0,
      slices: [
        {
          name: "match",
          states: 40,
          tokens_p50: 4000,
          tokens_p95: 9000,
          tokens_max: 11000,
          cap: 18000,
          trimmed: 0,
          over_cap: 0,
        },
        {
          name: "stats",
          states: 40,
          tokens_p50: 15000,
          tokens_p95: 17000,
          tokens_max: 18000,
          cap: 18000,
          trimmed: 0,
          over_cap: 0,
        },
        {
          name: "odds",
          states: 40,
          tokens_p50: 17500,
          tokens_p95: 18000,
          tokens_max: 18000,
          cap: 18000,
          trimmed: 6,
          over_cap: 0,
        },
        {
          name: "form",
          states: 40,
          tokens_p50: 18000,
          tokens_p95: 18000,
          tokens_max: 21000,
          cap: 18000,
          trimmed: 6,
          over_cap: 2,
        },
      ],
      build_ms: { p50: 120, p95: 1300, max: 61000 },
      per_day: [
        { day: "2026-10-24", states: 25, matches: 12, blocked: 2, flagged: 0 },
        { day: "2026-10-23", states: 15, matches: 8, blocked: 1, flagged: 0 },
      ],
      cycles: {
        total: 9,
        ok: 6,
        partial: 2,
        failed: 1,
        running: 0,
        last: {
          id: 7,
          kind: "package",
          started_at: "2026-10-25T12:00:00Z",
          finished_at: "2026-10-25T12:01:00Z",
          status: "partial",
          mode: "shadow",
          budget_state: "NORMAL",
          counts: { pending: 5, built: 3, refused: 2 },
          cost_usd: "0",
          error: null,
        },
      },
      rule: {
        state_version: "ms-v1",
        package_version: "package-v1",
        window_days: 4,
        limit: 200,
        max_seconds: 90,
      },
    },
    queue: {
      days: 7,
      tasks: Object.fromEntries(TASK_STATES.map((s) => [s, 0])),
      runs: Object.fromEntries(RUN_STATUSES.map((s) => [s, 0])),
      open: 0,
      reserved_usd: "0",
    },
    audit: [{ rule: "slice_known", days: [], days_audited: 0, checked: 0, violations: 0 }],
    settings: { mode: "shadow", package: true },
    ...over,
  };
}

function quiet(): AgentsOverview {
  const o = overview({ problems: [] });
  o.package.slices = [o.package.slices[0]!];
  o.package.cycles.last = null;
  o.package.cycles = { ...o.package.cycles, partial: 0, failed: 0 };
  return o;
}

const render = (o: AgentsOverview) => text(renderToStaticMarkup(<AgentsBody o={o} />));

describe("what to look at", () => {
  test("a quiet system says there is nothing to attend to", () => {
    const html = render(quiet());
    expect(html).toContain("Qué mirar");
    expect(html).toContain("Nada que atender");
  });

  test("a loud one lists what, most serious first, with how many", () => {
    const o = overview({
      problems: [
        { code: "fingerprint", subject: "reviewer", text: "the code is not the one registered" },
      ],
      audit: [{ rule: "slice_known", days: [], days_audited: 3, checked: 90, violations: 2 }],
      registry: [built({ in_sync: false })],
      settings: { mode: "shadow", package: false },
    });
    const html = render(o);
    expect(html).not.toContain("Nada que atender");
    const order = [
      "Violaciones de la auditoría de fugas: 2",
      "Agentes cuyo código no es el registrado: 1",
      "Hallazgos del registro frente al código: 1",
      "Slices que no caben en su tope en algún estado: 1",
      "El último ciclo del job de estados terminó a medias",
      "El job de estados está apagado (FBI_AI_PACKAGE)",
    ].map((line) => html.indexOf(line));
    expect(order.every((i) => i >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
  });

  test("a leak or code that is not the registered one is an alarm; a stopped job is a warning", () => {
    const alarm = renderToStaticMarkup(
      <AgentsBody
        o={overview({
          audit: [{ rule: "slice_known", days: [], days_audited: 1, checked: 5, violations: 1 }],
        })}
      />,
    );
    expect(alarm).toContain('role="alert"');
    expect(alarm).toContain('data-testid="agents-attention"');
    const warning = renderToStaticMarkup(<AgentsBody o={overview()} />);
    expect(warning).toContain('data-tone="warning"');
    expect(warning).not.toContain('data-tone="negative"');
  });
});

describe("the registry", () => {
  const html = () => render(overview());

  test("every agent is named with what it is for and its state", () => {
    const h = html();
    for (const word of [
      "brief",
      "reviewer",
      "match",
      "player",
      "Reviews a pick",
      "Assesses a match",
    ]) {
      expect(h).toContain(word);
    }
    for (const word of ["Construido", "Planeado", "Pospuesto"]) expect(h).toContain(word);
  });

  test("a built agent shows its version, the fingerprint of its code, and that it matches the registry", () => {
    const h = html();
    expect(h).toContain("brief-v8");
    expect(h).toContain(FINGERPRINT);
    expect(h).toContain("Coincide");
  });

  test("an agent whose code moved says it does not match, and the count says how many", () => {
    const o = overview({ registry: [built({ in_sync: false }), built({ agent: "brief" })] });
    const h = render(o);
    expect(h).toContain("No coincide");
    expect(h).toContain("Fuera de sincronía 1");
  });

  test("the task of an agent is one line: its name, its prompt, what it runs on and its effort", () => {
    expect(html()).toContain("review_analysis · review-v2 · analysis · low");
  });

  test("the plan of each agent: the baseline, when it retires and what follows, the phase that builds it, what it replaces, the gate that wakes it", () => {
    const h = html();
    expect(h).toContain("Línea base: ya funcionaba antes del registro");
    expect(h).toContain("Se retira en la fase 9");
    expect(h).toContain("Después: match-v1 (fase 3)");
    expect(h).toContain("Se construye en la fase 3");
    expect(h).toContain("Reemplaza a brief-v8");
    expect(h).toContain("Gate F-Player: not before the plan is done");
  });

  test("with nothing wrong the page says so, and with findings it lists them whole", () => {
    expect(html()).toContain("El registro coincide con el código: sin hallazgos.");
    const o = overview({
      problems: [
        {
          code: "prompt_label",
          subject: "brief/context",
          text: "the label of the prompt names two texts",
        },
        { code: "unreadable", subject: "registry", text: "RuntimeError: x" },
      ],
    });
    const h = render(o);
    expect(h).toContain("El registro y el código no coinciden");
    expect(h).toContain("prompt_label · brief/context : the label of the prompt names two texts");
    expect(h).toContain("unreadable · registry : RuntimeError: x");
    expect(h).not.toContain("sin hallazgos");
  });
});

describe("the engine of each family and the decisions", () => {
  const withAgent = () =>
    overview({
      families: [
        {
          family: "1X2",
          engine: "llm",
          promotion: null,
          agent: null,
          version: null,
          upstream: [],
          since: null,
          promotion_id: null,
        },
        {
          family: "OU",
          engine: "agent",
          promotion: "council@council-v1+match-v1",
          agent: "council",
          version: "council-v1",
          upstream: ["match-v1"],
          since: "2026-10-20T15:00:00Z",
          promotion_id: 3,
        },
        {
          family: "BTTS",
          engine: "agent",
          promotion: "oracle@v9",
          agent: null,
          version: null,
          upstream: [],
          since: "2026-10-21T15:00:00Z",
          promotion_id: 4,
        },
      ],
    });

  test("a family with no promotion reads the language model, and says no promotion", () => {
    const h = render(overview());
    expect(h).toContain("Modelo de lenguaje");
    expect(h).not.toContain("council@");
  });

  test("a family that reads an agent shows the exact name the owner signed", () => {
    const h = render(withAgent());
    expect(h).toContain("council@council-v1+match-v1");
  });

  test("a name this code does not read is shown as it is, marked as not understood - once", () => {
    const h = render(withAgent());
    expect(h).toContain("oracle@v9");
    expect(h.split("Nombre que este código no lee").length - 1).toBe(1);
  });

  test("with no decision the page says every family reads the language model", () => {
    expect(render(overview())).toContain("Ningún agente ha sido promovido ni retirado");
  });

  test("a decision says when, for which family, what changed, who signed and why", () => {
    const o = overview({
      decisions: [
        {
          id: 9,
          at: "2026-10-22T15:00:00Z",
          family: "OU",
          promotion: "council@council-v1",
          from_role: "CHAMPION",
          to_role: "RETIRED",
          decided_by: "system",
          gate_version: "ma-gate-v1",
          reason: "roll-back: the budget gate failed",
        },
        {
          id: 8,
          at: "2026-10-20T15:00:00Z",
          family: "OU",
          promotion: "council@council-v1",
          from_role: null,
          to_role: "CHAMPION",
          decided_by: "owner",
          gate_version: "ma-gate-v1",
          reason: "passed gate D with 312 selections",
        },
      ],
    });
    const h = render(o);
    expect(h).not.toContain("Ningún agente ha sido promovido");
    expect(h).toContain("CHAMPION → RETIRED");
    expect(h).toContain("— → CHAMPION");
    expect(h).toContain("Sistema (reversión)");
    expect(h).toContain("Propietario");
    expect(h).toContain("ma-gate-v1");
    expect(h).toContain("roll-back: the budget gate failed");
  });
});

describe("the states of the matches", () => {
  const h = () => render(overview());

  test("the figures of the window: states, matches, what blocks, how long it took, how the job fared", () => {
    const html = h();
    expect(html).toContain("Estados de partido");
    expect(html).toContain("Lo que escribió el job de estados en los últimos 7 días");
    expect(html).toContain("Estados escritos 40");
    expect(html).toContain("Partidos 20");
    expect(html).toContain("Con algo que bloquea a un agente 3");
    expect(html).toContain("120 ms · 1.3 s · 1 min");
    expect(html).toContain("6 correctos · 2 parciales · 1 fallidos · 0 en curso");
  });

  test("the job is on or off as the owner set it, with the mode of the layer", () => {
    expect(h()).toContain("Encendido");
    expect(h()).toContain("Modo de la IA: shadow");
    const off = render(overview({ settings: { mode: "shadow", package: false } }));
    expect(off).toContain("Apagado");
  });

  test("the last run of the job: when, how it ended and what it counted", () => {
    const html = h();
    expect(html).toContain("Último ciclo del job");
    expect(html).toContain("parcial");
    expect(html).toContain("Pases por armar 5");
    expect(html).toContain("Armados 3");
    expect(html).toContain("Rechazados 2");
  });

  test("a job that has not run says so", () => {
    expect(render(quiet())).toContain("El job todavía no ha corrido en esta ventana.");
  });

  test("the states by pass come in the order of the day, whatever order the server sent", () => {
    const html = h();
    const at = ["Primer pase · 20", "Pase previo · 18", "Pase final · 2"].map((s) =>
      html.indexOf(s),
    );
    expect(at.every((i) => i >= 0)).toBe(true);
    expect([...at].sort((a, b) => a - b)).toEqual(at);
  });

  test("each slice is shown against its cap, with the verdict: room to spare, near, cut, or not fitting", () => {
    const html = h();
    expect(html).toContain("Holgado");
    expect(html).toContain("Cerca del tope");
    expect(html).toContain("Recortado");
    expect(html).toContain("No cabe");
    expect(html).toContain("50 %");
    expect(html).toContain("94 %");
    expect(html).toContain("100 %");
    expect(html).toContain(localInt(18000));
    expect(html).toContain(localInt(21000));
  });

  test("a window with no states says the job has written none", () => {
    const o = overview();
    o.package = {
      ...o.package,
      states: 0,
      matches: 0,
      by_pass: {},
      slices: [],
      per_day: [],
      build_ms: { p50: null, p95: null, max: null },
    };
    const html = render(o);
    expect(html).toContain("Todavía no hay estados en la ventana");
    expect(html).toContain("Sin estados en la ventana.");
    expect(html).not.toContain("Estados por pase");
  });

  test("the states of each Bogotá day, newest first as the server sent them", () => {
    const html = h();
    expect(html).toContain("Estados por día de Bogotá");
    expect(html.indexOf("24 oct")).toBeGreaterThan(-1);
    expect(html.indexOf("24 oct")).toBeLessThan(html.indexOf("23 oct"));
  });

  test("the rules of the job: versions, the window of passes, the most per run and the longest time", () => {
    const html = h();
    for (const word of ["ms-v1", "package-v1", "4 días", localInt(200), "90 s"])
      expect(html).toContain(word);
  });
});

describe("the queue", () => {
  test("it says it is empty until phase 2, with every state counted, even those at zero, in the order of a task's life", () => {
    const html = render(overview());
    expect(html).toContain("Cola del Orquestador");
    expect(html).toContain("Vacía hasta la fase 2");
    expect(html).toContain("Tareas abiertas 0");
    const order = [
      "Planeadas",
      "En cola",
      "En curso",
      "Hechas",
      "Fallidas",
      "Omitidas",
      "Vencidas",
    ].map((s) => html.indexOf(s));
    expect(order.every((i) => i >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    for (const word of [
      "Correctos",
      "Inválidos",
      "Tiempo agotado",
      "Abstenciones",
      "Sin presupuesto",
    ]) {
      expect(html).toContain(word);
    }
  });

  test("what the open tasks reserve is money, written as money", () => {
    const o = overview();
    o.queue = { ...o.queue, open: 3, reserved_usd: "1.2500" };
    const html = render(o);
    expect(html).toContain("Tareas abiertas 3");
    expect(html).toContain("US$ 1,25");
  });
});

describe("the audit", () => {
  const audit = () =>
    overview({
      audit: [
        { rule: "slice_known", days: [], days_audited: 0, checked: 0, violations: 0 },
        {
          rule: "review_known",
          days: [
            {
              day: "2026-10-24",
              checked_at: "2026-10-25T05:00:00Z",
              version: "leak-audit-v7",
              n_checked: 30,
              n_violations: 0,
              examples: [],
            },
          ],
          days_audited: 1,
          checked: 30,
          violations: 0,
        },
        {
          rule: "agent_known",
          days: [
            {
              day: "2026-10-24",
              checked_at: "2026-10-25T05:00:00Z",
              version: "leak-audit-v7",
              n_checked: 12,
              n_violations: 2,
              examples: [{ fixture_id: 9370001, why: "knew the result" }],
            },
          ],
          days_audited: 1,
          checked: 12,
          violations: 2,
        },
      ],
    });

  test("a rule the audit never ran is not shown as clean", () => {
    const html = render(audit());
    expect(html).toContain("Sin auditar");
    expect(html).toContain("Limpia");
    expect(html).toContain("Con violaciones");
    expect(html).toContain("Cada slice sabía solo lo de su momento");
  });

  test("the days with violations show what was found", () => {
    const html = render(audit());
    expect(html).toContain("Días con violaciones");
    expect(html).toContain("agent_known · sáb, 24 oct · 2");
    expect(html).toContain("knew the result");
  });

  test("a clean audit lists no examples", () => {
    const o = audit();
    o.audit = o.audit.filter((r) => r.violations === 0);
    expect(render(o)).not.toContain("Días con violaciones");
  });

  test("no rule at all says the audit has none yet", () => {
    expect(render(overview({ audit: [] }))).toContain(
      "La auditoría todavía no tiene ninguna regla de agentes.",
    );
  });
});

describe("in English", () => {
  test("the same body reads in English", () => {
    setLocale("en");
    const o = overview({
      families: [
        {
          family: "OU",
          engine: "agent",
          promotion: "council@council-v1",
          agent: "council",
          version: "council-v1",
          upstream: [],
          since: null,
          promotion_id: 1,
        },
      ],
    });
    const html = render(o);
    for (const word of [
      "What to look at",
      "Agent registry",
      "Built",
      "Engine of each family",
      "Match states",
      "Orchestrator queue",
      "Leakage audit of the agents",
      "Comfortable",
      "Does not fit",
      "Not audited",
      "First pass",
    ]) {
      expect(html).toContain(word);
    }
    expect(html).not.toContain("Qué mirar");
  });

  test("a quiet system says so in English", () => {
    setLocale("en");
    expect(render(quiet())).toContain("Nothing to attend to");
  });
});

describe("the words of the tab", () => {
  const WORDS: Array<[string, readonly string[]]> = [
    ["ai.agents.queue.state", TASK_STATES],
    ["ai.agents.queue.status", RUN_STATUSES],
    ["ai.agents.match.state", TASK_STATES],
    ["ai.agents.match.status", RUN_STATUSES],
    ["ai.agents.package.pass", PASSES],
    ["ai.agents.package.slices.level", ["ok", "near", "cut", "over"]],
    ["ai.agents.audit.verdict", ["never", "clean", "violations"]],
    [
      "ai.agents.audit.rule",
      ["slice_known", "agent_known", "review_known", "shadow_review_known", "memory_known"],
    ],
    ["ai.agents.registry.status", ["built", "planned", "postponed"]],
    ["ai.agents.registry.sync", ["in_sync", "drift", "none"]],
    ["ai.agents.engines.engineName", ["llm", "agent"]],
    ["ai.agents.decisions.by", ["owner", "system"]],
    [
      "ai.agents.attention",
      [
        "audit_violations",
        "drift",
        "registry_problems",
        "slices_over_cap",
        "job_failed",
        "job_partial",
        "job_off",
      ],
    ],
    [
      "ai.agents.package.count",
      ["pending", "built", "existing", "refused", "failed", "deferred", "build_ms", "tokens_max"],
    ],
  ];

  test("every word the page counts by has its translation in Spanish and in English", () => {
    for (const locale of ["es", "en"] as const) {
      for (const [prefix, words] of WORDS) {
        for (const word of words) expect(hasKey(`${prefix}.${word}`, locale)).toBe(true);
      }
    }
  });

  test("the tab and the new kind of cycle are named in both languages", () => {
    for (const locale of ["es", "en"] as const) {
      expect(hasKey("admin.operation.tabs.agents", locale)).toBe(true);
      expect(hasKey("ai.layer.cycle.package", locale)).toBe(true);
    }
  });
});

// ── the state of a match ─────────────────────────────────────────────────────

function slice(name: string, tokens: number, over: Partial<StateSlice> = {}): StateSlice {
  return {
    name,
    hash: `${name}-hash`,
    tokens,
    cap: 18000,
    fits: true,
    trimmed: [],
    blocks: ["form", "market"],
    ...over,
  };
}

function state(id: number, pass: string, over: Partial<MatchStateRow> = {}): MatchStateRow {
  return {
    id,
    fixture_id: 9370001,
    run_kind: "live",
    pass_kind: pass,
    known_at: "2026-10-25T10:00:00Z",
    created_at: "2026-10-25T10:02:00Z",
    state_version: "ms-v1",
    package_version: "package-v1",
    package_hash: "0123456789abcdef0123456789abcdef",
    packet_id: 55,
    elapsed_ms: 120,
    slices: [slice("match", 800), slice("stats", 300)],
    blocking: [],
    flags: [],
    code: "mc9a7bec97ca",
    agents: 0,
    contradictions: 0,
    candidates: 0,
    risks: 0,
    final: false,
    ...over,
  };
}

const TASK: AgentTaskRow = {
  id: 1,
  agent: "match",
  agent_version: "match-v1",
  task_kind: "assess",
  pass_kind: "pre",
  state: "queued",
  run_kind: "live",
  priority: 70,
  est_cost_usd: "0.0350",
  attempts: 0,
  reason: "pre pass, kickoff in 5 h",
  created_at: "2026-10-25T10:03:00Z",
  deadline_at: "2026-10-25T14:00:00Z",
};

const RUN: AgentRunRow = {
  id: 1,
  agent: "match",
  agent_version: "match-v1",
  task_kind: "assess",
  pass_kind: "pre",
  run_kind: "live",
  status: "ok",
  model: "claude-haiku-5-5",
  verdict: "caution",
  started_at: "2026-10-25T10:04:00Z",
  finished_at: "2026-10-25T10:04:05Z",
  cost_usd: "0.0310",
  reason: "assessed",
};

const renderState = (s: MatchState) => text(renderToStaticMarkup(<MatchStateBody s={s} />));

describe("the state of a match for the agents", () => {
  const file = (over: Partial<MatchState> = {}): MatchState => {
    const first = state(1, "first", {
      known_at: "2026-10-24T22:00:00Z",
      created_at: "2026-10-24T22:02:00Z",
    });
    const pre = state(2, "pre", {
      blocking: ["competition_score:PRODUCT_ONLY"],
      flags: ["instruction_like:odds"],
      slices: [slice("match", 1500), slice("stats", 19000, { fits: false, trimmed: ["h2h"] })],
    });
    return {
      fixture_id: 9370001,
      current: pre,
      history: [pre, first],
      tasks: [],
      runs: [],
      ...over,
    };
  };

  test("a match with no live state says when the job writes one, and shows no table of slices", () => {
    const html = renderState({
      fixture_id: 9370002,
      current: null,
      history: [],
      tasks: [],
      runs: [],
    });
    expect(html).toContain("Este partido todavía no tiene estado vivo");
    expect(html).not.toContain("Estado vivo");
    expect(html).not.toContain("Estados por los que pasó el partido");
  });

  test("the live state: its pass, its moment, its fingerprint, the code of the model and what it measured", () => {
    const html = renderState(file());
    expect(html).toContain("Estado vivo");
    expect(html).toContain("Pase previo");
    expect(html).toContain("0123456789ab");
    expect(html).toContain("mc9a7bec97ca");
    expect(html).toContain("ms-v1 · package-v1");
    expect(html).toContain("120 ms");
  });

  test("what blocks the agents and what was marked are named, and a state without them says none", () => {
    const html = renderState(file());
    expect(html).toContain("competition_score:PRODUCT_ONLY");
    expect(html).toContain("instruction_like:odds");
    const clean = renderState(file({ current: state(2, "pre"), history: [state(2, "pre")] }));
    expect(clean).toContain("ninguno");
  });

  test("each slice is shown with its tokens against its cap, whether it fits, what was cut and the blocks it holds", () => {
    const html = renderState(file());
    expect(html).toContain(localInt(1500));
    expect(html).toContain(localInt(19000));
    expect(html).toContain(localInt(18000));
    expect(html).toContain("Cabe");
    expect(html).toContain("No cabe");
    expect(html).toContain("h2h");
    expect(html).toContain("form, market");
  });

  test("the history lists every state the match went through, marks the live one once, and names the slices that did not fit", () => {
    const html = renderState(file());
    expect(html).toContain("Estados por los que pasó el partido");
    expect(html).toContain("Primer pase");
    const history =
      html.split("Estados por los que pasó el partido")[1]?.split("Tareas de los agentes")[0] ?? "";
    expect(history.split(" vivo ").length - 1).toBe(1);
    expect(html).toContain("stats no cabe");
    expect(html).toContain("competition_score:PRODUCT_ONLY");
    expect(html).toContain(localInt(1100));
  });

  test("a state that is not live is marked with its kind", () => {
    const replay = state(3, "pre", { run_kind: "replay" });
    const html = renderState(
      file({ history: [replay, state(2, "pre")], current: state(2, "pre") }),
    );
    expect(html).toContain("replay");
  });

  test("with no task and no attempt the page says the Orchestrator arrives in phase 2", () => {
    const html = renderState(file());
    expect(html).toContain(
      "Ningún agente ha trabajado en este partido: el Orquestador llega en la fase 2.",
    );
    expect(html).toContain("Sin intentos");
  });

  test("the tasks and attempts of the agents, when there are, with their state, their cost and their reason", () => {
    const html = renderState(file({ tasks: [TASK], runs: [RUN] }));
    expect(html).not.toContain("Ningún agente ha trabajado");
    expect(html).not.toContain("Sin intentos");
    expect(html).toContain("assess");
    expect(html).toContain("En cola");
    expect(html).toContain("US$ 0,04");
    expect(html).toContain("pre pass, kickoff in 5 h");
    expect(html).toContain("Correcto");
    expect(html).toContain("claude-haiku-5-5");
    expect(html).toContain("caution");
    expect(html).toContain("US$ 0,03");
  });

  test("the verdict of the Council is written, or not yet", () => {
    expect(renderState(file())).toContain("Aún no");
    const done = state(2, "pre", {
      final: true,
      agents: 3,
      contradictions: 1,
      candidates: 2,
      risks: 4,
    });
    const html = renderState(file({ current: done, history: [done] }));
    expect(html).toContain("Escrito en el estado");
  });

  test("it reads in English", () => {
    setLocale("en");
    const html = renderState(file());
    expect(html).toContain("Live state");
    expect(html).toContain("Pre-match pass");
    expect(html).toContain("States the match went through");
    expect(html).toContain("No agent has worked on this match");
    expect(html).not.toContain("Estado vivo");
  });
});
