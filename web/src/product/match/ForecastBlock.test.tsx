/// <reference types="bun" />
/**
 * Plan F5, PRONÓSTICO PREDIGOL in the Resumen: a probability and the interval around it, "Sin calibrar" wherever no
 * champion calibrator exists, no price anywhere for a user, and nothing at all for a user until the owner decides.
 * The Admin Console's preview alone sees the fair odds and, folded away, the value and the picks of the match and,
 * in a block of its own, what the families forecast for it (plan F10.17b): research, never shown to a user.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import enMatch from "@/locales/en/match.json";
import esMatch from "@/locales/es/match.json";
import type { Envelope, Section } from "@/lib/api/v1/types";
import type {
  FamilyLine,
  FamilyMarket,
  ForecastBasis,
  ForecastCalibration,
  ForecastMarket,
  ForecastOutcome,
  ForecastPickRow,
  ForecastValueRow,
  MatchForecast,
} from "@/lib/api/v1/types_forecast";
import { ForecastView } from "./ForecastBlock";
import {
  barPercent,
  basisNote,
  familyOutcomeText,
  familyPercent,
  forecastScreen,
  groupFamilies,
  intervalSpan,
  intervalText,
  modelLabel,
  noForecastText,
  outcomeLabel,
  type ForecastLoad,
} from "./forecast";

setLocale("es");
afterEach(() => setLocale("es"));

const KNOWN = "2026-10-23T09:00:00Z";

function outcome(
  selection: string,
  p: number,
  low: number | null,
  high: number | null,
  likely = false,
  extra: Partial<ForecastOutcome> = {},
): ForecastOutcome {
  return {
    selection,
    probability: p.toFixed(4),
    low: low === null ? null : low.toFixed(4),
    high: high === null ? null : high.toFixed(4),
    likely,
    ...extra,
  };
}

function market(
  key: string,
  line: string,
  calibration: ForecastCalibration,
  basis: ForecastBasis,
  outcomes: ForecastOutcome[],
  model = "dixon_coles",
): ForecastMarket {
  return {
    market: key,
    line,
    family: key === "1X2" ? "RESULT" : key === "OU" ? "TOTAL_GOALS" : "BOTH_TEAMS_SCORE",
    model,
    calibration,
    basis,
    known_at: KNOWN,
    data_cutoff_at: "2026-10-23T08:30:00Z",
    outcomes,
  };
}

/** The three core markets, as the API lays them out: the result, the total at 2.5, both teams to score. */
function threeMarkets(extra: { fair: boolean } = { fair: false }): ForecastMarket[] {
  const fair = (p: number): Partial<ForecastOutcome> =>
    extra.fair ? { fair_odds: (1 / p).toFixed(2) } : {};
  return [
    market("1X2", "0.00", "UNCALIBRATED", "no_champion", [
      outcome("Home", 0.52, 0.44, 0.6, true, fair(0.52)),
      outcome("Draw", 0.26, 0.19, 0.33, false, fair(0.26)),
      outcome("Away", 0.22, 0.16, 0.29, false, fair(0.22)),
    ]),
    market("OU", "2.50", "CALIBRATED", "champion", [
      outcome("Over", 0.57, 0.5, 0.64, true, {
        ...fair(0.57),
        ...(extra.fair ? { model_probability: "0.5500" } : {}),
      }),
      outcome("Under", 0.43, 0.36, 0.5, false, fair(0.43)),
    ]),
    market("BTTS", "0.00", "UNCALIBRATED", "needs_price", [
      outcome("Yes", 0.48, 0.41, 0.55, false, fair(0.48)),
      outcome("No", 0.52, 0.45, 0.59, true, fair(0.52)),
    ]),
  ];
}

const VALUE: ForecastValueRow = {
  market: "1X2",
  selection: "Home",
  line: "0.00",
  state: "RECHAZADO",
  odds: "1.28",
  probability: "0.5200",
  market_probability: "0.5000",
  edge: "0.0200",
  ev: "-0.0100",
  reasons: ["price too short"],
  known_at: KNOWN,
};

const PICK: ForecastPickRow = {
  id: 77,
  market: "OU",
  selection: "Over",
  line: "2.50",
  status: "PENDING",
  mode: "shadow",
  odds: "1.95",
  probability: "0.5700",
};

function forecast(markets: ForecastMarket[], preview: boolean): MatchForecast {
  return {
    fixture_id: 45140,
    kickoff_at: "2026-10-24T01:00:00Z",
    status_group: "scheduled",
    forecast: { status: "ok", data: markets, reason: null },
    value: preview ? { status: "ok", data: [VALUE], reason: null } : null,
    picks: preview ? { status: "ok", data: [PICK], reason: null } : null,
  };
}

function envelope(data: MatchForecast | null, status: Envelope<unknown>["status"] = "ok") {
  return {
    status,
    data,
    reason: status === "ok" ? null : "The PrediGol forecast is not shown to users yet.",
    meta: {
      generated_at: KNOWN,
      api_version: "v1",
      count: null,
      total: null,
      limit: null,
      offset: null,
      data_as_of: KNOWN,
    },
  } as unknown as Envelope<MatchForecast | null>;
}

function render(load: ForecastLoad, preview: boolean): string {
  return renderToStaticMarkup(
    <ForecastView load={load} home="Nashville SC" away="Inter Miami" preview={preview} />,
  );
}

const userSees = (): ForecastLoad => ({
  status: "success",
  envelope: envelope(forecast(threeMarkets(), false)),
});
const adminSees = (): ForecastLoad => ({
  status: "success",
  envelope: envelope(forecast(threeMarkets({ fair: true }), true)),
});

describe("what a user sees once the owner lets users see the forecast", () => {
  const out = render(userSees(), false);

  test("the title, and the words that say it is not a recommendation nor a price", () => {
    expect(out).toContain('data-testid="forecast-block"');
    expect(out).toContain("Pronóstico PrediGol");
    expect(out).toContain("no una recomendación ni una cuota para apostar");
    expect(out).toContain("no si está bien pagado");
  });

  test("the three markets in order, each with its title", () => {
    const keys = [...out.matchAll(/data-testid="forecast-market" data-market="([^"]+)"/g)].map(
      (m) => m[1],
    );
    expect(keys).toEqual(["1X2", "OU", "BTTS"]);
    expect(out).toContain("Resultado final (1X2)");
    expect(out).toContain("Goles: más/menos de 2,5");
    expect(out).toContain("Ambos marcan");
  });

  test("outcomes are named in full, probabilities are whole percentages with their interval", () => {
    expect(out).toContain("Gana Nashville SC");
    expect(out).toContain("Empate");
    expect(out).toContain("Gana Inter Miami");
    expect(out).toContain("Más de 2,5");
    expect(out).toMatch(/52\s%/);
    expect(out).toMatch(/entre 44\s% y 60\s%/);
    expect(out).toMatch(/entre 50\s% y 64\s%/);
    // no false precision: no decimals in a probability
    expect(out).not.toMatch(/52,\d\s%/);
  });

  test("exactly one outcome per market is the most likely", () => {
    const rows = [
      ...out.matchAll(/data-testid="forecast-outcome"[^>]*data-likely="(true|false)"/g),
    ];
    expect(rows.length).toBe(7);
    expect(rows.filter((r) => r[1] === "true").length).toBe(3);
    expect(out.match(/Lo más probable/g)?.length).toBe(3);
  });

  test("calibrated only where a champion calibrator exists, and the others say so, with the reason", () => {
    expect(out.match(/Sin calibrar/g)?.length).toBe(2);
    expect(out.match(/Calibrada/g)?.length).toBe(1);
    expect(out).toContain("todavía no hay una corrección comprobada");
    expect(out).toContain("necesita un precio reciente");
    expect(out).toContain("corrigió la probabilidad del modelo con partidos ya jugados");
    expect(out).toMatch(/data-market="OU" data-calibration="CALIBRATED"/);
    expect(out).toMatch(/data-market="1X2" data-calibration="UNCALIBRATED"/);
  });

  test("the model and when it was said", () => {
    expect(out).toContain("Modelo: Dixon-Coles");
    expect(out).toContain("Actualizado");
  });

  test("the bar of a probability and the line of its interval sit where the numbers say", () => {
    expect(out).toContain("width:52%");
    expect(out).toContain("left:44%;width:16%");
  });

  test("no odds, no edge, no value, no pick, no preview badge", () => {
    expect(out).not.toContain("cuota justa");
    expect(out).not.toContain("modelo 55");
    expect(out).not.toContain("forecast-admin");
    expect(out).not.toContain("forecast-value");
    expect(out).not.toContain("forecast-picks");
    expect(out).not.toContain("RECHAZADO");
    expect(out).toContain('data-preview="false"');
    expect(out).not.toContain("Modo de evaluación");
  });

  test("a user is shown no price even if the payload carried one", () => {
    // Defence in depth: the API sends the fair odds to the preview alone; the view shows them to it alone.
    const leaky: ForecastLoad = {
      status: "success",
      envelope: envelope(forecast(threeMarkets({ fair: true }), true)),
    };
    const seen = render(leaky, false);
    expect(seen).not.toContain("cuota justa");
    expect(seen).not.toContain("1,92");
    expect(seen).not.toContain("forecast-admin");
    expect(seen).not.toContain("RECHAZADO");
    expect(seen).not.toContain("shadow");
  });
});

describe("a user sees nothing until the owner decides", () => {
  test("the API says not available (users do not see the forecast yet)", () => {
    const load: ForecastLoad = {
      status: "success",
      envelope: envelope(null, "not_available"),
    };
    expect(render(load, false)).toBe("");
  });

  test("while it loads, and when it cannot be loaded: no spinner, no error", () => {
    expect(render({ status: "pending" }, false)).toBe("");
    expect(render({ status: "error", error: new Error("boom") }, false)).toBe("");
  });

  test("the screen is decided apart from React", () => {
    expect(forecastScreen({ status: "pending" }, false).kind).toBe("nothing");
    expect(forecastScreen({ status: "pending" }, true).kind).toBe("loading");
    expect(forecastScreen({ status: "error", error: 1 }, false).kind).toBe("nothing");
    expect(forecastScreen({ status: "error", error: 1 }, true).kind).toBe("error");
    expect(forecastScreen(userSees(), false).kind).toBe("forecast");
  });
});

describe("a match without a forecast says why", () => {
  function noForecast(code: string | null): ForecastLoad {
    const data = forecast([], false);
    data.forecast = { status: "not_available", data: [], reason: "x", code };
    return { status: "success", envelope: envelope(data) };
  }

  test("each code in the reader's language, never the API's English", () => {
    const cases: [string, string][] = [
      ["data_not_fit", "PrediGol no pronostica esta competición"],
      ["quarantined", "los datos de este partido están en revisión"],
      ["no_forecast_yet", "PrediGol todavía no tiene pronóstico para este partido"],
    ];
    for (const [code, text] of cases) {
      const out = render(noForecast(code), false);
      expect(out).toContain(text);
      expect(out).toContain('data-testid="forecast-none"');
      expect(out).not.toContain("forecast-market");
      expect(out).not.toContain("is not fit");
    }
  });

  test("an unknown code falls back to a plain note, not to a blank", () => {
    const out = render(noForecast("something_new"), false);
    expect(out).toContain('data-testid="forecast-none"');
    expect(noForecastText("something_new")).toBe(noForecastText(null));
    expect(noForecastText(null).length).toBeGreaterThan(5);
  });
});

describe("the Admin Console's preview", () => {
  const out = render(adminSees(), true);

  test("is marked as a preview, never as a recommendation", () => {
    expect(out).toContain('data-preview="true"');
    expect(out).toContain("Modo de evaluación");
    expect(out).toContain("No es una recomendación");
  });

  test("shows the fair odds beside each number, and the model's own number where it was corrected", () => {
    expect(out).toContain("cuota justa 1,92");
    expect(out).toContain("cuota justa 3,85");
    expect(out.match(/cuota justa/g)?.length).toBe(7);
    // only the calibrated market has a model number that differs from the stated one
    expect(out.match(/modelo 55\s%/g)?.length).toBe(1);
  });

  test("lays the decision layer's value and the frozen picks apart from the forecast, folded away", () => {
    expect(out).toContain("<details");
    expect(out).toContain("Valor y picks de este partido (solo administrador)");
    const forecastEnds = out.lastIndexOf('data-testid="forecast-market"');
    expect(out.indexOf('data-testid="forecast-admin"')).toBeGreaterThan(forecastEnds);
    expect(out).toContain("RECHAZADO");
    expect(out).toContain("price too short");
    expect(out).toContain("PENDING · shadow");
    expect(out).toMatch(/cuota 1,28/);
    expect(out).toMatch(/\+2,0 pp/);
  });

  test("shows a match without value or picks as such, not as a gap", () => {
    const data = forecast(threeMarkets({ fair: true }), true);
    data.value = {
      status: "empty",
      data: [],
      reason: "x",
      code: "no_evaluation",
    };
    data.picks = { status: "empty", data: [], reason: "x", code: "no_pick" };
    const seen = render({ status: "success", envelope: envelope(data) }, true);
    expect(seen).toContain("sin precio no hay valor");
    expect(seen).toContain("un pronóstico, por seguro que sea, no lo es");
  });

  test("still reads the value and picks of a match PrediGol has no forecast for", () => {
    const data = forecast([], true);
    data.forecast = { status: "not_available", data: [], reason: "x", code: "no_forecast_yet" };
    const seen = render({ status: "success", envelope: envelope(data) }, true);
    expect(seen).toContain("PrediGol todavía no tiene pronóstico para este partido");
    expect(seen).toContain("forecast-admin");
  });

  test("shows its own loading and error states", () => {
    const loading = render({ status: "pending" }, true);
    expect(loading).toContain('data-screen="loading"');
    const failed = render({ status: "error", error: new Error("boom") }, true);
    expect(failed).toContain('data-screen="error"');
    expect(failed).toContain('role="alert"');
  });
});

// ── what the families forecast ──────────────────────────────────────────────

function familyOutcome(selection: string, p: number, likely = false): ForecastOutcome {
  return {
    selection,
    probability: p.toFixed(4),
    low: null,
    high: null,
    likely,
    fair_odds: (1 / p).toFixed(2),
  };
}

function familyLine(line: string, outcomes: ForecastOutcome[]): FamilyLine {
  return { line, known_at: KNOWN, outcomes };
}

function familyMarket(
  family: string,
  key: string,
  rule: string | null,
  model: string,
  lines: FamilyLine[],
): FamilyMarket {
  return {
    family,
    market: key,
    model,
    calibration: "UNCALIBRATED",
    rule,
    known_at: KNOWN,
    data_cutoff_at: "2026-10-23T08:30:00Z",
    lines,
  };
}

/** What the API lays out for a match: the four families in their order, each family's markets by key, each market's lines from the lowest. */
function familyMarkets(): FamilyMarket[] {
  return [
    familyMarket("GOALS_HALF", "HTFT", "goals_halves@v1", "family-goals_halves", [
      familyLine("0.00", [
        familyOutcome("Home/Home", 0.31, true),
        familyOutcome("Draw/Draw", 0.18),
        familyOutcome("Home/Away", 0.021),
      ]),
    ]),
    familyMarket("GOALS_HALF", "OU_1H", "goals_1h@v1", "family-goals_halves", [
      familyLine("0.50", [familyOutcome("Over", 0.66, true), familyOutcome("Under", 0.34)]),
    ]),
    familyMarket("CORNERS", "CORNERS_OU", "corners_ft@v1", "family-corners_ft", [
      familyLine("8.50", [familyOutcome("Over", 0.72, true), familyOutcome("Under", 0.28)]),
      familyLine("9.50", [familyOutcome("Over", 0.55, true), familyOutcome("Under", 0.45)]),
      familyLine("10.50", [familyOutcome("Over", 0.38), familyOutcome("Under", 0.62, true)]),
    ]),
    familyMarket("CARDS", "CARDS_OU", "cards_lines_ft@v1", "family-cards_lines_ft", [
      familyLine("3.50", [familyOutcome("Over", 0.52, true), familyOutcome("Under", 0.48)]),
    ]),
    familyMarket("YELLOW", "YELLOW_OU", "yellow_ft@v1", "family-yellow_ft", [
      familyLine("2.50", [familyOutcome("Over", 0.41), familyOutcome("Under", 0.59, true)]),
    ]),
  ];
}

function withFamilies(
  data: MatchForecast,
  families: Section<FamilyMarket[]> | null,
): MatchForecast {
  return { ...data, families };
}

const familiesSection = (markets: FamilyMarket[]): Section<FamilyMarket[]> => ({
  status: "ok",
  data: markets,
  reason: null,
});

function loaded(data: MatchForecast): ForecastLoad {
  return { status: "success", envelope: envelope(data) };
}

/** The html of one market of a family, from its opening to the opening of the next. */
function marketHtml(html: string, key: string): string {
  const start = html.indexOf(`data-testid="family-market" data-market="${key}"`);
  expect(start).toBeGreaterThan(-1);
  const next = html.indexOf('data-testid="family-market"', start + 10);
  return html.slice(start, next === -1 ? undefined : next);
}

describe("what the families forecast, in the preview's block of their own", () => {
  const withBlock = (): MatchForecast =>
    withFamilies(forecast(threeMarkets({ fair: true }), true), familiesSection(familyMarkets()));
  const out = render(loaded(withBlock()), true);
  const block = out.slice(out.indexOf('data-testid="forecast-families"'));

  test("is a block of its own, folded away, after the value and the picks and apart from the forecast above", () => {
    expect(out.match(/data-testid="forecast-families"/g)?.length).toBe(1);
    expect(out).toContain("Familias de este partido (investigación, solo administrador)");
    expect(out.indexOf('data-testid="forecast-families"')).toBeGreaterThan(
      out.indexOf('data-testid="forecast-admin"'),
    );
    expect(out.indexOf('data-testid="forecast-admin"')).toBeGreaterThan(
      out.lastIndexOf('data-testid="forecast-market"'),
    );
    // the forecast above is the three core markets: not one of the families' is among them
    const keys = [...out.matchAll(/data-testid="forecast-market" data-market="([^"]+)"/g)].map(
      (m) => m[1],
    );
    expect(keys).toEqual(["1X2", "OU", "BTTS"]);
    expect(block).toContain("no es el pronóstico de arriba ni una recomendación");
    expect(block).toContain("Entre paréntesis, la cuota justa");
  });

  test("one folded group per family, in the order the API sent them", () => {
    const groups = [...out.matchAll(/data-testid="family-group" data-family="([^"]+)"/g)].map(
      (m) => m[1],
    );
    expect(groups).toEqual(["GOALS_HALF", "CORNERS", "CARDS", "YELLOW"]);
    for (const name of ["Goles por mitad", "Córners", "Tarjetas", "Amarillas"]) {
      expect(block).toContain(name);
    }
    expect(block).toContain("Mercados: 2");
    expect(block.match(/data-testid="family-group"/g)?.length).toBe(4);
  });

  test("each market in words, its lines from the lowest and the probability of every outcome with its fair odds", () => {
    const corners = marketHtml(out, "CORNERS_OU");
    expect(corners).toContain("Córners · más/menos");
    expect([...corners.matchAll(/data-line="([^"]+)"/g)].map((m) => m[1])).toEqual([
      "8.50",
      "9.50",
      "10.50",
    ]);
    expect(corners).toMatch(/Más de 8,5\s72\s%/);
    expect(corners).toMatch(/Menos de 8,5\s28\s%/);
    expect(corners).toContain("(1,39)");
    expect(corners).toContain("(3,57)");
    expect(corners).toContain("cuota justa 1,39");
    // one outcome of each line is the most probable one
    const likely = [...corners.matchAll(/data-selection="([^"]+)" data-likely="(true|false)"/g)];
    expect(likely.map((m) => `${m[1]}:${m[2]}`)).toEqual([
      "Over:true",
      "Under:false",
      "Over:true",
      "Under:false",
      "Over:false",
      "Under:true",
    ]);
    // ... and it is set apart in the type, not only in the markup's data
    expect(corners.match(/data-likely="true" class="[^"]*font-semibold/g)?.length).toBe(3);
    expect(corners.match(/data-likely="false" class="[^"]*font-semibold/g)).toBeNull();
  });

  test("a market with no line names the sides of the match, and a small probability keeps a decimal", () => {
    const htft = marketHtml(out, "HTFT");
    expect(htft).toContain("Descanso/final");
    expect(htft).toMatch(/Nashville SC \/ Nashville SC\s31\s%/);
    expect(htft).toMatch(/Nashville SC \/ Inter Miami\s2,1\s%/);
    expect(marketHtml(out, "OU_1H")).toContain("Goles · más/menos · 1.ª parte");
    expect(marketHtml(out, "YELLOW_OU")).toContain("Amarillas · más/menos");
  });

  test("each market says the rule that grades a bet on it", () => {
    expect(marketHtml(out, "CORNERS_OU")).toContain("Se liquida con: Córners del partido");
    expect(marketHtml(out, "OU_1H")).toContain(
      "Se liquida con: Goles de la 1.ª parte: el marcador al descanso.",
    );
    expect(marketHtml(out, "HTFT")).toContain("Se liquida con: Las dos mitades");
    expect(marketHtml(out, "CARDS_OU")).toContain("Cada tarjeta mostrada cuenta uno");
    expect(marketHtml(out, "YELLOW_OU")).toContain("Solo tarjetas amarillas");
  });

  test("a market no rule can grade says so instead of leaving a blank", () => {
    const orphan = familyMarket("CARDS", "CARDS_OU", null, "family-cards_lines_ft", [
      familyLine("3.50", [familyOutcome("Over", 0.52, true), familyOutcome("Under", 0.48)]),
    ]);
    const seen = render(loaded(withFamilies(forecast([], true), familiesSection([orphan]))), true);
    expect(seen).toContain(
      "Ninguna regla de liquidación puede juzgar una apuesta en este mercado.",
    );
    expect(seen).not.toContain("Se liquida con");
  });

  test("every market of the families says it is not calibrated, and none reads as a recommendation", () => {
    expect(block.match(/data-calibration="UNCALIBRATED"/g)?.length).toBe(5);
    expect(block.match(/Sin calibrar/g)?.length).toBe(5);
    expect(block).not.toContain("Calibrada");
    expect(block).not.toContain("Lo más probable");
    expect(block).not.toContain("entre 4"); // no interval anywhere: the families measure none
  });

  test("the model and when the family said it", () => {
    expect(marketHtml(out, "CORNERS_OU")).toContain("Modelo: family-corners_ft");
    expect(marketHtml(out, "CORNERS_OU")).toContain("Actualizado");
  });

  test("a match the families forecast nothing for says so, in the reader's language", () => {
    const empty: Section<FamilyMarket[]> = {
      status: "empty",
      data: [],
      reason: "x",
      code: "no_family_forecast",
    };
    const seen = render(
      loaded(withFamilies(forecast(threeMarkets({ fair: true }), true), empty)),
      true,
    );
    expect(seen).toContain('data-testid="forecast-families-none"');
    expect(seen).toContain("Las familias no han pronosticado nada de este partido");
    expect(seen).not.toContain("family-group");
  });

  test("an answer without the section (an API that predates it) shows no block", () => {
    expect(render(adminSees(), true)).not.toContain("forecast-families");
    const nulled = withFamilies(forecast(threeMarkets({ fair: true }), true), null);
    expect(render(loaded(nulled), true)).not.toContain("forecast-families");
  });

  test("still shows what the families forecast for a match PrediGol has no forecast for", () => {
    const data = withFamilies(forecast([], true), familiesSection(familyMarkets()));
    data.forecast = { status: "not_available", data: [], reason: "x", code: "no_forecast_yet" };
    const seen = render(loaded(data), true);
    expect(seen).toContain('data-testid="forecast-none"');
    expect(seen).toContain('data-testid="forecast-families"');
  });

  test("a user is shown none of it, even if the payload carried it", () => {
    // Defence in depth: the API sends the section to the preview alone; the view shows it to the preview alone.
    const seen = render(loaded(withBlock()), false);
    for (const word of [
      "forecast-families",
      "family-market",
      "family-group",
      "Familias de este partido",
      "Se liquida con",
      "Goles por mitad",
      "Córners",
    ]) {
      expect(seen).not.toContain(word);
    }
    expect(render(loaded(withBlock()), true)).toContain("forecast-families");
  });

  test("in English", () => {
    setLocale("en");
    const seen = render(loaded(withBlock()), true);
    expect(seen).toContain("Families for this match (research, admin only)");
    for (const name of ["Goals by half", "Corners", "Cards", "Yellow cards"]) {
      expect(seen).toContain(name);
    }
    const corners = marketHtml(seen, "CORNERS_OU");
    expect(corners).toContain("Corners · over/under");
    expect(corners).toMatch(/Over 9\.5\s55%/);
    expect(corners).toContain("Graded with: Corners of the match");
    expect(seen).toContain("Markets: 2");
    expect(seen).not.toContain("Sin calibrar");
    expect(seen).not.toContain("Se liquida");
  });
});

describe("the families' words, apart from React", () => {
  test("the markets are grouped by family in the order the API sent them", () => {
    const groups = groupFamilies(familyMarkets());
    expect(groups.map((g) => [g.family, g.markets.map((m) => m.market)])).toEqual([
      ["GOALS_HALF", ["HTFT", "OU_1H"]],
      ["CORNERS", ["CORNERS_OU"]],
      ["CARDS", ["CARDS_OU"]],
      ["YELLOW", ["YELLOW_OU"]],
    ]);
    expect(groupFamilies([])).toEqual([]);
    const shuffled = [...familyMarkets()].reverse();
    expect(groupFamilies(shuffled).map((g) => g.family)).toEqual([
      "YELLOW",
      "CARDS",
      "CORNERS",
      "GOALS_HALF",
    ]);
  });

  test("a probability keeps a decimal below 10 % and is a whole percentage above", () => {
    expect(familyPercent("0.5500")).toMatch(/^55\s%$/);
    expect(familyPercent(0.21)).toMatch(/^21\s%$/);
    expect(familyPercent("0.0999")).toMatch(/^10,0\s%$/);
    expect(familyPercent("0.1000")).toMatch(/^10\s%$/);
    expect(familyPercent("0.0210")).toMatch(/^2,1\s%$/);
    expect(familyPercent("0.0000")).toMatch(/^0\s%$/);
    expect(familyPercent(null)).toBe("—");
    expect(familyPercent("not a number")).toBe("—");
  });

  test("an outcome is said with the line of its bet and the sides of the match", () => {
    const sides = { home: "Nashville SC", away: "Inter Miami" };
    const corners = familyMarkets()[2]!;
    expect(familyOutcomeText(corners, corners.lines[1]!, { selection: "Over" }, sides)).toBe(
      "Más de 9,5",
    );
    expect(familyOutcomeText(corners, corners.lines[1]!, { selection: "Under" }, sides)).toBe(
      "Menos de 9,5",
    );
    const htft = familyMarkets()[0]!;
    expect(familyOutcomeText(htft, htft.lines[0]!, { selection: "Draw/Away" }, sides)).toBe(
      "Empate / Inter Miami",
    );
    // a selection nobody knows comes back as it came, with its line
    expect(familyOutcomeText(corners, corners.lines[0]!, { selection: "Exactly" }, sides)).toBe(
      "Exactly 8,5",
    );
  });
});

describe("in English", () => {
  test("the same block, in the reader's language", () => {
    setLocale("en");
    const out = render(userSees(), false);
    expect(out).toContain("PrediGol forecast");
    expect(out).toContain("Uncalibrated");
    expect(out).toContain("Calibrated");
    expect(out).toContain("Most likely");
    expect(out).toContain("Over 2.5");
    expect(out).toMatch(/between 44%\sand 60%/);
    expect(out).not.toContain("Sin calibrar");
  });
});

describe("the words and the bar", () => {
  test("outcome labels name the market's sides in full", () => {
    const sides = { home: "Nashville SC", away: "Inter Miami" };
    expect(outcomeLabel({ market: "1X2", line: "0.00" }, { selection: "Home" }, sides)).toBe(
      "Gana Nashville SC",
    );
    expect(outcomeLabel({ market: "1X2", line: "0.00" }, { selection: "Draw" }, sides)).toBe(
      "Empate",
    );
    expect(outcomeLabel({ market: "OU", line: "2.50" }, { selection: "Under" }, sides)).toBe(
      "Menos de 2,5",
    );
    expect(outcomeLabel({ market: "BTTS", line: "0.00" }, { selection: "No" }, sides)).toBe("No");
  });

  test("a probability is a share of the track, clamped", () => {
    expect(barPercent("0.5234")).toBe(52.3);
    expect(barPercent(0)).toBe(0);
    expect(barPercent(1.4)).toBe(100);
    expect(barPercent(-0.2)).toBe(0);
    expect(barPercent(null)).toBe(0);
    expect(barPercent("not a number")).toBe(0);
  });

  test("an interval is drawn only when both ends were measured and they are in order", () => {
    expect(intervalSpan({ low: "0.4400", high: "0.6000" })).toEqual({ left: 44, right: 60 });
    expect(intervalSpan({ low: null, high: "0.6000" })).toBeNull();
    expect(intervalSpan({ low: "0.4400", high: null })).toBeNull();
    expect(intervalSpan({ low: "0.7000", high: "0.6000" })).toBeNull();
  });

  test("a missing interval is said, not drawn as a point", () => {
    expect(intervalText({ low: null, high: null })).toBe("sin rango medido");
    expect(intervalText({ low: "0.4400", high: "0.6000" })).toMatch(/^entre 44\s% y 60\s%$/);
    const noRange: ForecastMarket = market("BTTS", "0.00", "UNCALIBRATED", "no_champion", [
      outcome("Yes", 0.48, null, null, false),
      outcome("No", 0.52, null, null, true),
    ]);
    const data = forecast([noRange], false);
    const out = render({ status: "success", envelope: envelope(data) }, false);
    expect(out).toContain("sin rango medido");
    expect(out).not.toContain("left:");
  });

  test("a basis this page does not know is blank, a model it does not know is named as it is", () => {
    expect(basisNote("some_future_basis")).toBe("");
    expect(basisNote("champion").length).toBeGreaterThan(10);
    expect(modelLabel("poisson")).toBe("Poisson (Maher)");
    expect(modelLabel("dixon_coles")).toBe("Dixon-Coles");
    expect(modelLabel("elo_ologit")).toBe("Elo (logit ordenado)");
    expect(modelLabel("some_future_model")).toBe("some_future_model");
  });
});

describe("the data the Resumen says it does not have", () => {
  /**
   * Every name `fbi.ai.packet` can put in `missing` (each `missing.append(...)` of the PacketBuilder) is printed by the
   * Resumen in "Datos que aún no tenemos: …"; a name without a label would show its own translation key. `forecast` joined
   * them with packet-v6: a forecast that could not be read says so there instead of passing for "nothing to show";
   * `schedule` with packet-v7 (plan F4): a team calendar that could not be read.
   */
  const PACKET_BLOCKS = [
    "absences",
    "dossier",
    "elo",
    "forecast",
    "form",
    "h2h",
    "lineups",
    "market",
    "models",
    "phase",
    "schedule",
    "standings",
    "stats",
  ];

  test.each(PACKET_BLOCKS)("%s has a label in both languages", (name) => {
    const es = (esMatch.analysis.block as Record<string, string>)[name];
    const en = (enMatch.analysis.block as Record<string, string>)[name];
    expect(es && es.length > 2).toBe(true);
    expect(en && en.length > 2).toBe(true);
  });
});
