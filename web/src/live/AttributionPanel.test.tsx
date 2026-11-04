/// <reference types="bun" />
/**
 * PLAN IA phase 5, the attribution in the Admin Console (Aprendizaje, "Atribución"): the share of matches with attributions is shown against the plan's
 * bar and never as a verdict of the gate (zero matches is a dash, not 100 %); each agent shows its version and what it did about a selection; a miss
 * shows the class the code set and the one the reviewer added; the narrative is the AI's and says so; a hypothesis shows its agent, its version and the
 * ids of the attributions it cites; and every word is in both languages.
 */
import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import type { AttributionOverview } from "@/lib/api/v1/types_ai_attribution";
import { AttributionBody } from "./AttributionPanel";
import { citedIds, coverageState, sortedClasses } from "./attributionModel";

// Test files share one process and one i18n module: another file may leave "en" behind, so start every test in Spanish.
beforeEach(() => setLocale("es"));
afterEach(() => setLocale("es"));

const text = (html: string) =>
  html
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ");

const EMPTY: AttributionOverview = {
  switches: {
    pm_reviewer: false,
    learning_analyst: false,
    reviewer_version: "pmr-v1",
    analyst_version: "la-v1",
    attribution_version: "attr-v1",
  },
  coverage: {
    since: "2026-10-20",
    until: "2026-11-03",
    matches: 0,
    attributed_matches: 0,
    match_share: null,
    selections: 0,
    attributed_selections: 0,
    selection_share: null,
    bar: 0.95,
  },
  scoreboard: [],
  classes: [],
  postmortems: [],
  hypotheses: [],
  hypothesis_counts: [],
  days: 14,
};

const FULL: AttributionOverview = {
  ...EMPTY,
  switches: { ...EMPTY.switches, pm_reviewer: true },
  coverage: {
    ...EMPTY.coverage,
    matches: 20,
    attributed_matches: 19,
    match_share: 0.95,
    selections: 25,
    attributed_selections: 22,
    selection_share: 0.88,
  },
  scoreboard: [
    {
      agent: "council",
      agent_version: "council-v1",
      engine: "ma-v1",
      hits: 7,
      misses: 3,
      voids: 1,
      hit_rate: 0.7,
    },
  ],
  classes: [
    { agent: "council", agent_version: "council-v1", error_class: "UNKNOWN", n: 2, refined: 1 },
    { agent: "council", agent_version: "council-v1", error_class: "MODEL_ERROR", n: 1, refined: 0 },
  ],
  postmortems: [
    {
      postmortem_id: 11,
      fixture_id: 5,
      match: "Millonarios - Nacional",
      kickoff_at: "2026-11-01T20:00:00Z",
      market_key: "1X2",
      selection: "Home",
      line: 0,
      settled: "lost",
      calibration: "MARKET_BETTER",
      clv: -0.055,
      narrative: "El mercado sabía algo que el modelo no leyó.",
      lines: [
        {
          engine: "ma-v1",
          agent: "council",
          agent_version: "council-v1",
          signal: "VERDICT",
          stance: "FOR",
          outcome: "MISS",
          error_class: "UNKNOWN",
          refined_class: "CONTEXT_ERROR",
          toward_close: false,
        },
        {
          engine: "ma-v1",
          agent: "match",
          agent_version: "match-v1",
          signal: "ABSENCES",
          stance: "NONE",
          outcome: "VOID",
          error_class: "NONE",
          refined_class: null,
          toward_close: null,
        },
      ],
    },
  ],
  hypotheses: [
    {
      id: 3,
      agent: "council",
      agent_version: "council-v1",
      title: "El Council falla cuando el mercado se mueve en contra",
      hypothesis: "Bajar el peso del veredicto si MARKET_MOVE es fuerte.",
      rationale: "Dos fallos de la misma clase.",
      status: "PROPOSED",
      created_at: "2026-11-02T10:00:00Z",
      decided_at: null,
      attribution_ids: [4, 9, 12],
      experiment: { design: "shadow A/B", sample: "300" },
      week_from: "2026-10-26",
    },
  ],
  hypothesis_counts: [
    {
      agent: "council",
      agent_version: "council-v1",
      proposed: 1,
      accepted: 0,
      rejected: 0,
      other: 1,
    },
  ],
};

const render = (d: AttributionOverview) => renderToStaticMarkup(<AttributionBody d={d} />);

describe("the model", () => {
  test("the coverage is judged against the bar, and nothing to judge is not a pass", () => {
    expect(coverageState({ match_share: null, bar: 0.95 })).toBe("none");
    expect(coverageState({ match_share: 0.94, bar: 0.95 })).toBe("below");
    expect(coverageState({ match_share: 0.95, bar: 0.95 })).toBe("reached");
  });
  test("the ids are written with a hash and the classes keep the order of the plan", () => {
    expect(citedIds([4, 9, 12])).toBe("#4, #9, #12");
    expect(
      sortedClasses([
        { error_class: "UNKNOWN" },
        { error_class: "MODEL_ERROR" },
        { error_class: "ZZZ" },
      ]),
    ).toEqual([{ error_class: "MODEL_ERROR" }, { error_class: "UNKNOWN" }, { error_class: "ZZZ" }]);
  });
});

describe("the page", () => {
  test("with nothing attributed it says so, shows dashes and not a hundred percent, and never says a gate passed", () => {
    const t = text(render(EMPTY));
    expect(t).toContain("No hay partidos que juzgar");
    expect(t).toContain("Ningún post-mortem tiene atribución");
    expect(t).toContain("no ha propuesto hipótesis");
    expect(t).not.toContain("100");
    expect(t).not.toMatch(/pas[óo] la puerta|gate passed/i);
    expect(render(EMPTY)).toContain('data-testid="attribution-switches"');
    expect(t).toContain("Apagado");
  });

  test("the coverage shows the share, the counts behind it and the bar", () => {
    const html = render(FULL);
    const t = text(html);
    expect(t).toContain("19 de 20");
    expect(t).toContain("22 de 25");
    expect(t).toContain("95");
    expect(t).toContain("En o por encima de la barra del plan");
    expect(t).toContain("Encendido");
  });

  test("each agent shows its version and the post-mortem shows what each did, the class of the miss and the one the reviewer added", () => {
    const html = render(FULL);
    const t = text(html);
    expect(t).toContain("council-v1");
    expect(t).toContain("match-v1");
    expect(t).toContain("Millonarios - Nacional");
    expect(t).toContain("Sin clasificar");
    expect(t).toContain("Refinada por el revisor: Error de contexto");
    expect(html.match(/data-testid="attribution-line"/g)?.length).toBe(2);
    expect(html.match(/data-testid="score-row"/g)?.length).toBe(1);
    expect(t).toContain("70");
  });

  test("the narrative is shown as the AI's", () => {
    const t = text(render(FULL));
    expect(t).toContain("escrita por la IA");
    expect(t).toContain("El mercado sabía algo que el modelo no leyó.");
    expect(
      render({ ...FULL, postmortems: [{ ...FULL.postmortems[0]!, narrative: null }] }),
    ).not.toContain("attribution-narrative");
  });

  test("a hypothesis shows its agent, its version, the ids it cites and the experiment as a draft", () => {
    const html = render(FULL);
    const t = text(html);
    expect(t).toContain("council · council-v1");
    expect(t).toContain("Atribuciones citadas (3)");
    expect(t).toContain("#4, #9, #12");
    expect(t).toContain("borrador, no ejecutado");
    expect(t).toContain("shadow A/B");
    expect(html).toContain("attribution-hypothesis-3");
  });

  test("the text of the AI is escaped, not run", () => {
    const hostile = {
      ...FULL,
      postmortems: [{ ...FULL.postmortems[0]!, narrative: "<script>alert(1)</script>" }],
    };
    const html = render(hostile);
    expect(html).not.toContain("<script>alert(1)</script>");
    expect(html).toContain("&lt;script&gt;");
  });

  test("every word is in English too", () => {
    setLocale("en");
    const t = text(render(FULL));
    expect(t).toContain("Hits and misses per agent and version");
    expect(t).toContain("Refined by the reviewer: Context error");
    expect(t).toContain("Cited attributions (3)");
    expect(t).not.toContain("ai.attribution");
  });

  test("no key is left unwritten in Spanish", () => {
    expect(text(render(FULL))).not.toContain("ai.attribution");
    expect(text(render(EMPTY))).not.toContain("ai.attribution");
  });
});
