/// <reference types="bun" />
/**
 * Postpartido (plan UX, B4): the forecast set against the result in three markets, how each published pick ended and why - the
 * match's facts worded from their codes and figures, each for the selection or against it, never a judgement - what the reader
 * saved with its settlement, and the news published once the match had started.
 */
import { afterAll, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import type { ForecastMarket } from "@/lib/api/v1/types_forecast";
import type { NewsItem } from "@/lib/api/v1/types_news";
import type { PostmatchCause, PostmatchPick } from "@/lib/api/v1/types_postmatch";
import type { UserPick } from "@/lib/api/v1/types_records";
import {
  causeLines,
  causeText,
  causesEmptyText,
  chancesText,
  forecastMarkets,
  forecastVsResult,
  newsAfterKickoff,
  outcomeText,
  resultSelectionFor,
} from "./postmatch";
import { PublishedWhy, SavedOutcome } from "./PostmatchTab";

const SIDES = { home: "Millonarios", away: "Santa Fe" };
/** Intl writes «55 %» with a no-break space: compared as plain spaces. */
const plain = (s: string) => s.replace(/[\u00a0\u202f]/g, " ");

afterAll(() => setLocale("es"));

function cause(over: Partial<PostmatchCause>): PostmatchCause {
  return {
    code: "red_card",
    effect: "neutral",
    minute: null,
    side: null,
    n: null,
    cards: null,
    referee_avg: null,
    xg_home: null,
    xg_away: null,
    score: null,
    ...over,
  };
}

function pick(over: Partial<PostmatchPick> = {}): PostmatchPick {
  return {
    pick_id: 41,
    market_key: "1X2",
    selection: "Home",
    line: "0",
    status: "qualified",
    result: "win",
    p_model: "0.5500",
    p_close: "0.5200",
    analysed: true,
    analysed_at: "2031-06-17T07:50:00Z",
    causes: [],
    ...over,
  };
}

function market(key: string, line: string, likely: string, probability: string): ForecastMarket {
  return {
    market: key,
    line,
    family: key,
    model: null,
    calibration: "CALIBRATED",
    basis: "champion",
    known_at: "2031-06-16T12:00:00Z",
    data_cutoff_at: "2031-06-16T11:00:00Z",
    outcomes: [{ selection: likely, probability, low: null, high: null, likely: true }],
  };
}

describe("the forecast against the result", () => {
  test("each market reads the score its own way; a score on a whole line says nothing", () => {
    const s = { home: 2, away: 1 };
    expect(resultSelectionFor({ market: "1X2", line: "0" }, s)).toBe("Home");
    expect(resultSelectionFor({ market: "OU", line: "2.5" }, s)).toBe("Over");
    expect(resultSelectionFor({ market: "OU", line: "3" }, s)).toBeNull();
    expect(resultSelectionFor({ market: "BTTS", line: "0" }, s)).toBe("Yes");
    expect(resultSelectionFor({ market: "BTTS", line: "0" }, { home: 1, away: 0 })).toBe("No");
    expect(resultSelectionFor({ market: "AH", line: "-0.5" }, s)).toBeNull();
  });

  test("the result, the goals at 2.5 and both teams to score, in that order", () => {
    const markets = [
      market("BTTS", "0", "No", "0.5600"),
      market("OU", "1.5", "Over", "0.7000"),
      market("OU", "2.5", "Under", "0.5400"),
      market("1X2", "0", "Home", "0.4800"),
    ];
    expect(forecastMarkets(markets).map((m) => `${m.market} ${m.line}`)).toEqual([
      "1X2 0",
      "OU 2.5",
      "BTTS 0",
    ]);
  });

  test("a line per market: what PrediGol saw likeliest, the score and whether it matched", () => {
    setLocale("es");
    const over = forecastVsResult(
      market("OU", "2.5", "Under", "0.5400"),
      { home: 2, away: 1 },
      SIDES,
    );
    expect(over?.hit).toBe(false);
    expect(plain(over?.line ?? "")).toBe(
      "PrediGol veía más probable «Menos de 2,5» (54 %). Terminó 2-1: Más de 2,5.",
    );
    const both = forecastVsResult(
      market("BTTS", "0", "Yes", "0.5800"),
      { home: 2, away: 1 },
      SIDES,
    );
    expect(both?.hit).toBe(true);
    expect(
      forecastVsResult(market("OU", "3", "Over", "0.5"), { home: 2, away: 1 }, SIDES),
    ).toBeNull();
  });
});

describe("why a published pick ended as it did", () => {
  test("how it ended; a loss says how often a selection like it fails; the chances it had", () => {
    setLocale("es");
    expect(outcomeText(pick())).toBe("Ganó.");
    expect(outcomeText(pick({ result: "loss" }))).toBe(
      "Perdió. Una selección así falla aproximadamente 5 de cada 10 veces.",
    );
    expect(outcomeText(pick({ result: "push" }))).toBe(
      "Se devolvió: el resultado cayó exactamente en la línea.",
    );
    expect(outcomeText(pick({ result: null }))).toBe("Esperando el resultado oficial.");
    expect(plain(chancesText(pick()))).toBe(
      "PrediGol le daba un 55 % de probabilidad; al cierre, el mercado sin su margen, un 52 %.",
    );
    expect(plain(chancesText(pick({ p_close: null })))).toBe(
      "PrediGol le daba un 55 % de probabilidad.",
    );
    setLocale("en");
    expect(outcomeText(pick({ result: "void" }))).toBe("Void: it counts as neither won nor lost.");
  });

  test("each fact of the match in words: whose, when, how much", () => {
    setLocale("es");
    expect(causeText(cause({ code: "red_card", side: "away", minute: 60 }), SIDES)).toBe(
      "Expulsión en Santa Fe, en el minuto 60.",
    );
    expect(causeText(cause({ code: "penalty_scored", side: "home", minute: 70 }), SIDES)).toBe(
      "Penalti convertido por Millonarios, en el minuto 70.",
    );
    expect(causeText(cause({ code: "early_goal", side: "home", minute: 9 }), SIDES)).toBe(
      "Gol de Millonarios en el minuto 9: el partido cambió pronto.",
    );
    expect(causeText(cause({ code: "early_substitution", n: 2 }), SIDES)).toBe(
      "2 cambios antes del minuto 30 (posible lesión).",
    );
    expect(causeText(cause({ code: "early_substitution", n: 1 }), SIDES)).toBe(
      "Un cambio antes del minuto 30 (posible lesión).",
    );
    expect(
      causeText(cause({ code: "cards_above_referee", cards: 9, referee_avg: 4.1 }), SIDES),
    ).toBe("9 tarjetas, muy por encima de las 4,1 que este árbitro saca de media.");
    expect(
      causeText(cause({ code: "xg_against", xg_home: 0.71, xg_away: 1.9, score: "1-0" }), SIDES),
    ).toBe(
      "Las ocasiones no respaldaban esta selección: goles esperados Millonarios 0,71 – 1,90 Santa Fe.",
    );
    expect(causeText(cause({ code: "red_card", side: null, minute: 60 }), SIDES)).toBe("");
    expect(causeText(cause({ code: "xg_supported" }), SIDES)).toBe("");
    setLocale("en");
    expect(causeText(cause({ code: "penalty_missed", side: "away", minute: 81 }), SIDES)).toBe(
      "Penalty missed by Santa Fe, in minute 81.",
    );
  });

  test("the facts it can word, each for or against; when there are none, why", () => {
    setLocale("es");
    const p = pick({
      causes: [
        cause({ code: "red_card", side: "away", minute: 60, effect: "for" }),
        cause({ code: "xg_supported", effect: "for" }), // no figures: nothing to say
        cause({ code: "early_goal", side: "away", minute: 5, effect: "against" }),
      ],
    });
    expect(causeLines(p, SIDES).map((l) => l.effect)).toEqual(["for", "against"]);
    expect(causesEmptyText(pick())).toBe(
      "No pasó nada fuera de lo normal en el partido que lo explique.",
    );
    expect(causesEmptyText(pick({ analysed: false }))).toBe(
      "El análisis del partido todavía no está: se escribe la noche siguiente.",
    );
    expect(causesEmptyText(pick({ result: null, analysed: false }))).toBeNull();
  });

  test("under the card: the title, the sentence and each fact with its side", () => {
    setLocale("es");
    const html = renderToStaticMarkup(
      <PublishedWhy
        pick={pick({
          result: "loss",
          causes: [cause({ code: "penalty_scored", side: "away", minute: 70, effect: "against" })],
        })}
        sides={SIDES}
      />,
    );
    expect(html).toContain('data-result="loss"');
    expect(html).toContain("Por qué terminó así");
    expect(html).toContain("Perdió. Una selección así falla aproximadamente 5 de cada 10 veces.");
    expect(html).toContain('data-effect="against"');
    expect(html).toContain("En contra");
    expect(html).toContain("Penalti convertido por Santa Fe, en el minuto 70.");
    const quiet = renderToStaticMarkup(<PublishedWhy pick={pick()} sides={SIDES} />);
    expect(quiet).toContain('data-testid="postmatch-why-empty"');
  });
});

describe("what the reader saved", () => {
  const saved: UserPick = {
    id: 3,
    match: {
      fixture_id: 7,
      kickoff_at: "2031-06-16T15:00:00Z",
      status_group: "finished",
      competition: {
        id: 1,
        name: "Liga BetPlay",
        country: "Colombia",
        logo_url: null,
        flag_url: null,
      },
      home: { id: 10, name: "Millonarios", logo_url: null },
      away: { id: 11, name: "Santa Fe", logo_url: null },
      score_home: 2,
      score_away: 1,
      status_short: "FT",
      phase: "finished",
    },
    market_key: "OU",
    selection: "Over",
    line: "2.5",
    origin: "market",
    pick_id: null,
    odds: "1.950",
    bookmaker: "Betplay",
    price_at: "2031-06-16T12:00:00Z",
    user_odds: null,
    saved_at: "2031-06-16T12:01:00Z",
    status: "WIN",
    profit_units: "0.9500",
    settled_at: "2031-06-16T17:10:00Z",
    snapshot: {},
  } as UserPick;

  test("how it ended, at what price and its units; a pending one says it waits", () => {
    setLocale("es");
    const html = renderToStaticMarkup(
      <ul>
        <SavedOutcome pick={saved} sides={SIDES} />
      </ul>,
    );
    expect(html).toContain('data-status="WIN"');
    expect(html).toContain("a 1,95");
    expect(html).toContain("+0,95");
    const mine = renderToStaticMarkup(
      <ul>
        <SavedOutcome
          pick={{
            ...saved,
            user_odds: "2.050",
            status: "PENDING",
            profit_units: null,
            settled_at: null,
          }}
          sides={SIDES}
        />
      </ul>,
    );
    expect(mine).toContain("a tu cuota de 2,05");
    expect(mine).toContain("Se liquida en cuanto el resultado sea oficial.");
  });
});

describe("the news after kick-off", () => {
  const item = (published_at: string | null, published_day_only = false) =>
    ({ id: published_at ?? "none", published_at, published_day_only }) as NewsItem;

  test("only an exact time after the kick-off; a day-only date or none stays in Noticias", () => {
    const after = newsAfterKickoff(
      [
        item("2031-06-16T17:30:00Z"),
        item("2031-06-16T14:59:00Z"),
        item("2031-06-16T17:30:00Z", true),
        item(null),
      ],
      "2031-06-16T15:00:00Z",
    );
    expect(after.map((n) => n.published_at)).toEqual(["2031-06-16T17:30:00Z"]);
    expect(newsAfterKickoff([item("2031-06-16T17:30:00Z")], "not a date")).toEqual([]);
  });
});
