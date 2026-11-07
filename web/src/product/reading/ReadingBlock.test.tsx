/// <reference types="bun" />
/**
 * ANÁLISIS PREDIGOL (plan UX, A9): the structured reading with every state shown - a skeleton while it loads, the error with
 * its retry, the owner having turned it off (said), a partial reading without the match's context - and the conclusion's
 * caveat - and the chronicle of A11/UX-025 (a paragraph for each side, the sources). The Resumen's one reading (plan Partidos y
 * Match Center, R2): the chronicle's first stretch, or the structured reading as a short running text - never both.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import type { Envelope } from "@/lib/api/v1/types";
import type { MatchReading } from "@/lib/api/v1/types_reading";
import { ReadingLeadView, ReadingView } from "./ReadingBlock";
import type { ReadingLoad } from "./useReading";

setLocale("es");
afterEach(() => setLocale("es"));

function envelope(
  data: MatchReading | null,
  status: Envelope<null>["status"] = "ok",
): Envelope<MatchReading | null> {
  return {
    status,
    data,
    reason: status === "ok" ? null : "off",
    meta: { generated_at: "2026-10-25T12:00:00Z", api_version: "v1" },
  } as Envelope<MatchReading | null>;
}

const READING: MatchReading = {
  fixture_id: 7,
  version: "reading-v1",
  complete: true,
  data_at: "2026-10-25T10:30:00Z",
  forecast_at: "2026-10-25T09:00:00Z",
  sections: [
    {
      key: "summary",
      facts: [
        { code: "match_intro", params: { competition: "Liga BetPlay" }, ref: "packet:fixture" },
        {
          code: "expected_result",
          params: { outcome: "home", team: "Nacional", probability: 0.48, calibrated: false },
          ref: "forecast:1X2",
        },
      ],
    },
    { key: "market", facts: [{ code: "market_unpriced", params: {}, ref: "packet:market" }] },
    {
      key: "risks",
      facts: [
        { code: "lineups_unconfirmed", params: {}, ref: "packet:lineups" },
        { code: "rumours", params: { count: 2 }, ref: "packet:evidence" },
        { code: "no_external_info", params: {}, ref: "packet:evidence" },
        { code: "a_code_from_the_future", params: {}, ref: "packet:x" },
      ],
    },
    {
      key: "conclusion",
      facts: [
        {
          code: "likely",
          params: {
            market: "1X2",
            outcome: "home",
            team: "Nacional",
            probability: 0.48,
            calibrated: false,
          },
          ref: "forecast:1X2",
        },
      ],
    },
  ],
};

const ok = (data: MatchReading = READING): ReadingLoad => ({
  status: "success",
  envelope: envelope(data),
});

describe("the reading's states", () => {
  test("loading: a skeleton, never a blank", () => {
    const html = renderToStaticMarkup(<ReadingView load={{ status: "pending" }} />);
    expect(html).toContain('aria-busy="true"');
    expect(html).toContain("Análisis PrediGol");
  });

  test("an error: said, with its retry", () => {
    const html = renderToStaticMarkup(
      <ReadingView load={{ status: "error", error: new Error("boom"), retry: () => undefined }} />,
    );
    expect(html).toContain('role="alert"');
  });

  test("the owner turned it off: said, not hidden", () => {
    const html = renderToStaticMarkup(
      <ReadingView load={{ status: "success", envelope: envelope(null, "not_available") }} />,
    );
    expect(html).toContain('data-testid="reading-unavailable"');
    expect(html).toContain("La lectura de este partido no está disponible.");
  });

  test("the sections in order with their sentences, the data's time, the caveat - and an unknown code left out", () => {
    const html = renderToStaticMarkup(<ReadingView load={ok()} />);
    expect(html).toContain("Lectura automática con los datos de PrediGol");
    expect(html).toContain('data-testid="reading-data-at"');
    const order = ["summary", "market", "risks", "conclusion"].map((k) =>
      html.indexOf(`data-testid="reading-section-${k}"`),
    );
    expect(order.every((i) => i >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    expect(html).toContain("Hay 2 rumores sin confirmar: no cuentan como hechos.");
    expect(html).not.toContain("a_code_from_the_future");
    expect(html).toContain('data-testid="reading-caveat"');
    expect(html).not.toContain("La probabilidad implícita es la cuota sin el margen"); // the market had no price
    expect(html).not.toContain('data-testid="reading-partial"');
  });

  test("a match without its context: a partial reading that says so", () => {
    const html = renderToStaticMarkup(
      <ReadingView load={ok({ ...READING, complete: false, data_at: null })} />,
    );
    expect(html).toContain('data-testid="reading-partial"');
  });
});

const NARRATIVE: MatchReading["narrative"] = {
  version: "user-narrative-v3",
  written_at: "2026-10-25T10:40:00Z",
  data_at: "2026-10-25T10:30:00Z",
  es: [
    {
      key: "summary",
      sentences: [{ text: "Partido de la Liga BetPlay en Medellín.", refs: ["P:fixture"] }],
    },
    {
      key: "home",
      sentences: [
        { text: "Nacional viene de ganar 2-1 al Junior.", refs: ["P:results.home.1"] },
        { text: "Según Win Sports, su capitán es baja.", refs: ["E:11"] },
      ],
    },
    {
      key: "away",
      sentences: [{ text: "Millonarios empató 0-0 con el Cali.", refs: ["P:results.away.1"] }],
    },
    {
      key: "risks",
      sentences: [{ text: "Hay un rumor sin confirmar sobre el portero.", refs: ["E:12"] }],
    },
  ],
  en: [
    {
      key: "summary",
      sentences: [{ text: "A Liga BetPlay match in Medellín.", refs: ["P:fixture"] }],
    },
    {
      key: "home",
      sentences: [
        { text: "Nacional come off a 2-1 win over Junior.", refs: ["P:results.home.1"] },
        { text: "According to Win Sports, its captain is out.", refs: ["E:11"] },
      ],
    },
    {
      key: "away",
      sentences: [{ text: "Millonarios drew 0-0 with Cali.", refs: ["P:results.away.1"] }],
    },
    {
      key: "risks",
      sentences: [{ text: "There is an unconfirmed rumour about the goalkeeper.", refs: ["E:12"] }],
    },
  ],
  sources: [{ name: "Win Sports" }, { name: "rumores.example" }],
};
const TEAMS = { home: "Nacional", away: "Millonarios" };

describe("the chronicle (A11, UX-025)", () => {
  test("shown first, labelled as written with AI and checked, with the time of its data", () => {
    const html = renderToStaticMarkup(
      <ReadingView load={ok({ ...READING, narrative: NARRATIVE })} teams={TEAMS} />,
    );
    expect(html).toContain('data-testid="reading-narrative"');
    expect(html).toContain("Redactado con IA y validado contra los datos de PrediGol");
    expect(html).not.toContain("Lectura automática con los datos de PrediGol");
    expect(html).toContain("Escrito con datos de");
    expect(html).toContain("Nacional viene de ganar 2-1 al Junior.");
    expect(html).toContain('data-refs="P:results.home.1"');
    const chronicle = html.slice(
      html.indexOf('data-testid="reading-narrative"'),
      html.indexOf('data-testid="reading-section-market"'),
    );
    expect(chronicle).not.toContain('data-testid="reading-fact"'); // the chronicle is not the facts
  });

  test("a flowing paragraph for each side under its team's name, in order, then the head-to-head and the risks", () => {
    const html = renderToStaticMarkup(
      <ReadingView load={ok({ ...READING, narrative: NARRATIVE })} teams={TEAMS} />,
    );
    const order = ["summary", "home", "away", "risks"].map((k) =>
      html.indexOf(`data-testid="narrative-section-${k}"`),
    );
    expect(order.every((i) => i >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    expect(html).not.toContain('data-testid="narrative-section-h2h"'); // the match had nothing to say there
    expect(html).not.toContain("<details"); // nothing folds: it is read as a text
    const home = html.slice(
      html.indexOf('data-testid="narrative-section-home"'),
      html.indexOf('data-testid="narrative-section-away"'),
    );
    expect(home.match(/<p /g)?.length).toBe(1); // one paragraph, two sentences
    expect(home.match(/data-testid="narrative-sentence"/g)?.length).toBe(2);
    expect(home).toContain(">Nacional</h3>");
    expect(html).toContain(">Millonarios</h3>");
    expect(html).toContain("Qué puede salir mal");
  });

  test("without the teams' names the two sides are still told apart", () => {
    const html = renderToStaticMarkup(
      <ReadingView load={ok({ ...READING, narrative: NARRATIVE })} />,
    );
    expect(html).toContain(">Local</h3>");
    expect(html).toContain(">Visitante</h3>");
  });

  test("the outlets of its news, once, and where the forecast and the market are", () => {
    const html = renderToStaticMarkup(
      <ReadingView load={ok({ ...READING, narrative: NARRATIVE })} teams={TEAMS} />,
    );
    expect(html).toContain("Fuentes: Win Sports, rumores.example.");
    expect(html).toContain('data-testid="narrative-apart"');
    // the forecast and the market keep their own sections, written from the reading's templates, after the chronicle
    const chronicle = html.indexOf('data-testid="reading-narrative"');
    const conclusion = html.indexOf('data-testid="reading-section-conclusion"');
    expect(conclusion).toBeGreaterThan(chronicle);
    expect(html).toContain('data-testid="reading-caveat"');
    const noSources = renderToStaticMarkup(
      <ReadingView load={ok({ ...READING, narrative: { ...NARRATIVE!, sources: [] } })} />,
    );
    expect(noSources).not.toContain('data-testid="narrative-sources"');
  });

  test("in the page's language", () => {
    setLocale("en");
    const html = renderToStaticMarkup(
      <ReadingView load={ok({ ...READING, narrative: NARRATIVE })} teams={TEAMS} />,
    );
    expect(html).toContain("Written with AI and checked against PrediGol&#x27;s data");
    expect(html).toContain("Nacional come off a 2-1 win over Junior.");
    expect(html).toContain("What could go wrong");
    expect(html).toContain("Sources: Win Sports, rumores.example.");
    expect(html).not.toContain("viene de ganar");
  });

  test("without a chronicle - or with null - the facts, as A9 shows them", () => {
    for (const reading of [{ ...READING, narrative: null }, READING]) {
      const html = renderToStaticMarkup(<ReadingView load={ok(reading)} />);
      expect(html).not.toContain('data-testid="reading-narrative"');
      expect(html).toContain("Lectura automática con los datos de PrediGol");
      expect(html).toContain('data-testid="reading-fact"');
    }
  });
});

describe("once the match is over (plan UX, B4)", () => {
  test("the reading ends with the way to the Postpartido - and only then", () => {
    const to = 'data-testid="reading-to-postmatch"';
    expect(
      renderToStaticMarkup(<ReadingView load={ok()} afterMatch={() => undefined} />),
    ).toContain(to);
    expect(renderToStaticMarkup(<ReadingView load={ok()} />)).not.toContain(to);
  });
});

const EXPECTED = READING.sections[0]!.facts[1]!;
const PICK = {
  market: "1X2",
  selection: "Home",
  line: 0,
  home: "Nacional",
  away: "Millonarios",
};
const STREAK = {
  code: "streak_unbeaten",
  params: { team: "Nacional", n: 5 },
  ref: "packet:form",
};
const WITH_DERIVED: MatchReading = {
  ...READING,
  sections: [
    ...READING.sections,
    {
      key: "key_points",
      facts: [
        EXPECTED,
        { code: "value_pick", params: { ...PICK, p_model: 0.52, p_market: 0.45 }, ref: "pick:7" },
        STREAK,
      ],
    },
    {
      key: "value",
      facts: [
        { code: "value_pick", params: { ...PICK, p_model: 0.52, p_market: 0.45 }, ref: "pick:7" },
        {
          code: "value_price",
          params: { ...PICK, odds: 2.31, fair_market: 2.21, fair_model: 1.91, taken: false },
          ref: "pick:7",
        },
      ],
    },
    { key: "factors", facts: [STREAK] },
  ],
};

describe("the derived sections (UX-011)", () => {
  test("the full analysis is the six sections: the derived ones repeat them and are read in the Resumen", () => {
    for (const reading of [WITH_DERIVED, { ...WITH_DERIVED, narrative: NARRATIVE }]) {
      const html = renderToStaticMarkup(<ReadingView load={ok(reading)} />);
      for (const key of ["key_points", "value", "factors"])
        expect(html).not.toContain(`reading-section-${key}`);
      expect(html).not.toContain("Puntos clave");
      expect(html).not.toContain("Por qué hay valor");
    }
    const html = renderToStaticMarkup(<ReadingView load={ok(WITH_DERIVED)} />);
    expect(html).toContain('data-testid="reading-section-conclusion"');
    expect(html).not.toContain("PrediGol le da 52 %");
  });
});

const plain = (html: string) => html.replace(/[\u00a0\u202f]/g, " ");
const times = (html: string, needle: string) => html.split(needle).length - 1;

const ARRIVING: MatchReading = {
  ...WITH_DERIVED,
  sections: [
    ...WITH_DERIVED.sections.filter((s) => s.key !== "key_points" && s.key !== "conclusion"),
    {
      key: "conclusion",
      facts: [
        ...READING.sections.find((s) => s.key === "conclusion")!.facts,
        {
          code: "likely",
          params: {
            market: "OU",
            outcome: "over",
            line: "2.5",
            probability: 0.57,
            calibrated: true,
          },
          ref: "forecast:OU",
        },
      ],
    },
    {
      key: "context",
      facts: [
        {
          code: "stakes_pressure",
          params: { side: "home", team: "Nacional", pressure: "title" },
          ref: "packet:stakes.home",
        },
        {
          code: "rest_days",
          params: { side: "home", team: "Nacional", days: 4, matches_14d: 3 },
          ref: "packet:schedule.home",
        },
      ],
    },
    {
      key: "data",
      facts: [
        STREAK,
        {
          code: "key_absences",
          params: { side: "away", team: "Millonarios", count: 2, players: ["Castro", "Pérez"] },
          ref: "packet:absences.away",
        },
      ],
    },
    {
      key: "key_points",
      facts: [
        EXPECTED,
        { code: "value_pick", params: { ...PICK, p_model: 0.52, p_market: 0.45 }, ref: "pick:7" },
        STREAK,
        {
          code: "key_absences",
          params: { side: "away", team: "Millonarios", count: 2, players: ["Castro", "Pérez"] },
          ref: "packet:absences.away",
        },
      ],
    },
  ],
};

describe("the Resumen's one reading (plan Partidos y Match Center, R2)", () => {
  test("the structured reading as short paragraphs, in the order it is read, each sentence once", () => {
    const html = plain(renderToStaticMarkup(<ReadingLeadView load={ok(ARRIVING)} />));
    const keys = [...html.matchAll(/data-testid="reading-lead-([a-z]+)"/g)].map((m) => m[1]);
    expect(keys).toEqual(["summary", "arrival", "news", "risks", "conclusion"]);
    // the result PrediGol expects is said once: the conclusion keeps only what the summary did not say
    const conclusion = html.slice(html.indexOf('data-testid="reading-lead-conclusion"'));
    const refs = [
      ...conclusion.matchAll(/data-testid="reading-fact" data-code="[a-z_]+" data-ref="([^"]+)"/g),
    ].map((m) => m[1]);
    expect(refs).toEqual(["forecast:OU"]);
    // running text: paragraphs, never section headings nor lists
    expect(html).not.toContain("<h3");
    expect(html).not.toContain("<li");
    expect(html).not.toContain("Puntos clave");
    expect(html).toContain("Partido de Liga BetPlay.");
    expect(times(html, "PrediGol ve como resultado más probable la victoria de Nacional")).toBe(1);
    expect(times(html, "Nacional suma 5 partidos sin perder.")).toBe(1);
    // the key absences are the news, said once
    const news = html.slice(html.indexOf('data-testid="reading-lead-news"'));
    expect(news).toContain('data-code="key_absences"');
    expect(times(html, 'data-code="key_absences"')).toBe(1);
    // what the calendar says is Profundizar's
    expect(html).not.toContain('data-code="rest_days"');
    // the pick's own sentences belong to its card under the reading
    expect(html).not.toContain('data-code="value_pick"');
    expect(html).not.toContain('data-code="value_price"');
    expect(html).toContain('data-testid="reading-caveat"');
    expect(html).toContain('data-testid="reading-data-at"');
    expect(html).toContain("Lectura automática con los datos de PrediGol");
  });

  test("«Qué puede salir mal» with the two main risks, inside the text", () => {
    const html = plain(renderToStaticMarkup(<ReadingLeadView load={ok()} />));
    const risks = html.slice(html.indexOf('data-testid="reading-lead-risks"'));
    expect(risks).toContain("Qué puede salir mal:");
    expect(risks).toContain("Las alineaciones aún no están confirmadas.");
    expect(risks).toContain("Hay 2 rumores sin confirmar");
    expect(html).not.toContain("No encontramos información externa"); // only the first two
  });

  test("without a conclusion (or one that only repeats the summary), no conclusion and no caveat", () => {
    const noConclusion: MatchReading = {
      ...READING,
      sections: READING.sections.filter((s) => s.key !== "conclusion"),
    };
    expect(renderToStaticMarkup(<ReadingLeadView load={ok()} />)).not.toContain(
      'data-testid="reading-lead-conclusion"',
    );
    const html = renderToStaticMarkup(<ReadingLeadView load={ok(noConclusion)} />);
    expect(html).not.toContain('data-testid="reading-lead-conclusion"');
    expect(html).not.toContain('data-testid="reading-caveat"');
  });

  test("with a chronicle: its first stretch and the time of its data - never the facts as well", () => {
    const html = renderToStaticMarkup(
      <ReadingLeadView load={ok({ ...ARRIVING, narrative: NARRATIVE })} />,
    );
    expect(html).toContain('data-kind="narrative"');
    expect(html).toContain('data-testid="reading-narrative-lead" data-section="summary"');
    expect(html).toContain("Partido de la Liga BetPlay en Medellín.");
    expect(html).toContain("Escrito con datos de");
    expect(html).toContain("Redactado con IA y validado contra los datos de PrediGol");
    // only the first stretch: the sides' paragraphs and the risks are read in Análisis
    expect(html).not.toContain("Nacional viene de ganar 2-1 al Junior.");
    expect(html).not.toContain("Hay un rumor sin confirmar sobre el portero.");
    expect(html).not.toContain('data-testid="reading-fact"');
    expect(html).not.toContain("Lectura automática con los datos de PrediGol");
  });

  test("a chronicle without a lead starts at its first section; in the page's language", () => {
    const narrative = { ...NARRATIVE!, es: NARRATIVE!.es.slice(1), en: NARRATIVE!.en.slice(1) };
    const html = renderToStaticMarkup(<ReadingLeadView load={ok({ ...READING, narrative })} />);
    expect(html).toContain('data-section="home"');
    expect(html).toContain("Nacional viene de ganar 2-1 al Junior.");
    setLocale("en");
    const en = renderToStaticMarkup(
      <ReadingLeadView load={ok({ ...READING, narrative: NARRATIVE })} />,
    );
    expect(en).toContain("A Liga BetPlay match in Medellín.");
    expect(en).not.toContain("Partido de la Liga BetPlay en Medellín.");
  });

  test("without a chronicle - or with null - the facts", () => {
    for (const reading of [{ ...READING, narrative: null }, READING]) {
      const html = renderToStaticMarkup(<ReadingLeadView load={ok(reading)} />);
      expect(html).toContain('data-kind="facts"');
      expect(html).toContain('data-testid="reading-fact"');
      expect(html).not.toContain("reading-narrative-lead");
    }
  });

  test("its states: a skeleton, an error with its retry, the owner having turned it off (said), a partial reading", () => {
    expect(renderToStaticMarkup(<ReadingLeadView load={{ status: "pending" }} />)).toContain(
      'aria-busy="true"',
    );
    const error = renderToStaticMarkup(
      <ReadingLeadView load={{ status: "error", error: new Error("x"), retry: () => undefined }} />,
    );
    expect(error).toContain('data-kind="error"');
    const off = renderToStaticMarkup(
      <ReadingLeadView load={{ status: "success", envelope: envelope(null, "not_available") }} />,
    );
    expect(off).toContain("La lectura de este partido no está disponible.");
    const partial = renderToStaticMarkup(
      <ReadingLeadView load={ok({ ...READING, complete: false })} />,
    );
    expect(partial).toContain('data-testid="reading-partial"');
  });

  test("in English", () => {
    setLocale("en");
    const html = plain(renderToStaticMarkup(<ReadingLeadView load={ok(ARRIVING)} />));
    expect(html).toContain("What could go wrong:");
    expect(html).toContain("An automatic reading of PrediGol&#x27;s data");
    expect(html).not.toContain("Qué puede salir mal");
  });
});
