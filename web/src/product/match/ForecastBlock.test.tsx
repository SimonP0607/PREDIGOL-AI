/// <reference types="bun" />
/**
 * Plan F5, PRONÓSTICO PREDIGOL in the Resumen: a probability and the interval around it, "Sin calibrar" wherever no
 * champion calibrator exists, no price anywhere for a user, and nothing at all for a user until the owner decides.
 * The Admin Console's preview alone sees the fair odds and, folded away, the value and the picks of the match.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import enMatch from "@/locales/en/match.json";
import esMatch from "@/locales/es/match.json";
import type { Envelope } from "@/lib/api/v1/types";
import type {
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
  forecastScreen,
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
    // forecast ≠ value ≠ pick (plan UX, A3): the three questions under the forecast, each word opening its definition
    expect(out).toContain('data-testid="explain-layers"');
    expect(out).toContain("¿Está bien pagado?");
    expect(out).toContain('data-glossary="calibrated"');
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
    expect(out).not.toContain("cuota según PrediGol");
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
    expect(seen).not.toContain("cuota según PrediGol");
    expect(seen).not.toContain("1,92");
    expect(seen).not.toContain("forecast-admin");
    expect(seen).not.toContain("RECHAZADO");
    expect(seen).not.toContain("shadow");
  });
});

describe("a reader sees it load and fail; only the owner's switch hides it (plan UX, A9)", () => {
  test("the API says not available (the owner turned the forecast off for readers)", () => {
    const load: ForecastLoad = {
      status: "success",
      envelope: envelope(null, "not_available"),
    };
    expect(render(load, false)).toBe("");
  });

  test("while it loads a skeleton, and when it cannot be loaded the error with its retry: never a silent gap", () => {
    expect(render({ status: "pending" }, false)).toContain("animate-pulse");
    const failed = render({ status: "error", error: new Error("boom") }, false);
    expect(failed).not.toBe("");
    expect(failed).toContain('role="alert"');
  });

  test("the screen is decided apart from React", () => {
    expect(forecastScreen({ status: "pending" }, false).kind).toBe("loading");
    expect(forecastScreen({ status: "pending" }, true).kind).toBe("loading");
    expect(forecastScreen({ status: "error", error: 1 }, false).kind).toBe("error");
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

  test("shows PrediGol's odds beside each number, and the model's own number where it was corrected", () => {
    expect(out).toContain("cuota según PrediGol 1,92"); // the model's 1/p (plan UX, A3: «cuota justa» is the market's)
    expect(out).toContain("cuota según PrediGol 3,85");
    expect(out.match(/cuota según PrediGol/g)?.length).toBe(7);
    expect(out).not.toContain("cuota justa");
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
    expect(out).toMatch(/\+2,0 p\. p\./);
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
