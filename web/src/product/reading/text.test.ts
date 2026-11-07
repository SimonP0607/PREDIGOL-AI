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
  f(
    "value_pick",
    {
      market: "1X2",
      selection: "Home",
      line: 0,
      home: "Nacional",
      away: "Millonarios",
      p_model: 0.523,
      p_market: 0.452,
    },
    "pick:7",
  ),
  f(
    "value_price",
    {
      market: "1X2",
      selection: "Home",
      line: 0,
      home: "Nacional",
      away: "Millonarios",
      odds: 2.31,
      fair_market: 2.21,
      fair_model: 1.91,
      taken: false,
    },
    "pick:7",
  ),
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
  test("the round of the match intro reads as the header reads it, never the provider's English", () => {
    const intro = f("match_intro", { competition: "La Liga", round: "Regular Season - 12" });
    expect(factText(intro)).toBe("Partido de La Liga (Jornada 12).");
    expect(factText(intro)).not.toContain("Regular Season");
    expect(
      factText(f("match_intro", { competition: "Liga BetPlay", round: "Clausura - 11" })),
    ).toBe("Partido de Liga BetPlay (Clausura · Jornada 11).");
    expect(factText(f("match_intro", { competition: "La Liga" }))).toBe("Partido de La Liga.");
    setLocale("en");
    expect(factText(intro)).toBe("A La Liga match (Matchday 12).");
  });

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

  test("a count of one reads in the singular, never «1 partidos» or «1 empates» (plan Partidos y Match Center, A1)", () => {
    const one = [
      f("rest_days", { side: "home", team: "Nacional", days: 1, matches_14d: 1 }),
      f("h2h", {
        n: 1,
        n_effective: 0.4,
        home: "Nacional",
        home_wins: 1,
        draws: 1,
        away: "Millonarios",
        away_wins: 0,
      }),
      f("next_match", { side: "home", team: "Nacional", days: 1 }),
      f("form", { team: "Nacional", sequence: "W", n: 1, ppg: 3, goals_for: 2, goals_against: 0 }),
      f("venue_record", { side: "away", team: "Nacional", n: 1, wins: 1, draws: 0, losses: 0 }),
      f("xg", { team: "Nacional", xg_for: 1.2, xg_against: 0.8, n: 1 }),
      f("streak_unbeaten", { team: "Nacional", n: 1 }),
      f("top_scorer", { team: "Nacional", player: "Dorlan Pabón", goals: 1, minutes: 1 }),
      f("market_favourite", { outcome: "home", team: "Nacional", probability: 0.4, bookmakers: 1 }),
      f("h2h_weak", { n: 1, n_effective: 0.2 }),
      f("table_after", {
        result: "home_win",
        home: "Nacional",
        home_points: 1,
        home_best: 1,
        home_worst: 1,
        away: "Millonarios",
        away_points: 0,
        away_best: 2,
        away_worst: 2,
      }),
    ].map(factText);
    expect(one).toEqual([
      "Nacional llega con 1 día de descanso y 1 partido en los últimos 14 días.",
      "Cara a cara (90 minutos): 1 partido, 1 victoria de Nacional, 1 empate y 0 de Millonarios.",
      "Nacional vuelve a jugar en 1 día.",
      "Nacional: G en su último partido (3,00 puntos por partido; 2,0 goles a favor y 0,0 en contra por partido).",
      "Nacional fuera: 1G 0E 0P en 1 partido.",
      "Nacional genera 1,20 xG y concede 0,80 (en 1 partido con estadísticas).",
      "Nacional suma 1 partido sin perder.",
      "Nacional: Dorlan Pabón lleva 1 gol en 1 minuto.",
      "El mercado da 40 % a la victoria de Nacional (1 casa).",
      "El cara a cara dice poco: 1 partido, con poco peso para este partido.",
      "Si gana Nacional: Nacional sumaría 1 punto (puesto 1.º) y Millonarios, 0 (puesto 2.º).",
    ]);
    for (const text of one) {
      expect(text ?? "").not.toMatch(
        /\b1 (partidos|empates|victorias|días|goles|minutos|casas|puntos)\b/,
      );
    }
    setLocale("en");
    expect(factText(f("rest_days", { team: "Nacional", days: 1, matches_14d: 1 }))).toBe(
      "Nacional comes in with 1 day of rest and 1 match in the last 14 days.",
    );
    expect(
      factText(
        f("h2h", {
          n: 1,
          home: "Nacional",
          home_wins: 1,
          draws: 0,
          away: "Millonarios",
          away_wins: 0,
        }),
      ),
    ).toBe(
      "Head to head (90 minutes): 1 meeting, 1 win for Nacional, 0 draws and 0 for Millonarios.",
    );
  });

  test("and the plural stays the plural, with decimals for days", () => {
    expect(factText(SAMPLES[12]!)).toBe("Nacional vuelve a jugar en 3,5 días (Copa Libertadores).");
    expect(factText(SAMPLES[18]!)).toBe(
      "Cara a cara (90 minutos): 8 partidos, 2 victorias de Nacional, 3 empates y 3 de Millonarios.",
    );
    expect(factText(SAMPLES[19]!)).toBe("Nacional: Dorlan Pabón lleva 7 goles en 900 minutos.");
  });

  test("the head to head has no «efectivos» for the reader: the effective count stays in the API", () => {
    for (const locale of ["es", "en"] as const) {
      setLocale(locale);
      expect(SAMPLES[32]!.code).toBe("h2h_weak");
      for (const text of [factText(SAMPLES[18]!), factText(SAMPLES[32]!)]) {
        expect(text ?? "").not.toMatch(/efectiv|effective|2,4|2\.4|0,8|0\.8/);
      }
    }
    for (const s of strings({ es: esMatch.facts, en: enMatch.facts })) {
      expect(s).not.toContain("n_effective");
      expect(s).not.toMatch(/efectivos|effective\)/);
    }
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

  test("why there is value: the probability of each, the gap in whole points, the price against the fair price of each", () => {
    expect(factText(SAMPLES[40]!)).toBe(
      "Gana Nacional: PrediGol le da 52 % de probabilidad y el mercado, 45 % (diferencia de 7 puntos porcentuales).",
    );
    expect(factText(SAMPLES[41]!)).toBe(
      "Gana Nacional: la mejor cuota ahora es 2,31. La cuota justa del mercado es 2,21 y la cuota según PrediGol, 1,91.",
    );
    setLocale("en");
    expect(factText(SAMPLES[40]!)).toBe(
      "Nacional to win: PrediGol gives it a 52% probability and the market, 45% (a gap of 7 percentage points).",
    );
  });

  test("a pick already taken says the price it was taken at; a missing fair price leaves its clause out", () => {
    const price = (extra: ReadingFact["params"]) =>
      f(
        "value_price",
        { market: "OU", selection: "Over", line: 2.5, home: "A", away: "B", odds: 1.95, ...extra },
        "pick:9",
      );
    expect(factText(price({ taken: true, fair_market: null, fair_model: null }))).toBe(
      "Más de 2,5 goles: la cuota con la que se tomó fue 1,95.",
    );
    expect(factText(price({ taken: true, fair_market: null, fair_model: 1.8 }))).toBe(
      "Más de 2,5 goles: la cuota con la que se tomó fue 1,95. La cuota según PrediGol es 1,80.",
    );
    expect(factText(price({ taken: false, fair_market: 2, fair_model: null }))).toBe(
      "Más de 2,5 goles: la mejor cuota ahora es 1,95. La cuota justa del mercado es 2,00.",
    );
  });

  test("the gap is the difference of the two percentages shown, and never a negative or a zero one", () => {
    const pick = (p_model: number, p_market: number) =>
      f(
        "value_pick",
        { market: "BTTS", selection: "Yes", line: 0, home: "A", away: "B", p_model, p_market },
        "pick:9",
      );
    expect(factText(pick(0.285, 0.275))).toContain("(diferencia de 1 punto porcentual)");
    expect(factText(pick(0.5, 0.5))).not.toContain("diferencia");
    expect(factText(pick(0.48, 0.5))).not.toContain("diferencia");
  });

  test("an unknown code or a missing parameter: no sentence at all", () => {
    expect(
      factText(f("value_pick", { market: "1X2", selection: "Home", p_model: 0.5 })),
    ).toBeNull();
    expect(factText(f("value_price", { market: "1X2", selection: "Home", odds: null }))).toBeNull();
    expect(factText(f("a_code_from_the_future", { x: 1 }))).toBeNull();
    expect(factText(f("expected_result", { outcome: "home", probability: 0.5 }))).toBeNull();
    expect(factText(f("stakes_pressure", { team: "Nacional", pressure: "unknown" }))).toBeNull();
    expect(factText(f("not_checked", { blocks: ["nothing_we_know"] }))).toBeNull();
    expect(factText(f("form", { team: "Nacional" }))).toBeNull();
    expect(factText(f("rumours", { count: 0 }))).toBeNull();
  });
});

describe("what the templates never say (plan section 26)", () => {
  const CERTAINTY_ES =
    /\b(seguro|segura|fijo|fija|garantizad[oa]s?|asegurad[oa]s?|ganancia|ganar[áa])\b/i;
  const CERTAINTY_EN = /\b(sure|surely|guaranteed|lock|profit|will win)\b/i;
  test("the words of «Por qué hay valor» promise nothing, in either language", () => {
    for (const s of strings(esMatch.understand)) expect(s).not.toMatch(CERTAINTY_ES);
    for (const s of strings(enMatch.understand)) expect(s).not.toMatch(CERTAINTY_EN);
    expect(esMatch.understand.valueNote).toContain("no es una promesa");
    expect(enMatch.understand.valueNote).toContain("not a promise");
  });

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
