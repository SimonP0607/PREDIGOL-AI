/// <reference types="bun" />
/**
 * IA-019: the owner's diagnosis of a match's news in «Avanzado / Auditoría» - the verdict the server decided, in plain words and
 * Bogotá times, and the panel drawn from an answer of the API.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import type { DiagnosisVerdict, NewsDiagnosis } from "@/lib/api/v1/types_news";
import { NewsDiagnosisView } from "./NewsDiagnosisPanel";
import {
  evidenceText,
  exaText,
  nextPassText,
  passWebText,
  searchesText,
  verdictText,
  whenText,
} from "./newsDiagnosis";

setLocale("es");
afterEach(() => setLocale("es"));

// 8 Nov 2026, 12:00 in Bogotá (17:00 UTC); the match at 16:00 Bogotá.
const NOW = Date.parse("2026-11-08T17:00:00Z");
const KICKOFF = "2026-11-08T21:00:00Z";

function diagnosis(over: Partial<NewsDiagnosis> = {}): NewsDiagnosis {
  return {
    as_of: "2026-11-08T17:00:00Z",
    match: {
      fixture_id: 77,
      kickoff_at: KICKOFF,
      status_group: "scheduled",
      home: "Valencia",
      away: "Real Madrid",
      competition: "La Liga",
      provider_league_id: 140,
      priority_group: 1,
      tracked: true,
    },
    coverage: { covered: true, switch_on: true, groups: [1, 2, 3] },
    day: {
      day: "2026-11-08",
      opens_at: "2026-11-08T05:05:00Z",
      opened: true,
      has_market: true,
      odds_at: "2026-11-08T16:30:00Z",
    },
    passes: [
      {
        kind: "first",
        day: "2026-11-08",
        started_at: "2026-11-08T05:08:00Z",
        finished_at: "2026-11-08T05:10:00Z",
        status: "ok",
        web: { web_searches: 2, web_asked: 2, web_read: 5, web_priority: 1, web_extra: 3 },
        near_budget: false,
      },
    ],
    next_pass: {
      kind: "pre",
      window_from: "2026-11-08T15:00:00Z",
      window_until: "2026-11-08T19:30:00Z",
      lineups_until: null,
      due_now: false,
    },
    searches: {
      searches: 2,
      failed: 1,
      first_at: "2026-11-08T05:09:00Z",
      last_at: "2026-11-08T05:10:00Z",
      cost_usd: "0.030000",
      sources_read: 5,
    },
    exa: {
      allowed: true,
      reason: "ok",
      budget_usd: "35",
      spent_month_usd: "4.20",
      spent_today_usd: "0.15",
      daily_cap_usd: "2.40",
    },
    evidence: { CONFIRMED: 2, PROBABLE: 1, CONTRADICTORY: 0, RUMOR: 1, OUTDATED: 0 },
    evidence_newest_at: "2026-11-08T05:10:00Z",
    verdict: {
      code: "searched",
      at: "2026-11-08T05:10:00Z",
      searches: 2,
      pages: 5,
      items: 4,
    },
    ...over,
  };
}

describe("the verdict in words", () => {
  test("searched: when, how many searches, pages and news", () => {
    expect(verdictText(diagnosis().verdict, NOW)).toBe(
      "Se buscó a las 00:10: 2 búsquedas, 5 páginas, 4 noticias.",
    );
    const unknown: DiagnosisVerdict = {
      code: "searched",
      at: "2026-11-07T20:00:00Z",
      searches: 1,
      pages: null,
      items: 0,
    };
    expect(verdictText(unknown, NOW)).toBe(
      "Se buscó el 7 nov 15:00: 1 búsqueda, páginas sin contar, 0 noticias.",
    );
  });

  test("not yet: the AI's day opens at 00:05 in Bogotá, with the first pass expected", () => {
    const v: DiagnosisVerdict = {
      code: "day_not_open",
      next_pass: "first",
      next_at: "2026-11-09T05:05:00Z",
    };
    expect(verdictText(v, NOW)).toBe(
      "Aún no: el día de la IA abre a las 00:05 de Bogotá; primera pasada prevista el 9 nov 00:05.",
    );
  });

  test("the other reasons, each with the next pass when there is one", () => {
    expect(verdictText({ code: "no_market" }, NOW)).toBe(
      "Sin mercado: no se analiza ni se busca. Entra en el día de la IA cuando tenga cuotas.",
    );
    expect(
      verdictText({ code: "not_covered", next_pass: "pre", next_at: "2026-11-08T15:00:00Z" }, NOW),
    ).toBe(
      "Fuera de la cobertura garantizada y sin plaza entre las búsquedas del día: no se buscó. Próxima pasada: previa, a las 10:00.",
    );
    expect(verdictText({ code: "exa_spent", exa_reason: "month_spent" }, NOW)).toBe(
      "Sobre de Exa agotado (gastado el del mes): no se hacen búsquedas nuevas.",
    );
    for (const code of [
      "not_tracked",
      "kicked_off",
      "first_pending",
      "near_budget",
      "covered_not_searched",
    ] as const) {
      expect(verdictText({ code }, NOW)).not.toContain("match.advanced");
    }
  });

  test("in English too", () => {
    setLocale("en");
    expect(verdictText(diagnosis().verdict, NOW)).toBe(
      "Searched at 00:10: 2 searches, 5 pages, 4 news items.",
    );
    expect(nextPassText(diagnosis().next_pass, NOW)).toBe("pre-match, from 10:00 to 14:30.");
  });
});

describe("the facts", () => {
  test("times are Bogotá's: the same day says the hour, another day the date", () => {
    expect(whenText("2026-11-08T05:10:00Z", NOW)).toBe("a las 00:10");
    expect(whenText("2026-11-08T04:50:00Z", NOW)).toBe("el 7 nov 23:50");
  });

  test("a pass's web counts in words, any other web count as recorded", () => {
    expect(passWebText(diagnosis().passes[0]!)).toBe(
      "2 búsquedas pagadas · 2 consultas respondidas · 5 páginas leídas · por cobertura garantizada · web_extra 3",
    );
    const quiet = { ...diagnosis().passes[0]!, web: {}, near_budget: true };
    expect(passWebText(quiet)).toBe("sin búsqueda por estar cerca del límite del presupuesto");
  });

  test("searches, Exa's budget, the stored news and the next pass", () => {
    expect(searchesText(diagnosis(), NOW)).toBe(
      "2 búsquedas · 1 fallida · primera a las 00:09 · última a las 00:10 · 0,030 US$",
    );
    expect(exaText(diagnosis().exa)).toBe(
      "4,20 US$ de 35,00 US$ este mes · hoy 0,15 US$ de 2,40 US$ · permite buscar",
    );
    expect(exaText(null)).toBe("No se pudo leer.");
    expect(evidenceText(diagnosis())).toBe("2 confirmadas · 1 probable · 1 rumor");
    expect(nextPassText(diagnosis().next_pass, NOW)).toBe("previa, de 10:00 a 14:30.");
    const final = {
      kind: "final" as const,
      window_from: "2026-11-08T19:20:00Z",
      window_until: "2026-11-08T20:50:00Z",
      lineups_until: "2026-11-08T20:10:00Z",
      due_now: true,
    };
    expect(nextPassText(final, NOW)).toBe(
      "final, de 14:20 a 15:50. Sin alineaciones confirmadas espera hasta las 15:10. Toca ya: la corre el próximo ciclo.",
    );
    expect(nextPassText(null, NOW)).toBe("Ninguna: no le quedan pasadas o no tiene mercado.");
  });
});

describe("the panel", () => {
  test("draws the verdict first, the facts and every pass", () => {
    const html = renderToStaticMarkup(<NewsDiagnosisView d={diagnosis()} now={NOW} />);
    expect(html).toContain('data-code="searched"');
    expect(html).toContain("Se buscó a las 00:10");
    expect(html).toContain("La Liga · grupo de prioridad 1");
    expect(html).toContain("Sí: grupo 1");
    expect(html).toContain("primera · a las 00:10 · completa");
    expect(html.indexOf("advanced-news-verdict")).toBeLessThan(
      html.indexOf("advanced-news-passes"),
    );
  });

  test("a match without passes says so", () => {
    const d = diagnosis({ passes: [], verdict: { code: "first_pending" }, next_pass: null });
    const html = renderToStaticMarkup(<NewsDiagnosisView d={d} now={NOW} />);
    expect(html).toContain("Sin pasadas registradas.");
    expect(html).toContain("La primera pasada todavía no ha corrido");
  });
});
