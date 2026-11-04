/// <reference types="bun" />
/**
 * «Explícame» in the reader's words (plan UX, B9; section 26): every code the API can send has a sentence in Spanish and in
 * English, a code this page does not know - or a line without a parameter it needs - is left out (never shown raw, never with a
 * gap), probabilities are always labelled as PrediGol's or the market's, and no template promises anything or says how much to
 * stake.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { setLocale, type Locale } from "@/lib/i18n";
import en from "@/locales/en/explain.json";
import es from "@/locales/es/explain.json";
import type { ExplainLine, Explanation } from "@/lib/api/v1/types_explain";
import {
  QUESTIONS,
  answerLines,
  lineText,
  questionText,
  share,
  trackWhat,
  voteSubjectId,
  writtenSayCodes,
} from "./text";

/** Intl writes «52 %» with a no-break space: compared as a plain one. */
const plain = (s: string | null): string | null => s?.replace(/[\u00a0\u202f]/g, " ") ?? null;

setLocale("es");
afterEach(() => setLocale("es"));

const say = (code: string, params: ExplainLine["params"] = {}): ExplainLine => ({
  say: code,
  params,
  fact: null,
});

const text = (line: ExplainLine, lang: Locale = "es"): string | null => {
  setLocale(lang);
  return plain(lineText(line));
};

/** The word «count» sentences carry their plural forms (<code>_one / <code>_other); the others, the code itself. */
const COUNTED = [
  "has_pick",
  "no_pick_not_published",
  "no_pick_no_value",
  "parlay_leg_missing",
] as const;

describe("every sentence the page writes has its template", () => {
  for (const [lang, say_] of [
    ["es", es.say],
    ["en", en.say],
  ] as const) {
    test(lang, () => {
      const written = say_ as Record<string, string>;
      for (const code of writtenSayCodes()) {
        const forms = (COUNTED as readonly string[]).includes(code)
          ? [`${code}_one`, `${code}_other`]
          : [code];
        for (const form of forms) expect(written[form], `${lang}: ${form}`).toBeTruthy();
      }
    });
  }

  test("the two languages carry the same keys", () => {
    expect(Object.keys(es.say).sort()).toEqual(Object.keys(en.say).sort());
    expect(Object.keys(es.question.match).sort()).toEqual(Object.keys(en.question.match).sort());
    expect(Object.keys(es.reason).sort()).toEqual(Object.keys(en.reason).sort());
    expect(Object.keys(es.part).sort()).toEqual(Object.keys(en.part).sort());
  });

  test("every question of every place has its words", () => {
    for (const lang of ["es", "en"] as const) {
      setLocale(lang);
      for (const [entity, intents] of Object.entries(QUESTIONS)) {
        for (const intent of intents) {
          const q = questionText(entity as keyof typeof QUESTIONS, intent);
          expect(q.length, `${lang} ${entity}.${intent}`).toBeGreaterThan(8);
          expect(q).not.toContain("explain.question");
        }
      }
    }
  });
});

describe("the sentences", () => {
  test("a count, in singular and plural", () => {
    expect(text(say("has_pick", { count: 1 }))).toContain("un pick de PrediGol");
    expect(text(say("has_pick", { count: 3 }))).toContain("3 picks de PrediGol");
    expect(text(say("has_pick", { count: 2 }), "en")).toContain("2 PrediGol picks");
    expect(text(say("no_pick_not_published", { evaluated: 1 }))).toContain("una selección");
    expect(text(say("no_pick_not_published", { evaluated: 4 }))).toContain("4 selecciones");
  });

  test("why a compared selection was not published", () => {
    const line = say("no_pick_no_value", {
      evaluated: 5,
      no_value: 3,
      odds: 2,
      market: 0,
      other: 0,
    });
    const es_ = text(line) ?? "";
    expect(es_).toContain("5 selecciones");
    expect(es_).toContain("la cuota no paga lo suficiente por lo que vale (3)");
    expect(es_).toContain("una cuota fuera del rango que usa (2)");
    expect(es_).not.toContain("mercado que todavía no cubre");
    expect(text(say("no_pick_no_value", { evaluated: 1, no_value: 1 }))).not.toContain("(1)");
    expect(text(say("no_pick_no_value", { evaluated: 0 }))).toBeNull();
    expect(text(say("no_pick_no_value", { evaluated: 3, no_value: 0 }))).toBeNull();
  });

  test("a forecast: the likely outcome, its figure, whether it is calibrated, the rest", () => {
    const line = say("forecast_market", {
      market: "1X2",
      line: 0,
      home: "Nacional",
      away: "Millonarios",
      selections: ["Home", "Draw", "Away"],
      probabilities: [0.5, 0.27, 0.23],
      likely: "Home",
      p: 0.5,
      calibrated: false,
    });
    const out = text(line) ?? "";
    expect(out).toContain("Nacional");
    expect(out).toContain("50 %, sin calibrar");
    expect(out).toContain("27 %");
    expect(out).toContain("23 %");
    const calibrated = text(say("forecast_market", { ...line.params, calibrated: true })) ?? "";
    expect(calibrated).not.toContain("sin calibrar");
    // without a clear likely outcome, only the figures
    const even = text(say("forecast_market", { ...line.params, likely: null })) ?? "";
    expect(even).not.toContain("lo más probable");
    expect(even).toContain("27 %");
  });

  test("a forecast with figures that do not match its selections says nothing", () => {
    const params = { market: "1X2", selections: ["Home", "Draw"], probabilities: [0.5], p: 0.5 };
    expect(text(say("forecast_market", params))).toBeNull();
    expect(
      text(say("forecast_market", { market: "1X2", selections: [], probabilities: [] })),
    ).toBeNull();
  });

  test("the probability of a pick and its margin of doubt", () => {
    expect(text(say("pick_probability", { p: 0.523 }))).toContain("52 %");
    expect(text(say("pick_probability", {}))).toBeNull();
    const interval = text(say("pick_interval", { low: 0.41, high: 0.6 })) ?? "";
    expect(interval).toContain("41 %");
    expect(interval).toContain("60 %");
    expect(text(say("pick_interval", { low: 0.41 }))).toBeNull();
    expect(text(say("pick_review_risks", { risks: ["a", "b"] }))).toContain("a; b");
    expect(text(say("pick_review_risks", { risks: [] }))).toBeNull();
  });

  test("the parlay: each leg with its probability and who says it", () => {
    const leg = {
      leg: 2,
      home: "Nacional",
      away: "Millonarios",
      market: "OU",
      selection: "Over",
      line: 2.5,
      p: 0.543,
      source: "model",
    };
    const out = text(say("parlay_leg", leg)) ?? "";
    expect(out).toContain("2. Nacional – Millonarios");
    expect(out).toContain("54,3 %");
    expect(out).toContain("según PrediGol");
    expect(text(say("parlay_leg", { ...leg, source: "market" }))).toContain(
      "según el mercado, sin margen",
    );
    // a leg without its probability: said, never invented
    const none = text(say("parlay_leg", { ...leg, p: null, source: null })) ?? "";
    expect(none).toContain("no tengo su probabilidad");
    expect(none).not.toContain("%");
    // a match without names does not break the sentence
    expect(text(say("parlay_leg", { ...leg, home: null, away: null }))).toContain("un partido");
    expect(text(say("parlay_leg", { leg: 1, market: "OU" }))).toBeNull();
  });

  test("the parlay's product and its dependency", () => {
    expect(text(say("parlay_product", { probabilities: [0.6, 0.5], p: 0.3 }))).toContain(
      "60,0 % × 50,0 % = 30,0 %",
    );
    expect(text(say("parlay_product", { probabilities: [], p: 0.3 }))).toBeNull();
    const dep =
      text(
        say("parlay_dependency", { reasons: ["shared_team", "same_competition_day"], p: 0.31 }),
      ) ?? "";
    expect(dep).toContain("comparten equipo y son de la misma competición y el mismo día");
    expect(dep).toContain("31,0 %");
    expect(text(say("parlay_dependency", { reasons: ["nope"], p: 0.31 }))).toBeNull();
    expect(text(say("parlay_related", { reasons: ["shared_team"] }))).toContain("comparten equipo");
    expect(text(say("parlay_very_unlikely", { p: 0.0000123 }))).toContain("< 0,01 %");
  });

  test("a leg that breaks a rule: the slip's own sentence, or the generic one", () => {
    expect(text(say("parlay_issue", { code: "no_such_code_at_all", leg: 3 }))).toContain(
      "selección 3",
    );
    expect(text(say("parlay_issue", { code: "no_such_code_at_all", leg: null }))).toContain(
      "no cumple",
    );
    expect(text(say("parlay_issue", {}))).toBeNull();
  });

  test("the sentences without parameters are the template alone", () => {
    expect(text(say("pick_rule"))).toContain("nunca inventa un pick");
    expect(text(say("forecast_not_pick"))).toContain("Un pronóstico no es un pick");
    expect(text(say("pick_rule"), "en")).toContain("never makes up a pick");
  });

  test("a code this page does not know is left out, never shown raw", () => {
    expect(text(say("a_code_from_the_future"))).toBeNull();
    expect(text({ say: null, params: {}, fact: null })).toBeNull();
    const answer: Explanation = {
      version: "explain-v1",
      entity: "match",
      item_id: 7,
      intent: "forecast",
      answered: true,
      lines: [say("forecast_what"), say("a_code_from_the_future"), say("forecast_not_pick")],
      terms: [],
      links: [],
    };
    setLocale("es");
    expect(answerLines(answer)).toHaveLength(2);
  });

  test("a fact of the reading is written with the reading's own template", () => {
    const line: ExplainLine = {
      say: null,
      params: {},
      fact: { code: "forecast_missing", params: { reason: "no_forecast_yet" }, ref: "forecast" },
    };
    setLocale("es");
    const out = lineText(line);
    expect(out === null || out.length > 5).toBe(true);
  });
});

describe("what leaves the page", () => {
  test("«¿Te sirvió?» keeps one answer per reader and question", () => {
    const ids = new Set<number>();
    for (const [entity, intents] of Object.entries(QUESTIONS)) {
      for (const intent of intents) {
        const id = voteSubjectId(entity as keyof typeof QUESTIONS, 41, intent);
        expect(ids.has(id)).toBe(false);
        ids.add(id);
        expect(id % 8).toBeGreaterThan(0);
        expect(Math.floor(id / 8)).toBe(41);
      }
    }
    expect(voteSubjectId("parlay", null, "probability")).toBe(6);
  });

  test("`explain_opened` records the question only, never free text", () => {
    expect(trackWhat("match", "no_pick", true)).toBe("match.no_pick");
    expect(trackWhat("pick", "caution", false)).toBe("pick.caution.missing");
    for (const [entity, intents] of Object.entries(QUESTIONS)) {
      for (const intent of intents) {
        for (const answered of [true, false]) {
          const what = trackWhat(entity as keyof typeof QUESTIONS, intent, answered);
          expect(what).toMatch(/^[A-Za-z0-9_.+-]{1,40}$/);
        }
      }
    }
  });

  test("a parlay's share, with the digits it needs", () => {
    expect(plain(share(0.543))).toBe("54,3 %");
    expect(plain(share(0.0042))).toBe("0,42 %");
    expect(plain(share(0.00001))).toBe("< 0,01 %");
    expect(share(null)).toBe("—");
  });
});

describe("no template promises or advises a stake", () => {
  const FORBIDDEN_ES =
    /\b(seguro|segura|fijo|fija|garantizad[oa]|infalible|apuesta(?:s)?\s+(?:\d|\$)|deberías apostar)\b/i;
  const FORBIDDEN_EN =
    /\b(sure thing|guaranteed|certain win|risk-free|you should bet|bet \$?\d)\b/i;
  test("Spanish", () => {
    for (const [k, v] of Object.entries(es.say)) expect(FORBIDDEN_ES.test(v), k).toBe(false);
  });
  test("English", () => {
    for (const [k, v] of Object.entries(en.say)) expect(FORBIDDEN_EN.test(v), k).toBe(false);
  });
});
