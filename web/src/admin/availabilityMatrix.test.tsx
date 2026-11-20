/// <reference types="bun" />
/**
 * Plan PM, PM-02-08 (I11): the owner's console of the availability matrix shows, for every graded competition, its level by family,
 * its sample and the date it was measured, the cells of one competition, the changes of the last week and the shadow's
 * discrepancies, from C-16's own examples; with C-16 off the competitions page is the catalogue as it was.
 */
import { afterAll, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setLocale } from "@/lib/i18n";
import type { AvailabilityPrivate, MatchAvailability } from "@/lib/api/v1/types_availability";
import competitionExample from "@/lib/api/v1/fixtures/c16_competition_private.json";
import changesExample from "@/lib/api/v1/fixtures/c16_changes_private.json";
import matchExample from "@/lib/api/v1/fixtures/c16_match.json";
import {
  FAMILIES,
  NO_FILTER,
  changeRows,
  countries,
  filterRows,
  matrixFigures,
  matrixRow,
  type PrivateCompetition,
} from "./availabilityMatrix";
import { AvailabilityConsoleView, LevelBadge, MatchStates } from "./AvailabilityConsole";

afterAll(() => setLocale("es"));

const competition = competitionExample as unknown as AvailabilityPrivate;
const changes = changesExample as unknown as AvailabilityPrivate;
const base = (competition.competitions as PrivateCompetition[])[0]!;

/** A matrix of 138 competitions built from the contract's example, with the example's changes and discrepancies. */
function matrixOf(count: number): AvailabilityPrivate {
  const comps: PrivateCompetition[] = Array.from({ length: count }, (_, i) => ({
    ...base,
    competition_id: base.competition_id + i,
    name: `${base.name} ${i + 1}`,
    country: i % 3 === 0 ? "Colombia" : i % 3 === 1 ? "Argentina" : "Chile",
    tier: (i % 4) + 1,
    summary: (["A", "B", "C", "D"] as const)[i % 4] ?? "A",
    seasons: base.seasons.map((s, k) => ({
      ...s,
      competition_season_id: s.competition_season_id + i * 10 + k,
    })),
  }));
  comps[0]!.seasons = base.seasons; // keeps the example's season ids, which the changes name
  return { ...changes, scope: "matriz", competitions: comps };
}

function html(node: React.ReactElement): string {
  const client = new QueryClient();
  return renderToStaticMarkup(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

const text = (s: string) => s.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");

describe("the matrix", () => {
  test("a row per competition: level of the seven families, sample and date", () => {
    const row = matrixRow(base);
    expect(row.summary).toBe("A");
    expect(FAMILIES.map((f) => row.families[f])).toEqual(["A", "A", "D", "B", "A", "A", "B"]);
    expect(row.sample).toBe(120);
    expect(row.measuredAt).toBe("2026-11-21T08:04:00Z");
    expect(row.blocked).toBe(1);
  });

  test("filters by name, level, country and «solo bloqueadas», ordered by priority", () => {
    const rows = (matrixOf(138).competitions as PrivateCompetition[]).map(matrixRow);
    expect(filterRows(rows, NO_FILTER)).toHaveLength(138);
    expect(filterRows(rows, { ...NO_FILTER, level: "C" }).every((r) => r.summary === "C")).toBe(
      true,
    );
    expect(filterRows(rows, { ...NO_FILTER, country: "Chile" })).toHaveLength(46);
    expect(filterRows(rows, { ...NO_FILTER, term: "uno 12" }).map((r) => r.name)).toContain(
      "Liga Ficticia Uno 12",
    );
    expect(filterRows(rows, { ...NO_FILTER, blockedOnly: true })).toHaveLength(138);
    const ordered = filterRows(rows, NO_FILTER).map((r) => r.tier);
    expect(ordered).toEqual([...ordered].sort((a, b) => (a ?? 99) - (b ?? 99)));
    expect(countries(rows)).toEqual(["Argentina", "Chile", "Colombia"]);
  });

  test("the four figures and the week of changes with their competition's name", () => {
    const m = matrixOf(1);
    const f = matrixFigures(m);
    expect(f.competitions).toBe(1);
    expect(f.levelA).toBe(1);
    expect(f.totalCells).toBe(19);
    expect(f.visibleCells).toBe(16);
    expect(f.changes).toBe(changes.changes.items.length);
    const rows = changeRows(m);
    expect(rows[0]?.competition).toBe(`${base.name} 1`);
    expect(rows[0]?.season).toBe(2026);
  });
});

describe("the console", () => {
  test("all 138 competitions reachable, the changes and the shadow, private", () => {
    setLocale("es");
    const out = html(<AvailabilityConsoleView matrix={matrixOf(138)} />);
    const words = text(out);
    expect(words).toContain("Competiciones evaluadas");
    expect(words).toContain("138");
    expect(out.match(/data-testid="availability-row"/g)?.length).toBe(50); // a page at a time, then «ver todas»
    expect(words).toContain("50 de 138");
    expect(words).toContain("Cambios de la última semana");
    expect(words).toContain("Primera medida");
    expect(words).toContain("Discrepancias de la sombra");
    expect(words).toContain("total_shotongoal.FT.match");
    expect(words).toContain("21 nov 2026");
    expect(words).toContain("120 partidos");
  });

  test("an empty matrix says so instead of drawing an empty table", () => {
    setLocale("es");
    const empty = { ...changes, scope: "matriz" as const, competitions: [] };
    const words = text(html(<AvailabilityConsoleView matrix={empty} />));
    expect(words).toContain("El recálculo aún no ha graduado ninguna competición.");
    expect(words).not.toContain("Competición × familia");
  });

  test("a level is a word for a screen reader, never only a colour", () => {
    setLocale("es");
    const out = html(<LevelBadge level="C" />);
    expect(out).toContain(">C<");
    expect(text(out)).toContain("Nivel C: cobertura parcial");
  });

  test("the seven states of a match in order, and the reader's one note for its blocks", () => {
    setLocale("es");
    const match = (matchExample as unknown as { match: MatchAvailability }).match;
    const words = text(html(<MatchStates match={match} />));
    expect(words).toContain("1 · Existe");
    expect(words).toContain("7 · Cumple reglas");
    expect(words).toContain("Sin evaluar");
    expect(words).toContain("En revisión");
    expect(words).toContain("Esta competición no ofrece xg del proveedor.");
  });
});
