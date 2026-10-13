/// <reference types="bun" />
import { afterAll, describe, expect, test } from "bun:test";
import { hasKey, setLocale } from "@/lib/i18n";
import type { AiBudgetAlert } from "@/lib/api/v1/types_ai_layer";
import {
  BUDGET_THRESHOLDS,
  ESCALATION_REASONS,
  LOSS_CLASSES,
  PASSES,
  POSTMORTEM_VERDICTS,
  QUESTIONS,
  analysisLabel,
  answerKind,
  answerTone,
  answerView,
  barPercent,
  budgetMarkers,
  budgetTone,
  canPromote,
  classTone,
  dayLabel,
  decisionsFor,
  edgePoints,
  evidenceSummary,
  gateTone,
  groupOf,
  levelRows,
  lossClassLabel,
  minutesText,
  orderedAnswers,
  passLabel,
  pct,
  pointsText,
  projectionTone,
  promoteUnlocked,
  PROMOTE_WORD,
  questionLabel,
  ratioOf,
  reasonLabel,
  sampleCounts,
  selectionText,
  settledLabel,
  teamsOf,
  thresholdText,
  usd,
  verdictLabel,
  verdictTone,
} from "./aiModel";

/** Intl writes a no-break space in "150,00 US$"-style output and in Spanish percentages. */
const NBSP = String.fromCharCode(160);
const plain = (s: string) => s.split(NBSP).join(" ");

afterAll(() => setLocale("es"));

describe("the owner's answers", () => {
  test("a proposal can be rejected, investigated or approved as an experiment - nothing else", () => {
    expect(decisionsFor("PROPOSED")).toEqual(["reject", "investigate", "approve_experiment"]);
    expect(decisionsFor("INVESTIGATING")).toEqual(["reject", "approve_experiment"]);
    for (const s of ["ACCEPTED", "RUNNING", "SHADOW", "DONE", "PROMOTED", "REJECTED"] as const) {
      expect(decisionsFor(s)).toEqual([]);
    }
  });

  test("only a DONE experiment whose gate passed is promotable", () => {
    expect(canPromote({ status: "DONE", outcome: { gate_passed: true } })).toBe(true);
    expect(canPromote({ status: "DONE", outcome: { gate_passed: false } })).toBe(false);
    expect(canPromote({ status: "DONE", outcome: null })).toBe(false);
    expect(canPromote({ status: "SHADOW", outcome: { gate_passed: true } })).toBe(false);
  });

  test("groups follow the stages", () => {
    expect(groupOf({ status: "PROPOSED", outcome: null })).toBe("pending");
    expect(groupOf({ status: "INVESTIGATING", outcome: null })).toBe("pending");
    expect(groupOf({ status: "RUNNING", outcome: null })).toBe("experiment");
    expect(groupOf({ status: "DONE", outcome: { gate_passed: true } })).toBe("promotable");
    expect(groupOf({ status: "DONE", outcome: { gate_passed: false } })).toBe("closed");
    expect(groupOf({ status: "PROMOTED", outcome: { gate_passed: true } })).toBe("closed");
  });

  test("a promotion needs the typed word", () => {
    expect(promoteUnlocked("")).toBe(false);
    expect(promoteUnlocked("promover ")).toBe(true);
    expect(promoteUnlocked(PROMOTE_WORD)).toBe(true);
    expect(promoteUnlocked("PROMOTE")).toBe(false);
  });
});

describe("labels", () => {
  test("probabilities as percentages", () => {
    expect(pct("0.4512")).toBe(45.1);
    expect(pct(0.5)).toBe(50);
    expect(pct(null)).toBeNull();
    expect(pct("x")).toBeNull();
  });

  test("'Analizado por PrediGol AI' only when a language model took part", () => {
    expect(analysisLabel(true)).toBe("ai");
    expect(analysisLabel(false)).toBe("rules");
  });
});

describe("V2: decisions on a proposal (its status is plain text)", () => {
  test("PROPOSED and INVESTIGATING proposals get the owner's answers; anything else none", () => {
    expect(decisionsFor("PROPOSED")).toEqual(["reject", "investigate", "approve_experiment"]);
    expect(decisionsFor("INVESTIGATING")).toEqual(["reject", "approve_experiment"]);
    expect(decisionsFor("SOMETHING_NEW")).toEqual([]);
  });
});

describe("V2: money", () => {
  test("US$ with two decimals, four below one cent, a dash when absent (English)", () => {
    setLocale("en");
    expect(plain(usd(150))).toBe("US$ 150.00");
    expect(plain(usd("5"))).toBe("US$ 5.00");
    expect(plain(usd("0.0123"))).toBe("US$ 0.01");
    expect(plain(usd(0.0042))).toBe("US$ 0.0042");
    expect(plain(usd(0))).toBe("US$ 0.00");
    expect(usd(null)).toBe("—");
    expect(usd(undefined)).toBe("—");
    expect(usd("")).toBe("—");
    expect(usd("not a number")).toBe("—");
  });

  test("Spanish separators, and the space after US$ never breaks the line", () => {
    setLocale("es");
    expect(plain(usd(150))).toBe("US$ 150,00");
    expect(plain(usd(0.0099))).toBe("US$ 0,0099");
    expect(plain(usd("7.5"))).toBe("US$ 7,50");
    expect(usd(1).startsWith(`US$${NBSP}`)).toBe(true);
  });
});

describe("V2: the month bar and its alerts", () => {
  const alert = (threshold: number): AiBudgetAlert => ({
    month: "2026-10-01",
    threshold,
    at: "2026-10-05T19:02:00Z",
    spent_usd: (150 * threshold) / 100,
    budget_usd: 150,
  });

  test("the markers are 50 / 70 / 85 / 95 / 100 %, and those the spend reached are crossed", () => {
    expect([...BUDGET_THRESHOLDS]).toEqual([50, 70, 85, 95, 100]);
    const m = budgetMarkers(0.86, []);
    expect(m.map((x) => x.threshold)).toEqual([50, 70, 85, 95, 100]);
    expect(m.map((x) => x.crossed)).toEqual([true, true, true, false, false]);
    expect(budgetMarkers(0.7, []).map((x) => x.crossed)).toEqual([true, true, false, false, false]);
    expect(budgetMarkers(1.2, []).every((x) => x.crossed)).toBe(true);
    expect(budgetMarkers(null, []).some((x) => x.crossed)).toBe(false);
  });

  test("an alert recorded this month is attached to its marker (and marks it even without a ratio)", () => {
    const m = budgetMarkers(null, [alert(70), alert(85)]);
    expect(m.map((x) => x.crossed)).toEqual([false, true, true, false, false]);
    expect(m[1]?.alert?.spent_usd).toBe(105);
    expect(m[3]?.alert).toBeNull();
  });

  test("thresholds are de-duplicated and sorted", () => {
    expect(budgetMarkers(0.5, [], [100, 70, 70, 85]).map((x) => x.threshold)).toEqual([
      70, 85, 100,
    ]);
  });

  test("ratios and bar widths", () => {
    expect(ratioOf("37.5", "150")).toBe(0.25);
    expect(ratioOf(10, 0)).toBeNull();
    expect(ratioOf(null, 150)).toBeNull();
    expect(barPercent(0.256)).toBe(25.6);
    expect(barPercent(1.4)).toBe(100);
    expect(barPercent(-1)).toBe(0);
    expect(barPercent(null)).toBe(0);
  });

  test("a threshold reads like a percentage in each language", () => {
    setLocale("es");
    expect(plain(thresholdText(70))).toBe("70 %");
    setLocale("en");
    expect(thresholdText(100)).toBe("100%");
  });

  test("tones: budget state, projection against the budget, the shadow gate", () => {
    expect(budgetTone("NORMAL")).toBe("positive");
    expect(budgetTone("REDUCED")).toBe("warning");
    expect(budgetTone("CHEAP_ONLY")).toBe("warning");
    expect(budgetTone("EXHAUSTED")).toBe("negative");
    expect(budgetTone("SOMETHING_NEW")).toBe("neutral");
    expect(projectionTone(0.5)).toBe("positive");
    expect(projectionTone(0.9)).toBe("warning");
    expect(projectionTone(1.1)).toBe("negative");
    expect(projectionTone(null)).toBe("neutral");
    expect(gateTone("pass")).toBe("positive");
    expect(gateTone("fail")).toBe("negative");
    expect(gateTone("insufficient")).toBe("neutral");
    expect(gateTone(null)).toBe("neutral");
  });
});

describe("V2: labels of loss classes, verdicts, reasons, passes and questions", () => {
  test("loss classes in the owner's words", () => {
    setLocale("es");
    expect(lossClassLabel("MODEL_ERROR")).toBe("Error del modelo");
    expect(lossClassLabel("CONTEXT_ERROR")).toBe("Error de contexto");
    expect(lossClassLabel("DATA_ERROR")).toBe("Error de datos");
    expect(lossClassLabel("MARKET_ERROR")).toBe("El mercado sabía algo");
    expect(lossClassLabel("EXECUTION_ERROR")).toBe("Error de ejecución");
    expect(lossClassLabel("NORMAL_VARIANCE")).toBe("Varianza normal");
    expect(lossClassLabel("UNKNOWN")).toBe("Sin datos para juzgar");
    setLocale("en");
    expect(lossClassLabel("MARKET_ERROR")).toBe("The market knew something");
    expect(classTone("MODEL_ERROR")).toBe("negative");
    expect(classTone("NORMAL_VARIANCE")).toBe("neutral");
    expect(classTone(null)).toBe("neutral");
  });

  test("post-mortem verdicts: green when the AI was right, red when it was wrong", () => {
    setLocale("es");
    expect(verdictLabel("approved_won")).toBe("Aprobada que ganó");
    expect(verdictLabel("approved_lost")).toBe("Aprobada que perdió");
    expect(verdictLabel("rejected_would_have_won")).toBe("Rechazada que habría ganado");
    expect(verdictLabel("rejected_correctly")).toBe("Rechazada con acierto");
    expect(verdictTone("approved_won")).toBe("positive");
    expect(verdictTone("rejected_correctly")).toBe("positive");
    expect(verdictTone("approved_lost")).toBe("negative");
    expect(verdictTone("rejected_would_have_won")).toBe("negative");
    expect(verdictTone("push")).toBe("neutral");
  });

  test("escalation reasons and passes", () => {
    setLocale("es");
    expect(reasonLabel("model_market_gap")).toBe("Brecha modelo-mercado");
    expect(reasonLabel("contradiction")).toBe("Fuentes contradictorias");
    expect(passLabel("first")).toBe("Primera (00:05)");
    expect(passLabel("pre")).toBe("Previa");
    expect(passLabel("final")).toBe("Final");
  });

  test("the ten questions, in Spanish, in their order", () => {
    setLocale("es");
    expect(QUESTIONS.map(questionLabel)).toEqual([
      "¿Qué esperaba PrediGol?",
      "¿Qué ocurrió?",
      "¿Falló el modelo?",
      "¿Falló la información?",
      "¿Había una señal ignorada?",
      "¿La cuota se movió?",
      "¿Existía una baja importante?",
      "¿La alineación cambió?",
      "¿La incertidumbre estaba subestimada?",
      "¿Fue simplemente varianza?",
    ]);
  });

  test("every known value has a label in both languages; an unknown one is shown as it came, never as a key", () => {
    const groups: Array<[string, readonly string[]]> = [
      ["ai.v2.class", LOSS_CLASSES],
      ["ai.v2.verdict", POSTMORTEM_VERDICTS],
      ["ai.v2.reason", ESCALATION_REASONS],
      ["ai.v2.pass", PASSES],
      ["ai.v2.question", QUESTIONS],
    ];
    for (const [prefix, values] of groups) {
      for (const v of values) {
        expect(hasKey(`${prefix}.${v}`, "es")).toBe(true);
        expect(hasKey(`${prefix}.${v}`, "en")).toBe(true);
      }
    }
    setLocale("es");
    expect(lossClassLabel("BRAND_NEW")).toBe("BRAND_NEW");
    expect(verdictLabel("brand_new")).toBe("brand new");
    expect(reasonLabel("brand_new")).toBe("brand new");
    expect(passLabel("brand_new")).toBe("brand_new");
  });
});

describe("V2: the answers of a post-mortem", () => {
  test("the server's Spanish answers are recognised, accents and case aside", () => {
    expect(answerKind("sí")).toBe("yes");
    expect(answerKind("Sí")).toBe("yes");
    expect(answerKind("si")).toBe("yes");
    expect(answerKind("no")).toBe("no");
    expect(answerKind("sin datos")).toBe("unknown");
    expect(answerKind("en contra")).toBe("against");
    expect(answerKind("a favor")).toBe("favour");
    expect(answerKind("estable")).toBe("stable");
    expect(answerKind("no aplica")).toBe("na");
    expect(answerKind("")).toBe("unknown");
    expect(answerKind(null)).toBe("unknown");
    expect(answerKind("Millonarios - Santa Fe · 1X2 Home")).toBe("text");
  });

  test("a 'sí' asks for a look; to 'was it variance?' it only informs; a price against is red", () => {
    expect(answerTone("model", "yes")).toBe("warning");
    expect(answerTone("variance", "yes")).toBe("info");
    expect(answerTone("odds_moved", "against")).toBe("negative");
    expect(answerTone("odds_moved", "favour")).toBe("positive");
    expect(answerTone("model", "no")).toBe("neutral");
  });

  test("expected is plain text, happened is the settlement, the rest are chips", () => {
    setLocale("es");
    expect(answerView("expected", "A - B · 1X2 Home")).toEqual({
      label: "A - B · 1X2 Home",
      tone: "neutral",
      chip: false,
    });
    expect(answerView("happened", "loss")).toEqual({
      label: "Perdió",
      tone: "negative",
      chip: true,
    });
    expect(answerView("model", "sí")).toEqual({ label: "Sí", tone: "warning", chip: true });
    expect(answerView("odds_moved", "en contra")).toEqual({
      label: "En contra",
      tone: "negative",
      chip: true,
    });
    expect(settledLabel("half_win")).toBe("Medio ganada");
  });

  test("answers come in the questions' order, then any other", () => {
    const a = (answer: string) => ({ answer, detail: "", data: {} });
    const got = orderedAnswers({
      variance: a("no"),
      extra: a("x"),
      expected: a("e"),
      model: a("sí"),
    });
    expect(got.map(([q]) => q)).toEqual(["expected", "model", "variance", "extra"]);
    expect(orderedAnswers(null)).toEqual([]);
  });
});

describe("V2: selections, edges and small formats", () => {
  test("the model's edge in percentage points, from the edge or from the two probabilities", () => {
    expect(edgePoints(0.0324, null, null)).toBe(3.2);
    expect(edgePoints(null, 0.55, 0.5)).toBe(5);
    expect(edgePoints("-0.015", null, null)).toBe(-1.5);
    expect(edgePoints(null, null, 0.5)).toBeNull();
    setLocale("es");
    expect(pointsText(3.2)).toBe("+3,2 pp");
    expect(pointsText(-1.5)).toBe("−1,5 pp");
    expect(pointsText(null)).toBe("—");
  });

  test("a selection in the reader's words, with the teams of the match", () => {
    expect(teamsOf("Millonarios - Santa Fe")).toEqual({ home: "Millonarios", away: "Santa Fe" });
    expect(teamsOf("No separator")).toBeNull();
    setLocale("es");
    expect(selectionText("1X2", "Home", "0", "Millonarios - Santa Fe")).toBe(
      "1X2 · Gana Millonarios",
    );
    expect(plain(selectionText("OU", "Over", "2.5"))).toBe("Goles · Más de 2,5 goles");
  });

  test("ages and days", () => {
    expect(minutesText(45)).toBe("45 min");
    expect(minutesText(900)).toBe("15 h");
    expect(minutesText(4 * 1440)).toBe("4 d");
    expect(minutesText(null)).toBe("—");
    setLocale("es");
    expect(dayLabel("2026-10-08")).toBe("jueves, 8 de octubre");
    expect(dayLabel("not a day")).toBe("not a day");
  });

  test("costs by level in the stack's order, a level reported twice added up", () => {
    const rows = levelRows([
      { key: "web", tier: "search", requests: 4, cost_usd: 0.02 },
      { key: "L3", tier: "final", requests: 1, cost_usd: 0.3 },
      { key: "other", tier: "x", requests: 1, cost_usd: 0.01 },
      { key: "L1", tier: "bulk", requests: 10, cost_usd: 0.05 },
      { key: "L1", tier: "bulk", requests: 2, cost_usd: 0.01 },
    ]);
    expect(rows.map((r) => r.key)).toEqual(["L1", "L3", "web", "other"]);
    expect(rows[0]?.requests).toBe(12);
    expect(rows[0]?.cost_usd).toBeCloseTo(0.06, 10);
    expect(levelRows(undefined)).toEqual([]);
  });
});

describe("V2: evidence, compact", () => {
  test("numbers, lists as their size, small maps by their labels; omitted keys and the version left out", () => {
    setLocale("es");
    const got = evidenceSummary(
      {
        n_matches: 40,
        impact: "hasta 12 de 40 pérdidas",
        z: 2.31,
        memory_ids: [1, 2, 3],
        verdicts: { approved_won: 2, approved_lost: 1 },
        pattern_version: "patterns-v1",
        deep: { a: { b: 1 } },
        nothing: null,
      },
      { omit: ["impact"] },
    );
    expect(got).toEqual([
      { key: "n_matches", label: "Partidos", value: "40" },
      { key: "z", label: "z", value: "2,31" },
      { key: "memory_ids", label: "Memoria", value: "3 elementos" },
      {
        key: "verdicts",
        label: "Veredictos",
        value: "Aprobada que ganó 2 · Aprobada que perdió 1",
      },
    ]);
  });

  test("a loss class or a source level is said by its label; an unknown code as it came", () => {
    setLocale("es");
    const got = evidenceSummary({
      class: "MARKET_ERROR",
      tier: "social",
      signal: "market_against",
    });
    expect(got.map((i) => i.value)).toEqual([
      "El mercado sabía algo",
      "Red social",
      "market_against",
    ]);
    expect(evidenceSummary({ class: "BRAND_NEW" })[0]?.value).toBe("BRAND_NEW");
  });

  test("at most `max` items", () => {
    expect(evidenceSummary({ a: 1, b: 2, c: 3 }, { max: 2 }).map((i) => i.key)).toEqual(["a", "b"]);
    expect(evidenceSummary(null)).toEqual([]);
  });

  test("the comparison's sample as counts", () => {
    expect(sampleCounts({ selections: 120, days: "14", rejected: null, other: 3 })).toEqual({
      selections: 120,
      days: 14,
      rejected: null,
    });
    expect(sampleCounts(undefined)).toEqual({ selections: null, days: null, rejected: null });
  });
});
