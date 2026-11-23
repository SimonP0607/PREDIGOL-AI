/**
 * AP-P07 (a): the key figures of the Análisis, read from the facts the structured reading already carries - the same codes
 * and parameters its sentences are written from, so a figure is never a new calculation and never says more than its
 * sentence. Per side: the table position, the points to the zone it plays for, the form, the xG for and against and the days
 * of rest; and «Cómo quedaría la tabla» from the three `table_after` facts. A figure the reading lacks is left out.
 */
import type { MatchReading, ReadingFact, ReadingParam } from "@/lib/api/v1/types_reading";

type P = Record<string, ReadingParam>;

function str(p: P, key: string): string | null {
  const v = p[key];
  return typeof v === "string" && v ? v : null;
}

function num(p: P, key: string): number | null {
  const v = p[key];
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

export type FormLetter = "W" | "D" | "L";

export interface SideFigures {
  team: string;
  rank: number | null;
  /** The zone it is in (`zone` of `stakes_zone`) and the points to the one it chases or leaves behind. */
  zone: string | null;
  gap: { points: number; zone: string; direction: "up" | "down" } | null;
  form: { letters: FormLetter[]; matches: number; ppg: number } | null;
  xg: { for: number; against: number; matches: number | null } | null;
  rest: { days: number; atMost: boolean } | null;
}

export interface TableScenario {
  result: "home_win" | "draw" | "away_win";
  homePoints: number;
  awayPoints: number;
  homePlaces: { best: number; worst: number } | null;
  awayPlaces: { best: number; worst: number } | null;
}

export interface KeyFigures {
  home: SideFigures;
  away: SideFigures;
  table: TableScenario[];
}

const SCENARIOS: readonly TableScenario["result"][] = ["home_win", "draw", "away_win"];

function allFacts(reading: MatchReading): ReadingFact[] {
  return reading.sections.flatMap((s) => s.facts);
}

function emptySide(team: string): SideFigures {
  return { team, rank: null, zone: null, gap: null, form: null, xg: null, rest: null };
}

function letters(sequence: string): FormLetter[] {
  return [...sequence].filter((c): c is FormLetter => c === "W" || c === "D" || c === "L");
}

function places(p: P, side: "home" | "away"): { best: number; worst: number } | null {
  const best = num(p, `${side}_best`);
  const worst = num(p, `${side}_worst`);
  return best === null || worst === null ? null : { best, worst };
}

/** The sides' names: the page's own when it has them, otherwise the first two teams the facts name, in order. */
function sideNames(
  facts: readonly ReadingFact[],
  teams: { home: string; away: string } | undefined,
): { home: string; away: string } | null {
  if (teams?.home && teams.away) return teams;
  const seen: string[] = [];
  for (const f of facts) {
    const named = [str(f.params, "team"), str(f.params, "home"), str(f.params, "away")];
    for (const n of named) if (n && !seen.includes(n)) seen.push(n);
  }
  const [home, away] = seen;
  return home && away ? { home, away } : null;
}

/** The first fact of a code for one team: the reading says each thing once per side. */
function forTeam(facts: readonly ReadingFact[], code: string, team: string): P | null {
  return facts.find((f) => f.code === code && str(f.params, "team") === team)?.params ?? null;
}

function sideFigures(facts: readonly ReadingFact[], team: string): SideFigures {
  const out = emptySide(team);
  const zone = forTeam(facts, "stakes_zone", team);
  if (zone) {
    out.rank = num(zone, "rank");
    out.zone = str(zone, "zone");
  }
  for (const [code, direction] of [
    ["stakes_gap_up", "up"],
    ["stakes_gap_down", "down"],
  ] as const) {
    const g = forTeam(facts, code, team);
    const points = g ? num(g, "gap") : null;
    const zoneKey = g ? str(g, "zone") : null;
    if (g && points !== null && zoneKey && !out.gap) out.gap = { points, zone: zoneKey, direction };
  }
  const form = forTeam(facts, "form", team);
  const sequence = form ? str(form, "sequence") : null;
  if (form && sequence) {
    const n = num(form, "n");
    const ppg = num(form, "ppg");
    if (n !== null && ppg !== null) out.form = { letters: letters(sequence), matches: n, ppg };
  }
  const xg = forTeam(facts, "xg", team);
  if (xg) {
    const xf = num(xg, "xg_for");
    const xa = num(xg, "xg_against");
    if (xf !== null && xa !== null) out.xg = { for: xf, against: xa, matches: num(xg, "n") };
  }
  const rest = forTeam(facts, "rest_days", team);
  const days = rest ? num(rest, "days") : null;
  if (rest && days !== null) out.rest = { days, atMost: rest["at_most"] === true };
  return out;
}

function hasFigures(s: SideFigures): boolean {
  return s.rank !== null || s.gap !== null || s.form !== null || s.xg !== null || s.rest !== null;
}

/** The three scenarios of `table_after`, in the order win, draw, loss - only those the reading carries whole. */
function scenarios(facts: readonly ReadingFact[]): TableScenario[] {
  return SCENARIOS.flatMap((result) => {
    const f = facts.find((x) => x.code === "table_after" && str(x.params, "result") === result);
    if (!f) return [];
    const homePoints = num(f.params, "home_points");
    const awayPoints = num(f.params, "away_points");
    const homePlaces = places(f.params, "home");
    const awayPlaces = places(f.params, "away");
    if (homePoints === null || awayPoints === null || !homePlaces || !awayPlaces) return [];
    return [{ result, homePoints, awayPoints, homePlaces, awayPlaces }];
  });
}

/** The key figures of a reading, or null when it carries none (then the sentences are the whole analysis, as before). */
export function keyFigures(
  reading: MatchReading,
  teams?: { home: string; away: string } | undefined,
): KeyFigures | null {
  const facts = allFacts(reading);
  const names = sideNames(facts, teams);
  if (!names) return null;
  const home = sideFigures(facts, names.home);
  const away = sideFigures(facts, names.away);
  const table = scenarios(facts);
  if (!hasFigures(home) && !hasFigures(away) && table.length === 0) return null;
  return { home, away, table };
}
