/// <reference types="bun" />
/**
 * The structured reading in the reader's words (plan UX, A9; section 26): every code the API sends has a sentence in Spanish
 * and in English, a code this page does not know is left out (never shown raw), a missing parameter leaves the sentence out
 * rather than with a gap, and no template says what the plan forbids - certainty ("seguro", "fijo", "garantizado") or value.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { setLocale, type Locale } from "@/lib/i18n";
import enMatch from "@/locales/en/match.json";
import esMatch from "@/locales/es/match.json";
import type { ReadingFact } from "@/lib/api/v1/types_reading";
import CODES from "./codes.json";
import { factText as written, READING_CODES, writtenCodes } from "./text";

/** Intl writes «52 %» with a no-break space: compared as a plain one. */
const factText = (fact: ReadingFact): string | null =>
  written(fact)?.replace(/[\u00a0\u202f]/g, " ") ?? null;

setLocale("es");
afterEach(() => setLocale("es"));

const f = (code: string, params: ReadingFact["params"], ref = "packet:x"): ReadingFact => ({
  code,
  params,
  ref,
});

/** One fact of every code, with the parameters the API sends. */
const SAMPLES: ReadingFact[] = [
  f("match_intro", { competition: "Liga BetPlay", round: "Fecha 17", neutral: true }),
  f("match_kind", { kind: "final" }),
  f("expected_result", {
    outcome: "away",
    team: "Millonarios",
    probability: 0.523,
    calibrated: false,
  }),
  f("forecast_missing", { reason: "no_forecast_yet" }),
  f("stakes_zone", { side: "home", team: "Nacional", rank: 3, zone: "title" }),
  f("stakes_gap_up", { side: "home", team: "Nacional", gap: 1, zone: "title" }),
  f("stakes_gap_down", { side: "away", team: "Millonarios", gap: 4, zone: "relegation" }),
  f("stakes_pressure", { side: "away", team: "Millonarios", pressure: "title" }),
  f("first_leg", { home_goals: 1, away_goals: 2 }),
  f("tie_outlook", { ahead_from: 2, level_at: 1, home: "Nacional", away: "Millonarios" }),
  f("table_after", {
    result: "draw",
    home: "Nacional",
    home_points: 30,
    home_best: 2,
    home_worst: 4,
    away: "Millonarios",
    away_points: 31,
    away_best: 1,
    away_worst: 1,
  }),
  f("rest_days", { side: "home", team: "Nacional", days: 3, matches_14d: 4, at_most: true }),
  f("next_match", { side: "home", team: "Nacional", days: 3.5, competition: "Copa Libertadores" }),
  f("form", {
    side: "home",
    team: "Nacional",
    sequence: "WWDLW",
    n: 5,
    ppg: 2,
    goals_for: 1.8,
    goals_against: 1,
  }),
  f("venue_record", { side: "home", team: "Nacional", n: 4, wins: 3, draws: 1, losses: 0 }),
  f("xg", { side: "home", team: "Nacional", xg_for: 1.71, xg_against: 1.02, n: 9 }),
  f("streak_unbeaten", { side: "home", team: "Nacional", n: 5 }),
  f("streak_winless", { side: "away", team: "Millonarios", n: 4 }),
  f("h2h", {
    n: 8,
    n_effective: 2.4,
    home: "Nacional",
    home_wins: 2,
    draws: 3,
    away: "Millonarios",
    away_wins: 3,
  }),
  f("top_scorer", {
    side: "home",
    team: "Nacional",
    player: "Dorlan Pabón",
    goals: 7,
    minutes: 900,
  }),
  f("key_absences", {
    side: "home",
    team: "Nacional",
    count: 4,
    players: ["A. Uno", "B. Dos", "C. Tres"],
  }),
  f("market_unpriced", {}),
  f("market_favourite", { outcome: "home", team: "Nacional", probability: 0.412, bookmakers: 11 }),
  f("market_moved", { outcome: "home", team: "Nacional", opening: 0.352, now: 0.318 }),
  f("market_total", { outcome: "over", line: "2.5", probability: 0.585 }),
  f("no_context_yet", {}),
  f("lineups_unconfirmed", {}),
  f("short_rest", { side: "home", team: "Nacional" }),
  f("rest_disadvantage", { side: "home", team: "Nacional" }),
  f("contradictory_news", { count: 2 }),
  f("rumours", { count: 1 }),
  f("no_external_info", {}),
  f("h2h_weak", { n: 2, n_effective: 0.8 }),
  f("data_not_fit", {}),
  f("not_checked", { blocks: ["stats", "lineups"] }),
  f("uncalibrated", { markets: ["1X2", "BTTS"] }),
  f("none_found", {}),
  f("description_only", {}),
  f("likely", {
    market: "OU",
    outcome: "over",
    team: null,
    line: "2.5",
    probability: 0.62,
    calibrated: true,
  }),
  f("no_forecast", { reason: "quarantined" }),
];

function strings(node: unknown): string[] {
  if (typeof node === "string") return [node];
  if (node && typeof node === "object") return Object.values(node).flatMap(strings);
  return [];
}

describe("every code has its sentence", () => {
  test("the codes the page writes are the API's (codes.json, which a backend test holds to fbi.api.services.reading)", () => {
    expect([...writtenCodes()].sort()).toEqual([...CODES].sort());
    expect(READING_CODES).toEqual(CODES);
    expect(new Set(SAMPLES.map((s) => s.code))).toEqual(new Set(CODES));
  });

  for (const locale of ["es", "en"] as const satisfies readonly Locale[]) {
    test(`a sentence for every code in ${locale}, with no placeholder left and no raw code`, () => {
      setLocale(locale);
      for (const sample of SAMPLES) {
        const text = factText(sample);
        expect(text, sample.code).toBeTruthy();
        expect(text ?? "", sample.code).not.toMatch(/[{}]|match\.facts|undefined|null|NaN/);
        if (sample.code.includes("_")) expect(text ?? "", sample.code).not.toContain(sample.code);
      }
    });
  }
});

describe("what the sentences say", () => {
  test("the result PrediGol expects, labelled when uncalibrated", () => {
    expect(factText(SAMPLES[2]!)).toBe(
      "PrediGol ve como resultado más probable la victoria de Millonarios (52 %, sin calibrar).",
    );
    setLocale("en");
    expect(factText(SAMPLES[2]!)).toBe(
      "PrediGol sees a Millonarios win as the likeliest result (52%, uncalibrated).",
    );
  });

  test("a calendar that is not whole says «a lo sumo»; a form in the reader's letters", () => {
    expect(factText(SAMPLES[11]!)).toBe(
      "Nacional llega con a lo sumo 3 días de descanso y 4 partidos en los últimos 14 días.",
    );
    expect(factText(SAMPLES[13]!)).toContain("GGEPG en sus últimos 5 partidos");
    setLocale("en");
    expect(factText(SAMPLES[13]!)).toContain("WWDLW in the last 5 matches");
  });

  test("the market: implied probability, its move, never a price or a bookmaker", () => {
    expect(factText(SAMPLES[22]!)).toBe("El mercado da 41 % a la victoria de Nacional (11 casas).");
    expect(factText(SAMPLES[23]!)).toBe(
      "Desde la apertura, la victoria de Nacional pasó de 35 % a 32 % en el mercado.",
    );
  });

  test("risks say how many, never what; a list of names ends in «y»", () => {
    expect(factText(SAMPLES[30]!)).toBe("Hay 1 rumor sin confirmar: no cuenta como hecho.");
    expect(factText(SAMPLES[29]!)).toBe("Hay 2 informaciones contradictorias sobre el partido.");
    expect(factText(SAMPLES[20]!)).toBe(
      "Bajas importantes de Nacional: A. Uno, B. Dos y C. Tres y 1 más.",
    );
    expect(factText(SAMPLES[34]!)).toBe(
      "No pudimos comprobar: las estadísticas y las alineaciones.",
    );
  });

  test("an unknown code or a missing parameter: no sentence at all", () => {
    expect(factText(f("a_code_from_the_future", { x: 1 }))).toBeNull();
    expect(factText(f("expected_result", { outcome: "home", probability: 0.5 }))).toBeNull();
    expect(factText(f("stakes_pressure", { team: "Nacional", pressure: "unknown" }))).toBeNull();
    expect(factText(f("not_checked", { blocks: ["nothing_we_know"] }))).toBeNull();
    expect(factText(f("form", { team: "Nacional" }))).toBeNull();
    expect(factText(f("rumours", { count: 0 }))).toBeNull();
  });
});

describe("what the templates never say (plan section 26)", () => {
  const VETOED_ES = /\b(seguro|segura|fijo|fija|garantizad[oa]s?|valor|apuesta)\b/i;
  const VETOED_EN = /\b(sure|guaranteed|value|lock|bet)\b/i;
  test("no certainty and no value in Spanish", () => {
    for (const s of strings({
      facts: esMatch.facts,
      block: esMatch.readingBlock,
      post: esMatch.postmatch,
    }))
      expect(s).not.toMatch(VETOED_ES);
  });
  test("no certainty and no value in English", () => {
    for (const s of strings({
      facts: enMatch.facts,
      block: enMatch.readingBlock,
      post: enMatch.postmatch,
    }))
      expect(s).not.toMatch(VETOED_EN);
  });
});
