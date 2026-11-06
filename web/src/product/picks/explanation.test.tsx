/// <reference types="bun" />
/**
 * «¿Por qué PrediGol eligió este pick?» (plan UX, B3): the five layers written from the API's values with the reader's templates,
 * the conclusion first and open, the state in words with its reason, a pick of the day's state when it was chosen, the review
 * only while it is applied, and the notice «no garantiza · +18» closing every explanation.
 */
import { afterAll, describe, expect, test } from "bun:test";
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import type { PickExplanation } from "@/lib/api/v1/types_explanation";
import { setLocale } from "@/lib/i18n";
import {
  HOW_STEPS,
  LAYERS,
  conclusionText,
  contextEmptyText,
  contextLines,
  dayText,
  howText,
  marketLines,
  riskLines,
} from "./explanation";
import { PickExplanationView, WhyPickButton } from "./WhyPick";

function explanation(over: Partial<PickExplanation> = {}): PickExplanation {
  return {
    pick_id: 41,
    version: "pick-explanation-v1",
    match: {
      fixture_id: 7,
      kickoff_at: "2031-06-16T15:00:00Z",
      status_group: "scheduled",
      competition: {
        id: 1,
        name: "Liga BetPlay",
        country: "Colombia",
        logo_url: null,
        flag_url: null,
      },
      home: { id: 10, name: "Millonarios", logo_url: null },
      away: { id: 11, name: "Santa Fe", logo_url: null },
      score_home: null,
      score_away: null,
      status_short: "NS",
      phase: "scheduled",
    },
    market_key: "1X2",
    selection: "Home",
    line: "0",
    started: false,
    user_status: "RECOMMENDED",
    status_reason: "value",
    context_pending: true,
    day: null,
    reading_shown: true,
    reading_complete: true,
    reading_at: "2031-06-16T11:50:00Z",
    context: [
      {
        code: "form",
        params: {
          side: "home",
          team: "Millonarios",
          n: 5,
          sequence: "WWDLW",
          ppg: 2.0,
          goals_for: 1.8,
          goals_against: 0.6,
        },
        ref: "packet:form.home",
      },
    ],
    narrative: null,
    market: {
      p_model: "0.5000",
      p_low: "0.4500",
      p_high: "0.5500",
      p_market: "0.4300",
      published_odds: "2.300",
      published_bookmaker: "Betplay",
      published_at: "2031-06-15T12:05:00Z",
      odds_now: "2.250",
      bookmaker_now: "Wplay",
      price_at: "2031-06-16T11:30:00Z",
      value_now: true,
    },
    risks: [{ code: "lineups_unconfirmed", params: {}, ref: "packet:lineups" }],
    review: null,
    ...over,
  };
}

const view = (e: PickExplanation) => renderToStaticMarkup(<PickExplanationView e={e} />);

/** Layer 5's link to Transparencia is a router link: rendered inside a router. */
async function inRouter(node: ReactNode): Promise<string> {
  const router = createRouter({
    routeTree: createRootRoute({ component: () => node }),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  await router.load();
  return renderToStaticMarkup(<RouterProvider router={router} />);
}

/** Intl writes «50 %» with a no-break space: compared as plain spaces. */
const plain = (s: string) => s.replace(/[\u00a0\u202f]/g, " ");

afterAll(() => setLocale("es"));

describe("the five layers' lines", () => {
  test("the conclusion is one sentence over PrediGol's probability and the market's", () => {
    setLocale("es");
    expect(plain(conclusionText(explanation()))).toBe(
      "PrediGol espera «Gana Millonarios»: le da un 50 % de probabilidad; el mercado, sin su margen, un 43 %.",
    );
    const alone = explanation({ market: { ...explanation().market, p_market: null } });
    expect(plain(conclusionText(alone))).toBe(
      "PrediGol espera «Gana Millonarios»: le da un 50 % de probabilidad.",
    );
    setLocale("en");
    expect(conclusionText(explanation())).toContain("PrediGol expects «");
  });

  test("the context is the chronicle when there is one, otherwise the reading's facts, and says why it is empty", () => {
    setLocale("es");
    expect(contextLines(explanation())).toEqual([
      "Millonarios: GGEPG en sus últimos 5 partidos (2,00 puntos por partido; 1,8 goles a favor y 0,6 en contra por partido).",
    ]);
    const narrated = explanation({
      narrative: {
        version: "user-narrative-v2",
        written_at: "2031-06-16T11:55:00Z",
        data_at: "2031-06-16T11:50:00Z",
        es: [
          {
            key: "summary",
            sentences: [{ text: "Partido de la jornada 9.", refs: ["P:fixture"] }],
          },
          {
            key: "home",
            sentences: [{ text: "Millonarios llega cuarto.", refs: ["P:stakes.home"] }],
          },
          {
            key: "away",
            sentences: [{ text: "Nacional lleva tres sin ganar.", refs: ["P:streak.away"] }],
          },
          {
            key: "risks",
            sentences: [{ text: "Hay un rumor sin confirmar.", refs: ["E:3"] }],
          },
        ],
        en: [
          {
            key: "home",
            sentences: [{ text: "Millonarios are fourth.", refs: ["P:stakes.home"] }],
          },
        ],
        sources: [],
      },
    });
    expect(contextLines(narrated)).toEqual([
      "Millonarios llega cuarto.",
      "Nacional lleva tres sin ganar.",
    ]);
    expect(riskLines(narrated)).toContain("Hay un rumor sin confirmar.");
    setLocale("en");
    expect(contextLines(narrated)).toEqual(["Millonarios are fourth."]);
    setLocale("es");
    expect(contextEmptyText(explanation({ context: [], reading_shown: false }))).toBe(
      "La lectura del partido no está disponible ahora.",
    );
    expect(contextEmptyText(explanation({ context: [], reading_complete: false }))).toBe(
      "PrediGol todavía no ha reunido el contexto de este partido.",
    );
  });

  test("the market: the published price, the best price now and whether it still has value", () => {
    setLocale("es");
    const lines = marketLines(explanation());
    expect(lines[0]).toStartWith("Se publicó a 2,30 (Betplay), el ");
    expect(lines[1]).toBe("Mejor cuota ahora: 2,25 (Wplay).");
    expect(lines[2]).toBe(
      "Con la mejor cuota de ahora sigue pagando más de lo que dice su probabilidad.",
    );
    const gone = marketLines(
      explanation({ market: { ...explanation().market, value_now: false, odds_now: null } }),
    );
    expect(gone.slice(1)).toEqual([
      "Ahora no hay una cuota reciente de varias casas.",
      "Con la mejor cuota de ahora ya no paga más de lo que dice su probabilidad.",
    ]);
    const started = marketLines(
      explanation({
        started: true,
        market: { ...explanation().market, odds_now: null, value_now: null },
      }),
    );
    expect(started).toHaveLength(2);
    expect(started[1]).toBe(
      "El partido ya empezó: no se vuelve a calcular con las cuotas de ahora.",
    );
  });

  test("the risks: how often it fails, the model's doubt, then the reading's", () => {
    setLocale("es");
    const lines = riskLines(explanation());
    expect(lines[0]).toBe("Aun así, esta selección falla aproximadamente 5 de cada 10 veces");
    expect(plain(lines[1] ?? "")).toBe("El modelo duda: la sitúa entre el 45 % y el 55 %.");
    expect(lines.length).toBe(3);
    const noInterval = riskLines(explanation({ market: { ...explanation().market, p_low: null } }));
    expect(noInterval.some((l) => l.startsWith("El modelo duda"))).toBe(false);
  });

  test("how it was decided says what this pick passed - never more", () => {
    setLocale("es");
    expect(howText(explanation())).toStartWith(
      "Cumple la regla de valor con la mejor cuota de ahora.",
    );
    expect(howText(explanation({ market: { ...explanation().market, value_now: false } }))).toBe(
      "Pasó la regla de valor cuando se tomó; con la mejor cuota de ahora ya no la pasa.",
    );
    expect(howText(explanation({ started: true }))).toStartWith(
      "Cumplía la regla de valor cuando se tomó.",
    );
    const day = {
      day: "2031-06-16",
      rank: 2,
      stage: "T-6h" as const,
      selected_at: "2031-06-16T09:00:00Z",
      odds: "2.200",
      bookmaker: "Betplay",
      user_status: "CAUTION" as const,
      status_reason: "downgraded" as const,
      context_pending: false,
    };
    expect(howText(explanation({ day }))).toBe("Es el pick del día n.º 2: pasó todos estos pasos.");
    expect(dayText(explanation({ day }))).toStartWith("Pick del día n.º 2, elegido a las ");
    const evaluation = explanation({
      user_status: "EVALUATION",
      status_reason: "evaluation",
      context_pending: false,
      day: { ...day, user_status: "EVALUATION", status_reason: "evaluation" },
    });
    expect(howText(evaluation)).toStartWith("Su modelo todavía no ha superado al mercado");
    expect(dayText(evaluation)).toStartWith("En la selección de evaluación del día");
    expect(HOW_STEPS).toEqual(["model", "value", "risk", "context", "one"]);
  });
});

describe("the explanation's sheet", () => {
  test("the state in words, the conclusion first and open, the other layers folded in order, the notice last", () => {
    setLocale("es");
    const html = view(explanation());
    expect(html).toContain('data-testid="why-status"');
    expect(html).toContain("Recomendado");
    expect(html).toContain("Revisión de contexto aún no aplicada");
    expect(html).toContain(
      "La revisión de contexto de PrediGol Intelligence todavía no se aplica a los picks.",
    );
    const order = LAYERS.map((l) => html.indexOf(`data-testid="why-layer-${l}"`));
    expect(order.every((i) => i >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    expect(html).not.toMatch(/<details[^>]*open=""[^>]*data-testid="why-layer-context"/);
    expect(html).toContain('data-testid="disclaimer"');
    expect(html.indexOf('data-testid="disclaimer"')).toBeGreaterThan(order[order.length - 1] ?? 0);
    expect(html).not.toContain('data-testid="why-review"');
    expect(html).not.toContain('data-testid="why-how-more"');
  });

  test("layer 5 links to «Cómo se decide» in Transparencia only when that page is open to the reader", async () => {
    setLocale("es");
    const open = await inRouter(<PickExplanationView e={explanation()} transparency />);
    const link = /<a [^>]*data-testid="why-how-more"[^>]*>/.exec(open)?.[0] ?? "";
    expect(link).toContain('href="/transparency#how"');
    const closed = await inRouter(<PickExplanationView e={explanation()} transparency={false} />);
    expect(closed).not.toContain('data-testid="why-how-more"');
  });

  test("a pick of the day shows its state when it was chosen when it differs, and the review only while applied", () => {
    setLocale("es");
    const day = {
      day: "2031-06-16",
      rank: 1,
      stage: "T-6h" as const,
      selected_at: "2031-06-16T09:00:00Z",
      odds: "2.200",
      bookmaker: "Betplay",
      user_status: "CAUTION" as const,
      status_reason: "downgraded" as const,
      context_pending: false,
    };
    const html = view(
      explanation({
        day,
        user_status: "NOT_RECOMMENDED",
        status_reason: "rejected",
        context_pending: false,
        review: { decision: "REJECT", positives: [], risks: ["Baja clave confirmada"] },
      }),
    );
    expect(html).toContain('data-testid="why-day"');
    expect(html).toContain('data-testid="why-day-status"');
    expect(html).toContain("Cautela");
    expect(html).toContain("No recomendado");
    expect(html).toContain('data-testid="why-review"');
    expect(html).toContain("Baja clave confirmada");
    const same = view(
      explanation({ day: { ...day, user_status: "RECOMMENDED", context_pending: true } }),
    );
    expect(same).not.toContain('data-testid="why-day-status"');
  });

  test("the button is the sheet's own trigger: it says it opens a dialog and asks nothing until it does", () => {
    setLocale("es");
    const html = renderToStaticMarkup(<WhyPickButton pickId={41} testId="why-pick" />);
    expect(html).toMatch(/<button[^>]*aria-haspopup="dialog"/);
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain('data-testid="why-pick"');
    expect(html).not.toContain('data-testid="why-sheet"');
  });

  test("English", () => {
    setLocale("en");
    const html = view(explanation());
    expect(html).toContain("Recommended");
    expect(html).toContain("Context review not applied yet");
    expect(html).toContain("How we decided");
  });
});
