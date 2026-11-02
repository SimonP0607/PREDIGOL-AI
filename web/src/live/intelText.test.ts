/// <reference types="bun" />
/**
 * Plan F13: the Intelligence page says in words what it used to print as JSON or as a bare code.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { setLocale } from "@/lib/i18n";
import { DASH } from "@/lib/i18n/format";
import { calibratorParamsText, codeText, gateGroups, secondLegText } from "./intelText";

afterEach(() => setLocale("es"));

// What GET /admin/intelligence/calibration sends as `gates` (backend/src/fbi/api/services/intelligence.py).
const GATES = {
  calib_gate: {
    version: "calib-gate-v1",
    min_oos_n: 1500,
    min_oos_days: 5,
    min_gain_vs_raw: 0.005,
    max_ece: 0.03,
    max_loss_vs_market: 0.002,
  },
  edge_gate: { version: "edge-gate-v1", ev_rule: 0.02, min_rule_n: 300, min_rule_clv: 0 },
  replace_gain: 0.002,
  refit_every_days: 7,
};

describe("calibratorParamsText", () => {
  test("the coefficients in the order they are applied, three decimals, in the reader's language", () => {
    setLocale("es");
    expect(calibratorParamsText({ c: -0.04, b: 0.95, a: 0.12 })).toMatch(
      /^a 0,120 · b 0,950 · c [-−]0,040$/,
    );
    setLocale("en");
    expect(calibratorParamsText({ c: -0.04, b: 0.95, a: 0.12 })).toMatch(
      /^a 0\.120 · b 0\.950 · c [-−]0\.040$/,
    );
  });

  test("the names nobody planned come after, alphabetically; a list says how many it has", () => {
    setLocale("en");
    expect(calibratorParamsText({ z: 1, a: 2, knots: [1, 2, 3] })).toBe(
      "a 2.000 · knots 3 values · z 1.000",
    );
  });

  test("no coefficients is said, and what is not a set of parameters is a dash", () => {
    setLocale("en");
    expect(calibratorParamsText({})).toBe("No coefficients (changes nothing)");
    for (const none of [null, undefined, [], "x", 3]) expect(calibratorParamsText(none)).toBe(DASH);
  });
});

describe("gateGroups", () => {
  test("the gates the API sends become three labelled groups, not a block of JSON", () => {
    setLocale("es");
    const groups = gateGroups(GATES);
    expect(groups.map((g) => g.key)).toEqual(["calib_gate", "edge_gate", "general"]);
    expect(groups.map((g) => g.title)).toEqual([
      "Para validar un calibrador",
      "Para validar una ventaja",
      "General",
    ]);
    const line = (group: number, key: string) => groups[group]?.lines.find((l) => l.key === key);
    expect(line(0, "min_oos_n")?.label).toBe("Partidos mínimos fuera de muestra");
    expect(line(0, "min_oos_n")?.value).toMatch(/^1[.\s\u00a0]?500$/);
    expect(line(0, "max_ece")?.value).toBe("0,030");
    expect(line(0, "version")?.value).toBe("calib-gate-v1");
    expect(line(2, "refit_every_days")?.value).toBe("7");
  });

  test("a return (the expected value a rule asks for, the CLV it must show) is a percentage; a log loss is not", () => {
    setLocale("es");
    const groups = gateGroups(GATES);
    const edge = groups[1]?.lines ?? [];
    expect(edge.find((l) => l.key === "ev_rule")?.value).toMatch(/^2,0\s?%$/);
    expect(edge.find((l) => l.key === "min_rule_clv")?.value).toMatch(/^0,0\s?%$/);
    expect(groups[0]?.lines.find((l) => l.key === "min_gain_vs_raw")?.value).toBe("0,005");
  });

  test("a criterion nobody has named is shown by its own name, in English too", () => {
    setLocale("en");
    const groups = gateGroups({ calib_gate: { brand_new: 3, flag: true }, loose: 0.5 });
    expect(groups[0]?.lines).toEqual([
      { key: "brand_new", label: "brand_new", value: "3" },
      { key: "flag", label: "flag", value: "yes" },
    ]);
    expect(groups[1]?.title).toBe("General");
    expect(groups[1]?.lines[0]).toEqual({ key: "loose", label: "loose", value: "0.500" });
  });

  test("never JSON, whatever comes in", () => {
    setLocale("en");
    const groups = gateGroups({ calib_gate: { nested: { deeper: 1 }, list: [1, 2] } });
    const text = JSON.stringify(groups.flatMap((g) => g.lines.map((l) => l.value)));
    expect(text).not.toContain("deeper");
    expect(groups[0]?.lines.map((l) => l.value)).toEqual([DASH, "2 values"]);
    for (const none of [null, undefined, 3, "x", []]) expect(gateGroups(none)).toEqual([]);
  });
});

describe("secondLegText", () => {
  const LEG = {
    first_leg_at: "2026-10-21T20:00:00+00:00",
    first_leg_score_home_side: 1,
    first_leg_score_away_side: 2,
    aggregate_need: "el local remonta",
  };

  test("the first leg, what the tie needs and when it was played", () => {
    setLocale("es");
    const es = secondLegText(LEG);
    expect(es).toContain("Ida 1–2");
    expect(es).toContain("el local remonta");
    expect(es).toContain("21");
    setLocale("en");
    const en = secondLegText(LEG);
    expect(en).toContain("First leg 1–2");
    expect(en).toContain("home side must come back");
  });

  test("the other two words of the dossier, and a word nobody planned goes through as it is", () => {
    setLocale("en");
    expect(secondLegText({ ...LEG, aggregate_need: "el visitante remonta" })).toContain(
      "away side must come back",
    );
    expect(secondLegText({ ...LEG, aggregate_need: "empate global" })).toContain(
      "level on aggregate",
    );
    expect(secondLegText({ ...LEG, aggregate_need: "otra cosa" })).toContain("otra cosa");
  });

  test("whatever is missing is left out, and nothing at all is a dash", () => {
    setLocale("en");
    expect(secondLegText({ aggregate_need: "empate global" })).toBe("level on aggregate");
    expect(secondLegText({})).toBe(DASH);
    for (const none of [null, undefined, "x", 3, []]) expect(secondLegText(none)).toBe(DASH);
  });
});

describe("codeText", () => {
  test("the verdict and the quality of a post-mortem, the method of a calibrator, the result of a bet", () => {
    setLocale("es");
    expect(codeText("verdict", "MERECIDO")).toBe("Merecido");
    expect(codeText("verdict", "SIN_DATOS")).toBe("Sin datos");
    expect(codeText("quality", "BAD")).toBe("Mala");
    expect(codeText("method", "identity")).toBe("Sin corrección");
    expect(codeText("result", "half_win")).toBe("medio ganado");
    setLocale("en");
    expect(codeText("verdict", "VARIANZA")).toBe("Variance");
    expect(codeText("quality", "UNKNOWN")).toBe("Unknown");
    expect(codeText("method", "logit2")).toBe("Logistic with the market price");
    expect(codeText("result", "half_loss")).toBe("half loss");
  });

  test("a code nobody has named comes back as it is; nothing at all is a dash", () => {
    setLocale("en");
    expect(codeText("verdict", "NUEVO")).toBe("NUEVO");
    for (const none of [null, undefined, ""]) expect(codeText("quality", none)).toBe(DASH);
  });
});

describe("the page", () => {
  test("IntelligenceLive no longer prints JSON: it is said in words", () => {
    const text = readFileSync(join(import.meta.dir, "IntelligenceLive.tsx"), "utf8");
    expect(text).not.toContain("JSON.stringify");
    expect(text).toContain("calibratorParamsText(");
    expect(text).toContain("gateGroups(");
    expect(text).toContain("secondLegText(");
  });
});
