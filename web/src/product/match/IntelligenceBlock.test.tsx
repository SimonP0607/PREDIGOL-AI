/// <reference types="bun" />
/**
 * PREDIGOL INTELLIGENCE before kick-off (plan Partidos y Match Center, R1-R3): one reading - the chronicle's first stretch or
 * the structured reading, never both - then the picks PrediGol published, only when there are some (a reader without one sees
 * no picks block and no notice of selections in evaluation), the owner's preview with its picks in evaluation labelled, and
 * the way to the whole Análisis. The block keeps the anchor «Mi parlay» links to.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import type { Envelope } from "@/lib/api/v1/types";
import type { PickCard as PickCardData } from "@/lib/api/v1/types_product";
import type { MatchReading } from "@/lib/api/v1/types_reading";
import type { ReadingLoad } from "@/product/reading/useReading";
import { INTELLIGENCE_ID } from "./AnalysisBlock";
import { IntelligenceView } from "./IntelligenceBlock";
import { UpcomingPicksView, type UpcomingPicksLoad } from "./PicksTab";

setLocale("es");
afterEach(() => setLocale("es"));

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
        {
          code: "match_intro",
          params: { competition: "La Liga", round: "Regular Season - 12" },
          ref: "packet:fixture",
        },
      ],
    },
    { key: "risks", facts: [{ code: "lineups_unconfirmed", params: {}, ref: "packet:lineups" }] },
  ],
};

const NARRATIVE: MatchReading["narrative"] = {
  version: "user-narrative-v3",
  written_at: "2026-10-25T10:40:00Z",
  data_at: "2026-10-25T10:30:00Z",
  es: [
    {
      key: "summary",
      sentences: [{ text: "Un clásico con la tabla en juego.", refs: ["P:fixture"] }],
    },
    { key: "home", sentences: [{ text: "El Valencia llega con dudas.", refs: ["P:form.home"] }] },
  ],
  en: [
    {
      key: "summary",
      sentences: [{ text: "A classic with the table at stake.", refs: ["P:fixture"] }],
    },
    { key: "home", sentences: [{ text: "Valencia arrive with doubts.", refs: ["P:form.home"] }] },
  ],
  sources: [],
};

function reading(data: MatchReading = READING): ReadingLoad {
  return {
    status: "success",
    envelope: {
      status: "ok",
      data,
      reason: null,
      meta: { generated_at: "2026-10-25T12:00:00Z", api_version: "v1" },
    } as Envelope<MatchReading | null>,
  };
}

const pick = (id: number) => ({ pick_id: id, fixture_id: 7 }) as PickCardData;

function render(picks: UpcomingPicksLoad, load: ReadingLoad = reading()): string {
  return renderToStaticMarkup(
    <IntelligenceView
      reading={load}
      onMore={() => undefined}
      picks={
        <UpcomingPicksView
          load={picks}
          resetKey="7"
          renderPick={(p, rank, shadow) => (
            <article data-testid="stub-pick" data-rank={rank ?? ""} data-shadow={String(shadow)}>
              pick {p.pick_id}
            </article>
          )}
        />
      }
    />,
  );
}

const NONE: UpcomingPicksLoad = { status: "success", picks: [], shadow: false, top: [] };

describe("PrediGol Intelligence, before kick-off", () => {
  test("its title, the anchor «Mi parlay» links to, and the way to the whole analysis", () => {
    const html = render(NONE);
    expect(INTELLIGENCE_ID).toBe("predigol-intelligence");
    expect(html).toContain(`id="${INTELLIGENCE_ID}"`);
    expect(html).toContain('data-testid="intelligence-block"');
    expect(html).toContain("PrediGol Intelligence");
    expect(html).toContain('data-testid="reading-see-all"');
    expect(html).toContain("Ver el análisis completo");
    // the round as the header reads it
    expect(html).toContain("Partido de La Liga (Jornada 12).");
  });

  test("a reader without a published pick sees no picks block, no empty notice, nothing in evaluation", () => {
    const html = render(NONE);
    expect(html).not.toContain('data-testid="match-picks"');
    expect(html).not.toContain("Picks para este partido");
    expect(html).not.toContain("No hay picks");
    expect(html).not.toContain("en evaluación");
    expect(html).not.toContain("MODO EVALUACIÓN");
    expect(html).not.toContain("data-empty-state");
  });

  test("the published picks, inside the block, between the reading and the way to Análisis, ranked as the board ranks them", () => {
    const html = render({
      status: "success",
      picks: [pick(11), pick(12)],
      shadow: false,
      top: [pick(12)],
    });
    const block = html.indexOf('data-testid="intelligence-block"');
    const lead = html.indexOf('data-testid="reading-lead"');
    const picks = html.indexOf('data-testid="match-picks"');
    const more = html.indexOf('data-testid="reading-see-all"');
    expect(block).toBeGreaterThanOrEqual(0);
    expect(lead).toBeGreaterThan(block);
    expect(picks).toBeGreaterThan(lead);
    expect(more).toBeGreaterThan(picks);
    expect(html.split('data-testid="stub-pick"').length - 1).toBe(2);
    expect(html).toContain('data-rank="1" data-shadow="false">pick 12');
    expect(html).toContain("Picks publicados");
    expect(html).toContain('data-shadow="false"');
    expect(html).not.toContain("MODO EVALUACIÓN");
    // decision 4 of the plan: the pick's probability says which model it comes from, apart from the forecast's
    expect(html).toContain('data-testid="match-picks-origin"');
    expect(html).toContain("modelo con el que PrediGol decide sus picks");
  });

  test("no published pick, no word about where a pick's probability comes from", () => {
    const html = render({ status: "success", picks: [], shadow: false, top: [] });
    expect(html).not.toContain('data-testid="match-picks-origin"');
  });

  test("the owner's preview: the picks in evaluation, each labelled - and an empty one says so", () => {
    const html = render({ status: "success", picks: [pick(21)], shadow: true, top: [] });
    expect(html).toContain('data-testid="match-picks" data-shadow="true"');
    expect(html).toContain("Picks en evaluación");
    expect(html).toContain("MODO EVALUACIÓN");
    expect(html).toContain('data-shadow="true">pick 21');
    const empty = render({ status: "success", picks: [], shadow: true, top: [] });
    expect(empty).toContain("No hay picks shadow para este partido.");
    expect(empty).not.toContain('data-testid="match-picks"');
  });

  test("the picks' own states: a skeleton while they load, an error with its retry", () => {
    expect(render({ status: "pending" })).toContain('data-testid="match-picks-loading"');
    const error = render({ status: "error", error: new Error("boom"), retry: () => undefined });
    expect(error).not.toContain('data-testid="match-picks"');
    expect(error).toContain('data-testid="reading-see-all"');
  });

  test("one reading: the chronicle's first stretch when there is one, never the facts as well", () => {
    const html = render(NONE, reading({ ...READING, narrative: NARRATIVE }));
    expect(html).toContain('data-testid="reading-narrative-lead"');
    expect(html).toContain("Un clásico con la tabla en juego.");
    expect(html).toContain("Escrito con datos de");
    expect(html).not.toContain("El Valencia llega con dudas.");
    expect(html).not.toContain('data-testid="reading-fact"');
    expect(html.split('data-testid="reading-lead"').length - 1).toBe(1);
  });

  test("one reading: without a chronicle, the structured one - never the chronicle", () => {
    const html = render(NONE);
    expect(html).toContain('data-testid="reading-fact"');
    expect(html).not.toContain("reading-narrative");
    expect(html).toContain("Qué puede salir mal:");
    expect(html.split('data-testid="reading-lead"').length - 1).toBe(1);
  });

  test("the reading's own states inside the block", () => {
    expect(render(NONE, { status: "pending" })).toContain('aria-busy="true"');
    expect(
      render(NONE, { status: "error", error: new Error("x"), retry: () => undefined }),
    ).toContain('data-kind="error"');
  });

  test("in English", () => {
    setLocale("en");
    const html = render({ status: "success", picks: [pick(11)], shadow: false, top: [] });
    expect(html).toContain("Published picks");
    expect(html).toContain("See the full analysis");
    expect(html).toContain("PrediGol&#x27;s reading of this match");
    expect(html).toContain("A La Liga match (Matchday 12).");
  });
});
