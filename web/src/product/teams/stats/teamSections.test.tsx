/// <reference types="bun" />
/**
 * AP-T03: the team's statistics page draws every chart inside the evidence card, with a question as title, the axes named, the
 * «Cómo leerlo» sentence with the team's own figures and «¿Qué significa?»; a chart without data says why instead of drawing.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import type { StatsProfile, TeamBody } from "@/lib/api/v1/types_stats";
import preview from "@/components/analytics/stats/fixtures/c13_preview.json";
import { TeamSections } from "./TeamStatsHub";

afterEach(() => setLocale("es"));

const profile = preview as unknown as StatsProfile;
const entity = profile.entities[0]!;
const body = entity.team as TeamBody;

describe("the team's charts in the reader's language", () => {
  test("each chart is an evidence card with its reading sentence, its axes and a way to the glossary", () => {
    setLocale("es");
    const html = renderToStaticMarkup(<TeamSections entity={entity} body={body} />);
    for (const id of ["performance", "pulse", "intervals", "survival", "halves", "radar"])
      expect(html).toContain(`data-testid="stats-${id}"`);
    expect(html).toContain("data-evidence=");
    expect(html).toContain('data-review="completa"');
    expect(html.match(/¿Qué significa\?/g)?.length).toBeGreaterThanOrEqual(3);
    expect(html).toContain(body.team.name);
    expect(html).toContain("¿En qué minutos marca más que su liga?");
    expect(html).toContain("Horizontal: minuto del partido");
    expect(html).not.toMatch(/>p\d{2}</);
    expect(html).not.toMatch(/bootstrap|Kaplan|pulso-v/i);
  });

  test("a chart with no figures is not drawn: the reason is said instead", () => {
    setLocale("es");
    const empty = {
      ...body,
      pulse_for: { missing_reason: "sin_datos" },
      intervals: { missing_reason: "muestra_insuficiente", sample: 2, min_sample: 8 },
      series: body.series.map((p) => ({ ...p, xg_for_avg5: null, xg_against_avg5: null })),
    } as unknown as TeamBody;
    const html = renderToStaticMarkup(<TeamSections entity={entity} body={empty} />);
    expect(html).toContain("Sin datos de xG para esta liga.");
    expect(html).toContain("2 de 8");
    expect(html).not.toContain("<polygon");
  });

  test("English reads in English", () => {
    setLocale("en");
    const html = renderToStaticMarkup(<TeamSections entity={entity} body={body} />);
    expect(html).toContain("In which minutes does it score more than its league?");
    expect(html).toContain("What does it mean?");
  });
});
