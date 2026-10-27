/// <reference types="bun" />
/**
 * The "Por entidad y tema" view of Operación (plan IA, phase 2): what the page says of the figures it is given, in both languages. A quiet system
 * says there is nothing to look at and a loud one lists what, most serious first; `on` asked and held as shadow is told as such; a gate that cannot
 * be judged yet is a lack of time with the days it lacks, never a failure; a part of the page that could not be computed does not take the others
 * down; every word the page counts by has its translation. The view reads only: the figures come from the server.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { hasKey, setLocale } from "@/lib/i18n";
import type {
  AnswerRow,
  ClaimBreakdown,
  EntityResearchOverview,
  GateCheckRow,
  ResearchComparison,
  ResearchDay,
  ResearchGateRow,
  ResearchGateView,
  ResearchSwitch,
  TopicRow,
} from "@/lib/api/v1/types_ai_research";
import { TopicsBody } from "./TopicsLive";
import { bogotaDateTime } from "./aiModel";
import {
  CLAIM_STATUSES,
  CLAIM_TYPES,
  ENTITY_KINDS,
  GATE_CHECKS,
  PREVIEW_FIGURES,
  SOURCE_CLASSES,
  TIERS,
  TOPICS,
} from "./topicsModel";

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

// ── a world to render ────────────────────────────────────────────────────────

const GATE_AT = "2026-10-25T20:00:00Z";

function gateRow(over: Partial<ResearchGateRow> = {}): ResearchGateRow {
  return {
    id: 1,
    at: "2026-10-25T21:00:00Z",
    passed: true,
    decided_by: "ia_research_gate",
    code_version: "ia-p02",
    evidence_hash: "0123456789abcdef0123",
    ...over,
  };
}

function switchOf(over: Partial<ResearchSwitch> = {}): ResearchSwitch {
  return {
    asked: "shadow",
    mode: "shadow",
    why: "FBI_AI_RESEARCH_V2=shadow: research v2 runs after v1 and nobody reads its work",
    typed_visible: false,
    gate_passed: false,
    gate_at: null,
    history: [],
    ...over,
  };
}

function topic(over: Partial<TopicRow> = {}): TopicRow {
  return {
    topic: "availability",
    entity: "TEAM",
    levels: [1, 2],
    label: "quién puede jugar (bajas, dudas, sanciones)",
    early_hours: 24,
    late_hours: 4,
    entries: 4,
    fresh: 3,
    expired: 1,
    reuses: 9,
    newest_at: "2026-10-25T18:00:00Z",
    last_reuse_at: "2026-10-25T19:00:00Z",
    ...over,
  };
}

function answer(over: Partial<AnswerRow> = {}): AnswerRow {
  return {
    kind: "TEAM",
    id: 1,
    name: "Manchester United",
    kickoff_at: "2026-10-26T19:00:00Z",
    topic: "availability",
    level: 1,
    results: 5,
    standing: true,
    tiers: { media: 4, official: 1 },
    fetched_at: "2026-10-25T18:00:00Z",
    expires_at: "2026-10-26T18:00:00Z",
    fresh: true,
    reuses: 3,
    last_reuse_at: "2026-10-25T19:00:00Z",
    claims: 2,
    claims_fresh: 1,
    ...over,
  };
}

function breakdown(
  key: string,
  total: number,
  fresh: number,
  by_status: Record<string, number> = {},
): ClaimBreakdown {
  return { key, total, fresh, by_status };
}

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

function comparison(over: Partial<ResearchComparison> = {}): ResearchComparison {
  return {
    first: "2026-10-19",
    last: "2026-10-25",
    passes_in_shadow: 9,
    passes_compared: 8,
    passes_v2_failed: 1,
    passes_v2_cut_short: 0,
    searches_v1: 20,
    searches_v2_alone: 12,
    saved: 8,
    saved_pct: "40.00",
    reuse_pct: "55.50",
    fixtures: 14,
    facts_v1: 30,
    facts_v2: 29,
    found_by_v2: 29,
    coverage_pct: "96.67",
    coverage_players_pct: "90.00",
    facts_per_match_v1: 2.14,
    facts_per_match_v2: 2.07,
    missed_examples: [[9370001, "home", "Marcus Rashford", "OUT"]],
    exa_v1_searches: 20,
    exa_v1_usd: "0.1000",
    exa_v2_searches: 12,
    exa_v2_usd: "0.0600",
    extractor_calls: 11,
    extractor_by_status: { invalid_output: 1, ok: 10 },
    extractor_invalid_pct: "9.09",
    ...over,
  };
}

function check(over: Partial<GateCheckRow> = {}): GateCheckRow {
  return {
    id: "fewer_searches",
    title: "Research v2 habría pagado menos búsquedas que v1",
    ok: true,
    mark: "SÍ",
    detail: { searches_v1: 20, searches_v2_alone: 12, rule: "searches_v2_alone < searches_v1" },
    revert: "FBI_AI_RESEARCH_V2",
    ...over,
  };
}

/** The gate while it cannot be judged: one day of seven, with what the days gone show. */
function pending(over: Partial<ResearchGateView> = {}): ResearchGateView {
  return {
    verdict: "PENDIENTE POR TIEMPO REAL",
    at: GATE_AT,
    window: {
      first: "2026-10-19",
      last: "2026-10-25",
      days: 7,
      anchor: "2026-10-25",
      anchored_by: "a change declared by whoever deployed it, on 2026-10-24",
      stable_complete_days: 1,
      eligible_on: "2026-11-01",
      complete: false,
    },
    checks: [],
    pending: [
      "1 de 7 días completos con research v2 en sombra en todas las pasadas (desde 2026-10-25); el primer día evaluable es 2026-11-01",
    ],
    consequence: null,
    preview: {
      note: "NOT evidence of the gate: only what the days gone show",
      stable_complete_days: 1,
      searches: {
        passes_compared: 8,
        searches_v1: 20,
        searches_v2_alone: 12,
        saved_pct: "40.00",
        reuse_pct: "55.50",
      },
      coverage: {
        fixtures: 14,
        facts_v1: 30,
        facts_v2: 29,
        coverage_pct: "96.67",
        coverage_players_pct: "90.00",
      },
    },
    ...over,
  };
}

/** The gate judged: the seven checks, in the order the gate judges them. */
function judged(over: Partial<ResearchGateView> = {}, failing: string[] = []): ResearchGateView {
  const checks = GATE_CHECKS.map((id) =>
    check({
      id,
      title: `titulo-${id}`,
      ok: !failing.includes(id),
      mark: failing.includes(id) ? "NO" : "SÍ",
      detail: id === "sample" ? { facts_v1: 61, minimum_facts: 50 } : {},
      revert:
        id === "window" || id === "sample" || id === "evidence_known" ? null : "FBI_AI_RESEARCH_V2",
    }),
  );
  return pending({
    verdict: failing.length > 0 ? "NO PASA" : "PASA",
    window: {
      ...pending().window,
      stable_complete_days: 7,
      complete: true,
      eligible_on: "2026-10-26",
    },
    checks,
    pending: [],
    consequence:
      failing.length > 0
        ? "se revierte el interruptor que falle: FBI_AI_RESEARCH_V2 vuelve a off"
        : null,
    preview: {},
    ...over,
  });
}

function overview(over: Partial<EntityResearchOverview> = {}): EntityResearchOverview {
  return {
    days: 7,
    since: "2026-10-19T05:00:00Z",
    switch: switchOf(),
    freshness: {
      late_window_hours: 12,
      topics: [
        topic(),
        topic({
          topic: "confirmation",
          levels: [2],
          label: "confirmar con fuentes oficiales",
          entries: 0,
          fresh: 0,
          expired: 0,
          reuses: 0,
          newest_at: null,
          last_reuse_at: null,
        }),
        topic({
          topic: "preview",
          entity: "MATCH",
          levels: [3],
          label: "previa de medios internacionales",
          entries: 2,
          fresh: 2,
          expired: 0,
          reuses: 1,
        }),
      ],
      unreadable: 0,
    },
    answers: [
      answer({
        kind: "MATCH",
        id: 9370001,
        name: "Manchester United vs Liverpool",
        topic: "preview",
        level: 3,
        results: 3,
        tiers: { media: 3 },
        claims: 0,
        claims_fresh: 0,
      }),
      answer(),
    ],
    claims: {
      total: 6,
      fresh: 4,
      entity_scoped: 4,
      match_scoped: 2,
      flagged: 0,
      by_status: { PROBABLE: 3, CONFIRMED: 1, RUMOR: 2 },
      by_class: SOURCE_CLASSES.map((k) => {
        if (k === "OFFICIAL") return breakdown(k, 2, 2, { CONFIRMED: 1, PROBABLE: 1 });
        if (k === "RELIABLE_MEDIA") return breakdown(k, 3, 2, { PROBABLE: 2, RUMOR: 1 });
        if (k === "SOCIAL") return breakdown(k, 1, 0, { RUMOR: 1 });
        return breakdown(k, 0, 0);
      }),
      by_type: CLAIM_TYPES.map((k) => {
        if (k === "OUT") return breakdown(k, 3, 2, { CONFIRMED: 1, PROBABLE: 2 });
        if (k === "DOUBT") return breakdown(k, 2, 1, { RUMOR: 2 });
        if (k === "STARTER") return breakdown(k, 1, 1, { PROBABLE: 1 });
        return breakdown(k, 0, 0);
      }),
    },
    per_day: [
      day(),
      day({
        day: "2026-10-24",
        passes: 2,
        passes_v2: 2,
        searches: 4,
        demand: 1,
        paid: 1,
        shared: 0,
        reused: 3,
        pages: 3,
        pages_known: 1,
        claims: 2,
        claims_new: 2,
        exa_v1_usd: "0.0050",
        exa_v2_usd: "0.0070",
      }),
    ],
    pages: { remembered: 12, fresh: 9, reuses: 5, read: 10, known: 3, unread: 2, flagged: 0 },
    comparison: { status: "ok", data: comparison(), reason: null },
    gate: { status: "ok", data: pending(), reason: null },
    ...over,
  };
}

/** A system with nothing to look at. */
const quiet = () => overview();

const render = (o: EntityResearchOverview) => text(renderToStaticMarkup(<TopicsBody o={o} />));
const raw = (o: EntityResearchOverview) => renderToStaticMarkup(<TopicsBody o={o} />);

// ── what to look at ──────────────────────────────────────────────────────────

describe("what to look at", () => {
  test("a quiet system says there is nothing to attend to", () => {
    const html = render(quiet());
    expect(html).toContain("Qué mirar");
    expect(html).toContain("Nada que atender");
  });

  test("a loud one lists what, most serious first, with how many", () => {
    const o = overview({
      comparison: { status: "not_available", data: null, reason: "x", code: "comparison_failed" },
      per_day: [day({ passes_failed: 2, passes_cut: 1 })],
      switch: switchOf({ asked: "on", mode: "shadow" }),
      claims: { ...quiet().claims, flagged: 3 },
      pages: { ...quiet().pages, flagged: 2 },
      freshness: { ...quiet().freshness, unreadable: 4 },
    });
    const html = render(o);
    expect(html).not.toContain("Nada que atender");
    const order = [
      "Partes de esta página que no se pudieron calcular: 1",
      "Pases en los que la investigación v2 falló: 2",
      "Pases en los que la investigación v2 se cortó (presupuesto o caída de la búsqueda): 1",
      "Se pidió «on», pero la puerta no ha pasado: v2 sigue corriendo en shadow, junto a v1",
      "Afirmaciones leídas de páginas que sonaban a una orden para un modelo: 3",
      "Páginas marcadas porque parecían una instrucción: 2",
      "Filas de la caché de entidades que este código no sabe leer: 4",
    ].map((line) => html.indexOf(line));
    expect(order.every((i) => i >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
  });

  test("a part of the page that could not be computed is an alarm; the rest are warnings", () => {
    const alarm = raw(
      overview({
        gate: { status: "not_available", data: null, reason: "x", code: "gate_failed" },
      }),
    );
    expect(alarm).toContain('role="alert"');
    expect(alarm).toContain('data-testid="topics-attention"');
    const warning = raw(overview({ claims: { ...quiet().claims, flagged: 1 } }));
    expect(warning).toContain('data-tone="warning"');
    expect(warning).not.toContain('data-tone="negative"');
  });

  test("a switch that is on and asked for it is not held; one asked for while nothing ran is a switch nobody obeys", () => {
    const fine = render(
      overview({
        switch: switchOf({ asked: "on", mode: "on", gate_passed: true, gate_at: GATE_AT }),
      }),
    );
    expect(fine).not.toContain("Se pidió «on»");
    const idle = render(overview({ per_day: [day({ passes_v2: 0 })] }));
    expect(idle).toContain(
      "El interruptor no está apagado, pero ningún pase de la ventana ejecutó la investigación v2",
    );
  });
});

// ── the switch ───────────────────────────────────────────────────────────────

describe("the switch", () => {
  test("in shadow: what was asked, what is in force, that the typed claims are hidden and that the gate was never recorded", () => {
    const html = render(quiet());
    expect(html).toContain("Interruptor de la investigación v2");
    expect(html).toContain("Pedido shadow");
    expect(html).toContain("En vigor shadow");
    expect(html).toContain("Ocultas: solo se miden");
    expect(html).toContain("Nunca se registró");
    expect(html).toContain("Shadow: v2 corre junto a v1 y nadie lee lo suyo");
  });

  test("the reason the server gives is shown as it wrote it", () => {
    expect(render(quiet())).toContain("FBI_AI_RESEARCH_V2=shadow: research v2 runs after v1");
  });

  test("off says v1 researches alone", () => {
    const html = render(overview({ switch: switchOf({ asked: "off", mode: "off" }) }));
    expect(html).toContain("Apagada: v1 investiga sola");
  });

  test("on, with the gate passed: v2 replaces v1 and the system reads the typed claims", () => {
    const html = render(
      overview({
        switch: switchOf({
          asked: "on",
          mode: "on",
          typed_visible: true,
          gate_passed: true,
          gate_at: GATE_AT,
        }),
      }),
    );
    expect(html).toContain("En vigor: v2 sustituye a v1");
    expect(html).toContain("Las lee el sistema");
    expect(html).toContain(`Pasó el ${bogotaDateTime(GATE_AT)}`);
    expect(html).not.toContain("retenida como shadow");
  });

  test("on asked and held as shadow because the newest verdict of the gate is a failure says so, with the date", () => {
    const html = render(
      overview({
        switch: switchOf({ asked: "on", mode: "shadow", gate_passed: false, gate_at: GATE_AT }),
      }),
    );
    expect(html).toContain("Pedida «on» y retenida como shadow: la puerta no ha pasado");
    expect(html).toContain(`No pasó el ${bogotaDateTime(GATE_AT)}`);
  });

  test("the verdicts recorded by the gate: when, which, who, the version of the code and the first twelve characters of the fingerprint", () => {
    const html = render(
      overview({
        switch: switchOf({
          gate_at: "2026-10-25T21:00:00Z",
          history: [
            gateRow({ id: 2, passed: false, decided_by: "ops", code_version: null }),
            gateRow({ id: 1 }),
          ],
        }),
      }),
    );
    expect(html).toContain("Veredictos registrados de la puerta");
    expect(html).toContain("Pasó");
    expect(html).toContain("No pasó");
    expect(html).toContain("ia_research_gate");
    expect(html).toContain("ia-p02");
    expect(html).toContain("0123456789ab");
    expect(html).not.toContain("0123456789abc");
    expect(html).not.toContain("La puerta nunca se registró");
  });

  test("with no verdict recorded it says how one is recorded", () => {
    const html = render(quiet());
    expect(html).toContain("La puerta nunca se registró");
    expect(html).toContain("python -m scripts.ia_research_gate evaluate --record");
  });
});

// ── the gate ─────────────────────────────────────────────────────────────────

describe("the gate", () => {
  test("while it cannot be judged it says so in its own words, with the days it has and the ones it lacks", () => {
    const html = render(quiet());
    expect(html).toContain("Puerta de la investigación v2");
    expect(html).toContain("PENDIENTE POR TIEMPO REAL");
    expect(html).toContain("1 de 7");
    expect(html).toContain("Lo que falta");
    expect(html).toContain("1 de 7 días completos con research v2 en sombra");
    expect(html).toContain("a change declared by whoever deployed it, on 2026-10-24");
  });

  test("a gate that cannot be judged is a warning and draws no table of checks", () => {
    const html = raw(quiet());
    expect(html).toContain('data-testid="topics-gate-pending"');
    expect(html).not.toContain("Si falla, se revierte");
    expect(html).not.toContain('data-testid="topics-gate-consequence"');
  });

  test("what the days gone show is told as no evidence, and the percentages are written in Spanish", () => {
    const html = render(quiet());
    expect(html).toContain("Lo que muestran los días transcurridos");
    expect(html).toContain("No es evidencia de la puerta");
    expect(html).toContain("Búsquedas ahorradas 40,0 %");
    expect(html).toContain("Cobertura de v1 96,7 %");
    expect(html).toContain("Cobertura de quién puede jugar 90,0 %");
    expect(html).toContain("Partidos con hechos de v1 14");
  });

  test("it says the page only reads and how the gate is recorded", () => {
    const html = render(quiet());
    expect(html).toContain("Esta página solo lee");
    expect(html).toContain("solo queda registrado un veredicto PASA o NO PASA");
  });

  test("judged and passed: seven checks in the order the gate judges them, each in the reader's words with the gate's own title beneath", () => {
    const html = render(overview({ gate: { status: "ok", data: judged(), reason: null } }));
    expect(html).toContain("PASA");
    expect(html).not.toContain("Lo que falta");
    const order = [
      "Siete días completos con v2 en shadow",
      "Menos búsquedas que v1",
      "Cobertura de las evidencias de v1 (≥ 95 %)",
      "Cobertura de quién puede jugar (≥ 95 %)",
      "En shadow nada cita a v2",
      "Auditoría nocturna «evidence_known» sin violaciones",
      "Muestra suficiente de partidos y hechos",
    ].map((line) => html.indexOf(line));
    expect(order.every((i) => i >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    expect(html).toContain("titulo-fewer_searches");
    expect(html).toContain("7 de 7");
  });

  test("a check shows its detail pairs and the switch that is rolled back when it fails", () => {
    const html = render(overview({ gate: { status: "ok", data: judged(), reason: null } }));
    expect(html).toContain("facts_v1 61");
    expect(html).toContain("minimum_facts 50");
    expect(html).toContain("FBI_AI_RESEARCH_V2");
    expect(html).toContain("Si falla, se revierte");
  });

  test("a verdict of NO PASA marks the failing check, names the consequence as an alarm and stays a failure", () => {
    const o = overview({
      gate: { status: "ok", data: judged({}, ["coverage"]), reason: null },
    });
    const html = render(o);
    expect(html).toContain("NO PASA");
    expect(html).toContain("Consecuencia");
    expect(html).toContain("se revierte el interruptor que falle: FBI_AI_RESEARCH_V2 vuelve a off");
    expect(raw(o)).toContain('data-testid="topics-gate-consequence"');
    const row = html.slice(html.indexOf("Cobertura de las evidencias de v1"));
    expect(row.slice(0, 200)).toContain("No");
  });

  test("a verdict this page does not know is shown as the server wrote it", () => {
    const html = render(
      overview({ gate: { status: "ok", data: pending({ verdict: "QUIZÁ" }), reason: null } }),
    );
    expect(html).toContain("QUIZÁ");
  });

  test("a check this page has no name for is shown by its id", () => {
    const html = render(
      overview({
        gate: {
          status: "ok",
          data: judged({ checks: [check({ id: "brand_new_check", title: "algo nuevo" })] }),
          reason: null,
        },
      }),
    );
    expect(html).toContain("brand_new_check");
    expect(html).toContain("algo nuevo");
  });

  test("a gate that could not be evaluated says so in the reader's words and takes no other part down", () => {
    const html = render(
      overview({
        gate: {
          status: "not_available",
          data: null,
          reason: "gate_failed: OperationalError",
          code: "gate_failed",
        },
      }),
    );
    expect(html).toContain("No se pudo evaluar la puerta de la investigación v2");
    expect(html).not.toContain("OperationalError");
    for (const kept of [
      "Interruptor de la investigación v2",
      "Investigación v1 frente a v2",
      "Frescura por tema",
      "Respuestas guardadas",
      "Páginas leídas",
    ]) {
      expect(html).toContain(kept);
    }
  });

  test("a gate section with no data at all says there is no evaluation to show", () => {
    const html = render(overview({ gate: { status: "ok", data: null, reason: null } }));
    expect(html).toContain("Esta página no tiene una evaluación de la puerta que mostrar");
  });
});

// ── v1 against v2 ────────────────────────────────────────────────────────────

describe("research v1 against v2", () => {
  test("the window, the passes compared and what failed or was cut", () => {
    const html = render(quiet());
    expect(html).toContain("Investigación v1 frente a v2");
    expect(html).toContain("Pases comparados 8");
    expect(html).toContain("9 en shadow · 1 con fallo de v2 · 0 cortados");
    expect(html).toContain("Del ");
  });

  test("the searches of each research, what v2 saved and how much of what it needed a fresh answer spared", () => {
    const html = render(quiet());
    expect(html).toContain("Búsquedas de v1 20");
    expect(html).toContain("Búsquedas de v2 por sí sola 12");
    expect(html).toContain("Búsquedas ahorradas 8 40,0 %");
    expect(html).toContain("Reutilización 55,5 %");
  });

  test("the coverage of the facts of v1, and of those about who can play, with how many were found", () => {
    const html = render(quiet());
    expect(html).toContain("Cobertura de v1 96,7 %");
    expect(html).toContain("29 de 30 hechos de v1 los encontró también v2");
    expect(html).toContain("Cobertura de quién puede jugar 90,0 %");
    expect(html).toContain("Hechos por partido (v1 · v2) 2,14 · 2,07");
    expect(html).toContain("Sobre 14 partidos con hechos de v1");
  });

  test("a percentage that could not be computed is a dash, never a zero", () => {
    const html = render(
      overview({
        comparison: {
          status: "ok",
          data: comparison({
            coverage_pct: null,
            coverage_players_pct: null,
            extractor_invalid_pct: null,
            saved_pct: null,
            reuse_pct: null,
            facts_per_match_v1: null,
            facts_per_match_v2: null,
          }),
          reason: null,
        },
      }),
    );
    expect(html).toContain("Cobertura de v1 —");
    expect(html).toContain("Cobertura de quién puede jugar —");
    expect(html).toContain("Salidas inválidas del extractor —");
    expect(html).toContain("Hechos por partido (v1 · v2) — · —");
    expect(html).not.toContain("Cobertura de v1 0");
  });

  test("the spend in Exa of each research and the calls of the extractor, by how they ended, the good ones first", () => {
    const html = render(quiet());
    expect(html).toContain("Gasto en Exa de v1");
    expect(html).toContain("20 búsquedas");
    expect(html).toContain("Gasto en Exa de v2");
    expect(html).toContain("12 búsquedas");
    expect(html).toContain("Llamadas del extractor 11");
    expect(html).toContain("ok 10 · invalid_output 1");
    expect(html).toContain("Salidas inválidas del extractor 9,1 %");
  });

  test("the facts of v1 that v2 did not find, as examples, or that there are none", () => {
    expect(render(quiet())).toContain("9370001 · home · Marcus Rashford · OUT");
    const none = render(
      overview({
        comparison: { status: "ok", data: comparison({ missed_examples: [] }), reason: null },
      }),
    );
    expect(none).toContain("v2 encontró todos los hechos de v1 de la ventana");
  });

  test("no pass ran v2 beside v1: the page says there is nothing to compare, in the reader's words", () => {
    const html = render(
      overview({
        comparison: {
          status: "empty",
          data: null,
          reason: "no pass of the window ran research v2 beside v1",
          code: "no_v2_passes",
        },
      }),
    );
    expect(html).toContain(
      "Ningún pase de la ventana ejecutó la investigación v2 junto a v1: todavía no hay nada que comparar.",
    );
    expect(html).not.toContain("Gasto en Exa de v1");
    expect(html).not.toContain("Hechos de v1 que v2 no encontró");
    expect(html).toContain("Frescura por tema");
  });

  test("a comparison that could not be computed says so and takes no other part down", () => {
    const html = render(
      overview({
        comparison: {
          status: "not_available",
          data: null,
          reason: "comparison_failed: ValueError",
          code: "comparison_failed",
        },
      }),
    );
    expect(html).toContain("No se pudo calcular la comparación entre v1 y v2");
    expect(html).not.toContain("ValueError");
    expect(html).toContain("Puerta de la investigación v2");
    expect(html).toContain("Día a día del ciclo");
  });
});

// ── the cache ────────────────────────────────────────────────────────────────

describe("the freshness of each topic", () => {
  test("the three topics, what they are about, their levels and how long an answer holds far from the kick-off and near it", () => {
    const html = render(quiet());
    expect(html).toContain("Frescura por tema");
    for (const word of ["Disponibilidad", "Confirmación", "Previa"]) expect(html).toContain(word);
    expect(html).toContain("quién puede jugar (bajas, dudas, sanciones)");
    expect(html).toContain("confirmar con fuentes oficiales");
    expect(html).toContain("1 · 2");
    expect(html).toContain("24 h / 4 h");
    expect(html).toContain("Equipo");
    expect(html).toContain("Partido");
  });

  test("answers kept, fresh and expired, with the share that can still be reused", () => {
    const html = render(quiet());
    expect(html).toContain("75 %");
    expect(html).toContain("100 %");
  });

  test("the window that separates near from far is told in hours", () => {
    expect(render(quiet())).toContain("«Cerca» son las últimas 12 h antes del saque más próximo");
  });

  test("an empty cache says v2 has searched nothing", () => {
    const empty = overview({
      freshness: {
        late_window_hours: 12,
        topics: quiet().freshness.topics.map((t) => ({
          ...t,
          entries: 0,
          fresh: 0,
          expired: 0,
          reuses: 0,
          newest_at: null,
          last_reuse_at: null,
        })),
        unreadable: 0,
      },
    });
    const html = render(empty);
    expect(html).toContain("v2 aún no ha buscado nada");
    expect(render(quiet())).not.toContain("v2 aún no ha buscado nada");
  });

  test("rows of the cache this code does not read are counted, not interpreted", () => {
    const html = render(overview({ freshness: { ...quiet().freshness, unreadable: 3 } }));
    expect(html).toContain("con una clave que este código no lee: 3");
    expect(render(quiet())).not.toContain("con una clave que este código no lee");
  });

  test("a topic this page has no name for is shown by its key", () => {
    const html = render(
      overview({
        freshness: {
          ...quiet().freshness,
          topics: [topic({ topic: "mystery", entity: "STADIUM", label: "algo" })],
        },
      }),
    );
    expect(html).toContain("mystery");
    expect(html).toContain("STADIUM");
  });
});

describe("the answers kept", () => {
  test("the newest first, the entity named as the server named it and the topic in the reader's word", () => {
    const html = render(quiet());
    expect(html).toContain("Respuestas guardadas");
    expect(html.indexOf("Manchester United vs Liverpool")).toBeGreaterThan(-1);
    expect(html.indexOf("Manchester United vs Liverpool")).toBeLessThan(
      html.indexOf("Manchester United", html.indexOf("Manchester United vs Liverpool") + 40),
    );
    expect(html).toContain("las afirmaciones que dejaron en los últimos 7 días");
  });

  test("an entity the server could not name is shown by its number", () => {
    const html = render(
      overview({ answers: [answer({ kind: "PLAYER", id: 77, name: null, kickoff_at: null })] }),
    );
    expect(html).toContain("#77");
    expect(html).toContain("Jugador");
  });

  test("the results by tier of source, in the order of the tiers, and a tier the page does not know is shown too", () => {
    const html = render(
      overview({ answers: [answer({ tiers: { media: 4, official: 1, rumour_mill: 2 } })] }),
    );
    const a = html.indexOf("Oficial · 1");
    const b = html.indexOf("Medio · 4");
    const c = html.indexOf("rumour_mill · 2");
    expect(a).toBeGreaterThan(-1);
    expect(b).toBeGreaterThan(a);
    expect(c).toBeGreaterThan(b);
  });

  test("a source of known standing is said, and so is the lack of one; an answer that records neither shows a dash", () => {
    const yes = render(overview({ answers: [answer({ standing: true })] }));
    const no = render(overview({ answers: [answer({ standing: false })] }));
    const none = render(
      overview({ answers: [answer({ standing: null, level: null, results: null })] }),
    );
    expect(yes).toContain("Fuente reconocida");
    expect(raw(overview({ answers: [answer({ standing: true })] }))).toContain("Sí");
    expect(no).toContain("No");
    expect(none).toContain("—");
  });

  test("fresh or expired, until when, how many times it was reused and how many claims it left, of which current", () => {
    const html = render(
      overview({
        answers: [
          answer({
            fresh: false,
            expires_at: "2026-10-25T10:00:00Z",
            reuses: 6,
            claims: 5,
            claims_fresh: 2,
          }),
        ],
      }),
    );
    expect(html).toContain("Caducada");
    expect(html).toContain(`hasta el ${bogotaDateTime("2026-10-25T10:00:00Z")}`);
    expect(html).toContain("5 (2 vigentes)");
    const fresh = render(overview({ answers: [answer()] }));
    expect(fresh).toContain("Fresca");
  });

  test("with no answer kept it says so", () => {
    expect(render(overview({ answers: [] }))).toContain(
      "La caché todavía no guarda respuestas por entidad",
    );
  });
});

// ── the claims ───────────────────────────────────────────────────────────────

describe("the claims", () => {
  test("the figures: all, current, about an entity, about a match and those from flagged pages", () => {
    const html = render(quiet());
    expect(html).toContain("Afirmaciones por clase de fuente y estado");
    expect(html).toContain("Afirmaciones 6");
    expect(html).toContain("Vigentes 4");
    expect(html).toContain("Sobre una entidad 4");
    expect(html).toContain("Sobre un partido 2");
    expect(html).toContain("De páginas marcadas 0");
  });

  test("the states they ended in, the surest first, only those with something", () => {
    const html = render(quiet());
    const a = html.indexOf("Confirmadas · 1");
    const b = html.indexOf("Probables · 3");
    const c = html.indexOf("Rumores · 2");
    expect(a).toBeGreaterThan(-1);
    expect(b).toBeGreaterThan(a);
    expect(c).toBeGreaterThan(b);
    expect(html).not.toContain("Contradictorias · ");
    expect(html).not.toContain("Desactualizadas · ");
  });

  test("by class of source: each in the reader's word with its code, the totals, and only the states anybody used as columns", () => {
    const html = render(quiet());
    expect(html).toContain("Por clase de fuente");
    expect(html).toContain("Oficial");
    expect(html).toContain("Medio fiable");
    expect(html).toContain("Red social");
    expect(html).toContain("RELIABLE_MEDIA");
    const head = html.slice(html.indexOf("Clase de fuente"), html.indexOf("Clase de fuente") + 120);
    expect(head).toContain("Total");
    expect(head).toContain("Vigentes");
    expect(head).toContain("Confirmadas");
    expect(head).not.toContain("Contradictorias");
  });

  test("by type of claim", () => {
    const html = render(quiet());
    expect(html).toContain("Por tipo de afirmación");
    for (const word of ["Baja", "Duda", "Titular"]) expect(html).toContain(word);
  });

  test("the classes of source that wrote nothing are named, since that is a finding", () => {
    const html = render(quiet());
    expect(html).toContain("Clases de fuente sin ninguna afirmación en la ventana:");
    expect(html).toContain("Proveedor de datos, Periodista");
    expect(html).not.toContain("Clases de fuente sin ninguna afirmación en la ventana: Oficial");
  });

  test("claims from flagged pages are a warning, with what that means", () => {
    const html = render(overview({ claims: { ...quiet().claims, flagged: 2 } }));
    expect(html).toContain("De páginas marcadas 2");
    expect(html).toContain("cuentan como fuente desconocida");
  });

  test("no claim at all says v2 wrote none, and does not claim every class of source was silent", () => {
    const html = render(
      overview({
        claims: {
          total: 0,
          fresh: 0,
          entity_scoped: 0,
          match_scoped: 0,
          flagged: 0,
          by_status: {},
          by_class: SOURCE_CLASSES.map((k) => breakdown(k, 0, 0)),
          by_type: CLAIM_TYPES.map((k) => breakdown(k, 0, 0)),
        },
      }),
    );
    expect(html).toContain("v2 no escribió ninguna afirmación tipificada en la ventana");
    expect(html).not.toContain("Clases de fuente sin ninguna afirmación en la ventana");
  });

  test("a class or a state this page does not know is shown as it is", () => {
    const html = render(
      overview({
        claims: {
          ...quiet().claims,
          by_status: { WITHDRAWN: 2 },
          by_class: [breakdown("CARRIER_PIGEON", 2, 0, { WITHDRAWN: 2 })],
        },
      }),
    );
    expect(html).toContain("CARRIER_PIGEON");
    expect(html).toContain("WITHDRAWN");
  });
});

// ── the days and the pages ───────────────────────────────────────────────────

describe("the days of the cycle", () => {
  test("a row for each day with what the passes did, and the total of the window", () => {
    const html = render(quiet());
    expect(html).toContain("Día a día del ciclo");
    for (const word of [
      "Pases",
      "Con v2",
      "Fallidos",
      "Cortados",
      "Búsquedas de v1",
      "Necesarias",
      "Pagadas",
      "Compartidas",
      "Reutilizadas",
      "Reutilización",
      "Exa v1",
      "Exa v2",
    ]) {
      expect(html).toContain(word);
    }
    const total = html.slice(html.indexOf("Total", html.indexOf("Día a día del ciclo")));
    expect(total).toContain("6");
  });

  test("the pages and claims of a day carry how many were already known and how many are new", () => {
    const html = render(quiet());
    expect(html).toContain("(2 conocidas)");
    expect(html).toContain("(4 nuevas)");
  });

  test("the reuse of a day is what a fresh answer spared of what v2 needed, and a day that needed nothing shows none", () => {
    const html = raw(overview({ per_day: [day({ reused: 6, demand: 2 })] }));
    expect(text(html)).toContain("75 %");
    const idle = raw(overview({ per_day: [day({ reused: 0, demand: 0 })] }));
    const row = idle.slice(idle.indexOf('data-testid="topics-days"'));
    expect(text(row)).toContain("—");
  });

  test("the money is written as money, and the total adds the days up without the drift of decimals", () => {
    const html = render(quiet());
    expect(html).toContain("US$");
    expect(html).toContain("0,03");
    expect(html).toContain("US$ 0,0050");
    const total = html.slice(html.indexOf("Total", html.indexOf("Día a día del ciclo")));
    expect(total).toContain("US$ 0,04");
    expect(total).toContain("US$ 0,02");
  });

  test("it explains what each column means", () => {
    expect(render(quiet())).toContain("Reutilización = reutilizadas / (reutilizadas + necesarias)");
  });
});

describe("the pages read", () => {
  test("what is remembered, how much of it still holds, how many times it was reused and what was read", () => {
    const html = render(quiet());
    expect(html).toContain("Páginas leídas");
    expect(html).toContain("Páginas recordadas 12");
    expect(html).toContain("Aún vigentes 9");
    expect(html).toContain("Reutilizaciones 5");
    expect(html).toContain("Leídas en la ventana 10");
    expect(html).toContain("Ya conocidas 3");
    expect(html).toContain("Sin leer 2");
    expect(html).toContain("Marcadas 0");
  });

  test("pages that looked like an instruction to a model are a warning", () => {
    const html = render(overview({ pages: { ...quiet().pages, flagged: 2 } }));
    expect(html).toContain("Marcadas 2");
    expect(html).toContain("su texto se trata como no fiable");
  });
});

// ── English ──────────────────────────────────────────────────────────────────

describe("in English", () => {
  test("the same body reads in English", () => {
    setLocale("en");
    const html = render(quiet());
    for (const word of [
      "What to look at",
      "Nothing to attend to",
      "Research v2 switch",
      "Gate of research v2",
      "PENDING ON REAL TIME",
      "Research v1 against v2",
      "Freshness by topic",
      "Answers kept",
      "Claims by class of source and state",
      "Day by day of the cycle",
      "Pages read",
      "Hidden: only measured",
      "Never recorded",
      "Shadow: v2 runs beside v1 and nobody reads its work",
    ]) {
      expect(html).toContain(word);
    }
    for (const spanish of [
      "Qué mirar",
      "Nada que atender",
      "Frescura por tema",
      "Páginas leídas",
    ]) {
      expect(html).not.toContain(spanish);
    }
  });

  test("the percentages and the figures use the English marks", () => {
    setLocale("en");
    const html = render(quiet());
    expect(html).toContain("Searches saved 8 40.0%");
    expect(html).toContain("Coverage of v1 96.7%");
    expect(html).toContain("Facts per match (v1 · v2) 2.14 · 2.07");
    expect(html).toContain("29 of 30 facts of v1 were found by v2 too");
  });

  test("a judged gate and a held switch read in English", () => {
    setLocale("en");
    const html = render(
      overview({
        switch: switchOf({ asked: "on", mode: "shadow", gate_at: GATE_AT, gate_passed: false }),
        gate: { status: "ok", data: judged({}, ["sample"]), reason: null },
      }),
    );
    expect(html).toContain("DOES NOT PASS");
    expect(html).toContain("Asked “on” and held as shadow: the gate has not passed");
    expect(html).toContain("Enough matches and facts compared");
    expect(html).toContain("Consequence");
    expect(html).toContain("If it fails, roll back");
  });

  test("the sections that could not be computed read in English", () => {
    setLocale("en");
    const html = render(
      overview({
        comparison: { status: "empty", data: null, reason: "x", code: "no_v2_passes" },
        gate: { status: "not_available", data: null, reason: "x", code: "gate_failed" },
      }),
    );
    expect(html).toContain("No pass of the window ran research v2 beside v1");
    expect(html).toContain("The gate of research v2 could not be evaluated");
  });
});

// ── the words of the view ────────────────────────────────────────────────────

describe("the words of the view", () => {
  const WORDS: Array<[string, readonly string[]]> = [
    [
      "ai.topics.attention",
      [
        "part_unavailable",
        "v2_failed",
        "v2_cut",
        "not_running",
        "held_as_shadow",
        "claims_flagged",
        "pages_flagged",
        "unreadable",
      ],
    ],
    ["ai.topics.switch.state", ["off", "shadow", "on", "held"]],
    ["ai.topics.switch.gateState", ["never", "passed", "failed"]],
    ["ai.topics.gate.check", GATE_CHECKS],
    ["ai.topics.gate.mark", ["yes", "no", "pending"]],
    ["ai.topics.gate.verdict", ["pass", "fail", "pending"]],
    ["ai.topics.gate.preview.figure", PREVIEW_FIGURES.map(([, key]) => key)],
    ["ai.topics.freshness.topic", TOPICS],
    ["ai.topics.entity", ENTITY_KINDS],
    ["ai.topics.answers.tier", TIERS],
    ["ai.topics.claims.status", CLAIM_STATUSES],
    ["ai.topics.claims.class", SOURCE_CLASSES],
    ["ai.topics.claims.type", CLAIM_TYPES],
    ["common.sectionCode", ["no_v2_passes", "comparison_failed", "gate_failed"]],
  ];

  test("every word the page counts by has its translation in Spanish and in English", () => {
    for (const locale of ["es", "en"] as const) {
      for (const [prefix, words] of WORDS) {
        for (const word of words) {
          expect(`${locale}:${prefix}.${word}:${hasKey(`${prefix}.${word}`, locale)}`).toBe(
            `${locale}:${prefix}.${word}:true`,
          );
        }
      }
    }
  });

  test("the view is named in both languages", () => {
    for (const locale of ["es", "en"] as const) {
      expect(hasKey("admin.operation.aiViews.topics", locale)).toBe(true);
    }
  });
});
