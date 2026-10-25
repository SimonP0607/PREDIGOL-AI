/// <reference types="bun" />
/**
 * PLAN F10.17 and F11.11, the words of the families in shadow: a market key read by its parts and named in both languages (every key the
 * families state, and the shapes they could grow into), the selections with their lines and the teams of the match, the rule that grades each
 * family, the cycle's steps and the tones. The catalog is held complete: no word the tab can ask for is missing in either language.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { hasKey, setLocale, translate } from "@/lib/i18n";
import type { FamiliesRule } from "@/lib/api/v1/types_families";
import {
  FAMILY_CODES,
  STEPS,
  familyName,
  isFamilyMarket,
  marketText,
  measureOf,
  modeHelp,
  modeName,
  modeTone,
  msText,
  pickText,
  reasonName,
  reasonsShown,
  resultName,
  resultTone,
  ruleNote,
  ruleText,
  shapeOf,
  stateName,
  stateTone,
  statusName,
  stepFacts,
  stepName,
  stepTone,
  verdictHint,
  verdictName,
  verdictTone,
} from "./familiesText";

afterEach(() => setLocale("es"));

/** Every market key the four families state (read from the forecasts the backend builds for them: tests/unit/test_api_families.py). */
const FAMILY_KEYS: Record<(typeof FAMILY_CODES)[number], string[]> = {
  GOALS_HALF: [
    "OU_1H",
    "OU_HOME_1H",
    "OU_AWAY_1H",
    "1X2_1H",
    "DNB_1H",
    "DC_1H",
    "BTTS_1H",
    "OU_2H",
    "OU_HOME_2H",
    "OU_AWAY_2H",
    "1X2_2H",
    "DNB_2H",
    "DC_2H",
    "BTTS_2H",
    "HTFT",
    "HSH",
    "HSH_HOME",
    "HSH_AWAY",
  ],
  CORNERS: ["CORNERS_OU", "CORNERS_OU_HOME", "CORNERS_OU_AWAY", "CORNERS_1X2", "CORNERS_DC"],
  CARDS: ["CARDS_OU", "CARDS_OU_HOME", "CARDS_OU_AWAY"],
  YELLOW: ["YELLOW_OU", "YELLOW_OU_HOME", "YELLOW_OU_AWAY", "YELLOW_1X2", "YELLOW_DC"],
};

const MEASURE_OF_FAMILY: Record<string, string[]> = {
  GOALS_HALF: ["goals_1h", "goals_2h", "goals_halves"],
  CORNERS: ["corners_ft"],
  CARDS: ["cards_lines_ft"],
  YELLOW: ["yellow_ft"],
};

const LOCALES = ["es", "en"] as const;

function rule(measure: string, extra: Partial<FamiliesRule> = {}): FamiliesRule {
  return {
    key: `${measure}@v1`,
    measure,
    version: 1,
    period: "FT",
    convention: "the registry's own words",
    columns: [],
    liquidable: true,
    note: "",
    ...extra,
  };
}

describe("which measure grades a key", () => {
  test("every key of every family is graded on a measure of that family", () => {
    for (const code of FAMILY_CODES) {
      for (const key of FAMILY_KEYS[code]) {
        expect(MEASURE_OF_FAMILY[code]).toContain(measureOf(key) as string);
        expect(isFamilyMarket(key)).toBe(true);
      }
    }
  });

  test("the prefixes and the halves decide the measure, the rest of the shape does not", () => {
    for (const kind of ["OU", "1X2", "DC", "DNB", "BTTS", "AH", "OE"]) {
      for (const side of ["", "_HOME", "_AWAY"]) {
        expect(measureOf(`CORNERS_${kind}${side}`)).toBe("corners_ft");
        expect(measureOf(`CARDS_${kind}${side}`)).toBe("cards_lines_ft");
        expect(measureOf(`YELLOW_${kind}${side}`)).toBe("yellow_ft");
        expect(measureOf(`${kind}${side}_1H`)).toBe("goals_1h");
        expect(measureOf(`${kind}${side}_2H`)).toBe("goals_2h");
        expect(measureOf(`${kind}${side}`)).toBeNull();
      }
    }
    for (const key of ["HTFT", "HSH", "HSH_HOME", "HSH_AWAY"]) {
      expect(measureOf(key)).toBe("goals_halves");
    }
  });

  test("a market no family bets on has no measure", () => {
    for (const key of ["1X2", "OU", "BTTS", "AH", "DC", "FOO_BAR", "", "HTFT_X"]) {
      expect(isFamilyMarket(key)).toBe(false);
    }
  });
});

describe("a key read by its parts", () => {
  test("what is counted, the kind, the side and the half", () => {
    expect(shapeOf("CORNERS_OU_HOME")).toEqual({
      count: "corners",
      kind: "OU",
      subject: "home",
      half: "",
    });
    expect(shapeOf("OU_AWAY_2H")).toEqual({
      count: "goals",
      kind: "OU",
      subject: "away",
      half: "2H",
    });
    expect(shapeOf("YELLOW_DC")).toEqual({ count: "yellow", kind: "DC", subject: "", half: "" });
    expect(shapeOf("CARDS_OU")).toEqual({ count: "cards", kind: "OU", subject: "", half: "" });
    expect(shapeOf("BTTS_1H")).toEqual({ count: "goals", kind: "BTTS", subject: "", half: "1H" });
  });

  test("a key it cannot read is not read", () => {
    for (const key of ["FOO", "CORNERS_", "CORNERS_FOO", "OU_HOME_X", "HTFT", "HSH", ""]) {
      expect(shapeOf(key)).toBeNull();
    }
  });
});

describe("the market in words", () => {
  test("Spanish", () => {
    setLocale("es");
    expect(marketText("CORNERS_OU")).toBe("Córners · más/menos");
    expect(marketText("CORNERS_OU_HOME")).toBe("Córners del local · más/menos");
    expect(marketText("CARDS_OU_AWAY")).toBe("Tarjetas del visitante · más/menos");
    expect(marketText("YELLOW_DC")).toBe("Amarillas · doble oportunidad");
    expect(marketText("OU_1H")).toBe("Goles · más/menos · 1.ª parte");
    expect(marketText("OU_HOME_2H")).toBe("Goles del local · más/menos · 2.ª parte");
    expect(marketText("1X2_1H")).toBe("1X2 · 1.ª parte");
    expect(marketText("BTTS_2H")).toBe("Ambos marcan · 2.ª parte");
    expect(marketText("HTFT")).toBe("Descanso/final");
    expect(marketText("HSH_AWAY")).toBe("Mitad con más goles del visitante");
  });

  test("English", () => {
    setLocale("en");
    expect(marketText("CORNERS_OU")).toBe("Corners · over/under");
    expect(marketText("CORNERS_OU_AWAY")).toBe("Away corners · over/under");
    expect(marketText("YELLOW_1X2")).toBe("Yellow cards · 1X2");
    expect(marketText("OU_2H")).toBe("Goals · over/under · 2nd half");
    expect(marketText("DNB_1H")).toBe("Draw no bet · 1st half");
    expect(marketText("HSH")).toBe("Highest scoring half");
  });

  test("no key of any family is shown as its key, in either language, and none is shown twice", () => {
    for (const locale of LOCALES) {
      setLocale(locale);
      const names = FAMILY_CODES.flatMap((code) => FAMILY_KEYS[code]).map((key) => {
        const text = marketText(key);
        expect(text).not.toBe(key);
        expect(text).not.toMatch(/_|families\./);
        return text;
      });
      expect(new Set(names).size).toBe(names.length);
    }
  });

  test("a key it cannot read is shown as it came, never guessed", () => {
    expect(marketText("FOO_BAR")).toBe("FOO_BAR");
    expect(marketText("CORNERS_FOO")).toBe("CORNERS_FOO");
  });

  test("the extra kinds the catalogue could add are named too", () => {
    setLocale("es");
    expect(marketText("CORNERS_AH")).toBe("Córners · hándicap");
    expect(marketText("CARDS_OE")).toBe("Tarjetas · par/impar");
    setLocale("en");
    expect(marketText("CORNERS_AH")).toBe("Corners · handicap");
  });
});

describe("the selection in words", () => {
  const teams = { home: "Barcelona", away: "Real Madrid" };

  test("over and under keep their line", () => {
    setLocale("es");
    expect(pickText("CORNERS_OU", "Over", 9.5)).toBe("Más de 9,5");
    expect(pickText("CORNERS_OU", "Under", "9.5")).toBe("Menos de 9,5");
    expect(pickText("OU_HOME_1H", "Over", 0.5, teams)).toBe("Más de 0,5");
    expect(pickText("CARDS_OU", "Over", null)).toBe("Más");
    setLocale("en");
    expect(pickText("CORNERS_OU", "Over", 9.5)).toBe("Over 9.5");
    expect(pickText("YELLOW_OU", "Under", 3.5)).toBe("Under 3.5");
    expect(pickText("YELLOW_OU", "Under", null)).toBe("Under");
  });

  test("the sides are the teams when the match is known, else home and away", () => {
    setLocale("es");
    expect(pickText("CORNERS_1X2", "Home", 0, teams)).toBe("Barcelona");
    expect(pickText("CORNERS_1X2", "Away", 0, teams)).toBe("Real Madrid");
    expect(pickText("CORNERS_1X2", "Draw", 0, teams)).toBe("Empate");
    expect(pickText("CORNERS_1X2", "Home", 0)).toBe("Local");
    expect(pickText("1X2_1H", "Away", 0, { home: null, away: undefined })).toBe("Visitante");
    expect(pickText("DNB_2H", "Home", 0, teams)).toBe("Barcelona");
    setLocale("en");
    expect(pickText("CORNERS_1X2", "Home", 0)).toBe("Home");
    expect(pickText("CORNERS_1X2", "Away", 0, teams)).toBe("Real Madrid");
  });

  test("the double chance names the two outcomes it covers", () => {
    setLocale("es");
    expect(pickText("CORNERS_DC", "1X", 0, teams)).toBe("Barcelona o empate");
    expect(pickText("CORNERS_DC", "12", 0, teams)).toBe("Barcelona o Real Madrid");
    expect(pickText("DC_2H", "X2", 0, teams)).toBe("Empate o Real Madrid");
    expect(pickText("DC_1H", "1X", 0)).toBe("Local o empate");
    setLocale("en");
    expect(pickText("YELLOW_DC", "12", 0)).toBe("Home or Away");
  });

  test("yes and no, odd and even, the handicap with its sign", () => {
    setLocale("es");
    expect(pickText("BTTS_1H", "Yes", 0)).toBe("Sí");
    expect(pickText("BTTS_2H", "No", 0)).toBe("No");
    expect(pickText("CORNERS_OE", "Odd", 0)).toBe("Impar");
    expect(pickText("CORNERS_OE", "Even", 0)).toBe("Par");
    expect(pickText("CORNERS_AH", "Home", -0.5, teams)).toBe("Barcelona -0,5");
    expect(pickText("CORNERS_AH", "Away", 1.5, teams)).toBe("Real Madrid +1,5");
    expect(pickText("CORNERS_AH", "Home", null, teams)).toBe("Barcelona");
  });

  test("half-time/full-time and the highest scoring half", () => {
    setLocale("es");
    expect(pickText("HTFT", "Home/Draw", 0, teams)).toBe("Barcelona / Empate");
    expect(pickText("HTFT", "Away/Away", 0)).toBe("Visitante / Visitante");
    expect(pickText("HSH", "1st Half", 0)).toBe("1.ª parte");
    expect(pickText("HSH_HOME", "2nd Half", 0)).toBe("2.ª parte");
    expect(pickText("HSH_AWAY", "Draw", 0)).toBe("Igual en las dos");
    setLocale("en");
    expect(pickText("HSH", "Draw", 0)).toBe("Same in both");
    expect(pickText("HTFT", "Draw/Home", 0, teams)).toBe("Draw / Barcelona");
  });

  test("a selection it does not know comes back as it came, with its line", () => {
    setLocale("es");
    expect(pickText("CARDS_OU", "Weird", 4.5)).toBe("Weird 4,5");
    expect(pickText("CARDS_OU", "Weird", null)).toBe("Weird");
    expect(pickText("HTFT", "Home/Sideways", 0)).toBe("Home/Sideways");
    expect(pickText("HSH", "Other", 0)).toBe("Other");
    expect(pickText("FOO_BAR", "Bar", 1)).toBe("Bar 1");
    expect(pickText("CORNERS_DC", "ZZ", 0)).toBe("ZZ 0");
  });

  test("the case of the stored selection does not matter", () => {
    setLocale("es");
    expect(pickText("CORNERS_OU", "OVER", 8.5)).toBe("Más de 8,5");
    expect(pickText("CORNERS_1X2", " home ", 0)).toBe("Local");
  });
});

describe("how a bet is graded", () => {
  test("the six rules of the registry have their words in both languages", () => {
    for (const measure of Object.values(MEASURE_OF_FAMILY).flat()) {
      for (const locale of LOCALES) {
        expect(hasKey(`families.rule.${measure}`, locale)).toBe(true);
      }
      const spanish = translate(`families.rule.${measure}`, undefined, "es");
      const english = translate(`families.rule.${measure}`, undefined, "en");
      expect(spanish).not.toBe(english);
    }
  });

  test("a rule is said in the reader's language, and a rule the catalog does not know says what the registry says", () => {
    setLocale("es");
    expect(ruleText(rule("corners_ft"))).toContain("Córners del partido");
    expect(ruleText(rule("yellow_ft"))).toContain("Solo tarjetas amarillas");
    setLocale("en");
    expect(ruleText(rule("yellow_ft"))).toContain("Yellow cards only");
    expect(ruleText(rule("offsides_ft", { convention: "offsides of the match" }))).toBe(
      "offsides of the match",
    );
  });

  test("the warning about the cards convention is kept; the registry's own note is said only for a rule the catalog does not know", () => {
    setLocale("es");
    expect(ruleNote(rule("cards_lines_ft", { note: "English words" }))).toContain("convención");
    expect(ruleNote(rule("corners_ft", { note: "an English note" }))).toBe("");
    expect(ruleNote(rule("goals_halves", { note: "HT/FT and the like read both halves." }))).toBe(
      "",
    );
    expect(ruleNote(rule("offsides_ft", { note: "only for the new rule" }))).toBe(
      "only for the new rule",
    );
    setLocale("en");
    expect(ruleNote(rule("cards_lines_ft"))).toContain("convention");
  });
});

describe("the names of the cycle", () => {
  test("the four families, the four steps, the statuses", () => {
    setLocale("es");
    expect(FAMILY_CODES.map(familyName)).toEqual([
      "Goles por mitad",
      "Córners",
      "Tarjetas",
      "Amarillas",
    ]);
    expect(STEPS.map(stepName)).toEqual(["Decidir", "Liquidar", "Post-mortem", "Recordar"]);
    expect(statusName("partial")).toBe("Parcial");
    expect(familyName("PENALTIES")).toBe("PENALTIES");
    setLocale("en");
    expect(FAMILY_CODES.map(familyName)).toEqual([
      "Goals by half",
      "Corners",
      "Cards",
      "Yellow cards",
    ]);
    expect(STEPS.map(stepName)).toEqual(["Decide", "Settle", "Post-mortem", "Remember"]);
    expect(statusName("mystery")).toBe("mystery");
  });

  test("the figures of a step are those it reported, as whole numbers, and only those", () => {
    setLocale("es");
    const decide = stepFacts("families", {
      mode: "shadow",
      forecasts: 12500,
      candidates: 4,
      written: 3,
      failed: 0,
      by_family: { CORNERS: 3 },
      errors: [],
    });
    expect(decide.map((f) => [f.key, f.label, f.value])).toEqual([
      ["forecasts", "Pronósticos", "12.500"],
      ["candidates", "Candidatas", "4"],
      ["written", "Escritas", "3"],
      ["failed", "Fallidas", "0"],
    ]);
    expect(stepFacts("family_outcomes", { open: 7, settled: 2 }).map((f) => f.key)).toEqual([
      "open",
      "settled",
    ]);
    expect(stepFacts("family_postmortems", {}).length).toBe(0);
    expect(stepFacts("family_memory", { postmortems: "12", entities: null })).toEqual([]);
    expect(stepFacts("someday", { open: 1 })).toEqual([]);
    setLocale("en");
    expect(stepFacts("families", { forecasts: 12500 })[0]?.value).toBe("12,500");
  });

  test("how long a step took", () => {
    setLocale("es");
    expect(msText(850)).toBe("850 ms");
    expect(msText(2400)).toBe("2,4 s");
    expect(msText(null)).toBe("");
    setLocale("en");
    expect(msText(2400)).toBe("2.4 s");
  });

  test("the mode of the cycle and what to say when it is not in shadow", () => {
    setLocale("es");
    expect(modeName("shadow")).toBe("En shadow");
    expect(modeName("off")).toBe("Apagado");
    expect(modeName(null)).toBe("Sin pasadas");
    expect(modeName("future")).toBe("future");
    expect(modeHelp("shadow")).toBeNull();
    expect(modeHelp("off")).toContain("FBI_FAMILY_DECISIONS");
    expect(modeHelp(null)).toContain("7 días");
    expect(modeTone("shadow")).toBe("info");
    expect(modeTone("off")).toBe("neutral");
    expect(modeTone(null)).toBe("neutral");
    setLocale("en");
    expect(modeName("off")).toBe("Off");
    expect(modeHelp(null)).toContain("7 days");
  });
});

describe("what became of a decision", () => {
  test("every result, verdict and quality the backend can write has its words in both languages", () => {
    const results = ["win", "loss", "push", "void", "half_win", "half_loss"];
    const verdicts = ["MERECIDO", "VARIANZA", "SUERTE", "ERROR", "NULO", "SIN_DATOS"];
    const qualities = ["GOOD", "NEUTRAL", "BAD", "UNKNOWN"];
    for (const locale of LOCALES) {
      for (const r of results) expect(hasKey(`families.result.${r}`, locale)).toBe(true);
      for (const v of verdicts) {
        expect(hasKey(`families.verdictHint.${v}`, locale)).toBe(true);
        expect(hasKey(`intel.codes.verdict.${v}`, locale)).toBe(true);
      }
      for (const q of qualities) expect(hasKey(`families.quality.${q}`, locale)).toBe(true);
    }
    setLocale("es");
    expect(resultName("half_win")).toBe("Media ganada");
    expect(verdictName("SUERTE")).toBe("Suerte");
    expect(verdictHint("ERROR")).toContain("peor que el cierre");
    expect(verdictHint("NOPE")).toBe("");
    setLocale("en");
    expect(resultName("loss")).toBe("Lost");
    expect(verdictName("MERECIDO")).toBe("Deserved");
  });

  test("the states a family reaches are named as the rest of the console names them", () => {
    setLocale("es");
    expect(stateName("INVESTIGACION")).toBe("Investigación");
    expect(stateName("RECHAZADO")).toBe("Rechazado");
    setLocale("en");
    expect(stateName("INVESTIGACION")).toBe("Investigation");
  });

  test("the reasons: every one the decision layer can give has words, and the baseline of every family is not repeated on each row", () => {
    const reasons = [
      "family_research",
      "family_shadow_only",
      "not_calibrated",
      "data",
      "model",
      "no_price",
      "thin_market",
      "price_outlier",
      "price_stale",
      "ev_unknown",
      "ev_cal_below",
      "context_stop",
      "key_absence_confirmed",
      "key_absence_reported",
      "risk",
      "price_not_fresh",
      "edge_not_validated",
      "correlated_same_match",
    ];
    for (const locale of LOCALES) {
      for (const reason of reasons) expect(hasKey(`families.reason.${reason}`, locale)).toBe(true);
    }
    setLocale("es");
    expect(reasonName("price_outlier")).toBe("Precio atípico");
    expect(reasonName("ai_reject")).toBe("ai_reject");
    expect(reasonsShown(["family_research", "not_calibrated"])).toEqual(["Sin calibrar"]);
    expect(reasonsShown(["family_research"])).toEqual([]);
    expect(reasonsShown([])).toEqual([]);
    expect(reasonsShown(["family_research", "price_outlier", "family_shadow_only"])).toEqual([
      "Precio atípico",
      "La familia solo mide",
    ]);
  });

  test("a result, a verdict, a step status and a state are as green or red as they are good or bad news", () => {
    expect(resultTone("win")).toBe("positive");
    expect(resultTone("half_win")).toBe("positive");
    expect(resultTone("loss")).toBe("negative");
    expect(resultTone("half_loss")).toBe("negative");
    expect(resultTone("push")).toBe("neutral");
    expect(resultTone("void")).toBe("neutral");
    expect(resultTone("other")).toBe("neutral");
    expect(verdictTone("MERECIDO")).toBe("positive");
    expect(verdictTone("VARIANZA")).toBe("info");
    expect(verdictTone("SUERTE")).toBe("warning");
    expect(verdictTone("ERROR")).toBe("negative");
    expect(verdictTone("NULO")).toBe("neutral");
    expect(verdictTone("SIN_DATOS")).toBe("neutral");
    expect(stepTone("ok")).toBe("positive");
    expect(stepTone("partial")).toBe("warning");
    expect(stepTone("failed")).toBe("negative");
    expect(stepTone("running")).toBe("info");
    expect(stepTone("unknown")).toBe("neutral");
    expect(stateTone("INVESTIGACION")).toBe("info");
    expect(stateTone("RECHAZADO")).toBe("negative");
    expect(stateTone("APROBADO")).toBe("neutral");
  });
});

describe("the catalog is complete", () => {
  test("every part of a market name exists in both languages", () => {
    for (const locale of LOCALES) {
      for (const count of ["goals", "corners", "cards", "yellow"]) {
        for (const subject of ["", "_home", "_away"]) {
          expect(hasKey(`families.what.${count}${subject}`, locale)).toBe(true);
        }
      }
      for (const kind of ["OU", "1X2", "DC", "DNB", "BTTS", "AH", "OE"]) {
        expect(hasKey(`families.kind.${kind}`, locale)).toBe(true);
      }
      for (const half of ["1H", "2H"]) expect(hasKey(`families.half.${half}`, locale)).toBe(true);
      for (const key of ["HTFT", "HSH", "HSH_HOME", "HSH_AWAY"]) {
        expect(hasKey(`families.special.${key}`, locale)).toBe(true);
      }
    }
  });

  test("the four families, the four steps and every figure a step reports have words in both languages", () => {
    for (const locale of LOCALES) {
      for (const code of FAMILY_CODES) expect(hasKey(`families.family.${code}`, locale)).toBe(true);
      for (const step of STEPS) expect(hasKey(`families.step.${step}`, locale)).toBe(true);
      for (const status of ["ok", "partial", "failed", "skipped", "interrupted", "running"]) {
        expect(hasKey(`families.status.${status}`, locale)).toBe(true);
      }
      for (const key of [
        "forecasts",
        "candidates",
        "written",
        "failed",
        "open",
        "settled",
        "no_close",
        "unreadable",
        "postmortems",
        "entities",
        "unchanged",
      ]) {
        expect(hasKey(`families.fact.${key}`, locale)).toBe(true);
      }
    }
  });
});
