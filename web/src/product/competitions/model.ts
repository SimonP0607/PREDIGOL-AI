/**
 * What a competition's page shows (plan PM, PM-09-04; UX-178): each tab by the level of ITS OWN data in C-16, never by the summary
 * (section 4 of the plan: «ninguna pantalla decide con el resumen»). The calendar and the results are always there; the tables and
 * the leaders need the base data (events and line-ups) above level D, and data to show. Without C-16 (`FBI_AVAILABILITY` off) the
 * page shows what the routes it reads have, as every page did before the matrix.
 */
import type {
  CompetitionAvailability,
  CoverageFamily,
  CoverageLevel,
  SeasonAvailability,
} from "@/lib/api/v1/types_availability";

export const COMPETITION_TABS = ["table", "calendar", "leaders", "coverage"] as const;
export type CompetitionTab = (typeof COMPETITION_TABS)[number];

export interface CompetitionModules {
  tabs: CompetitionTab[];
  /** What the competition does not offer at its level, said in one line where it would be. */
  notOffered: Array<"table" | "leaders">;
  /** The summary of its newest graded season (only the header and the directory write it). */
  level: CoverageLevel | null;
  label: string | null;
}

export function familyLevel(
  c: CompetitionAvailability | null | undefined,
  family: CoverageFamily,
): CoverageLevel | null {
  return c?.families.find((f) => f.family === family)?.level ?? null;
}

/** The newest graded season of the competition in C-16 (its own route sends them newest first or not: sorted here). */
export function newestSeason(
  c: CompetitionAvailability | null | undefined,
): SeasonAvailability | null {
  const seasons = [...(c?.seasons ?? [])].sort((a, b) => b.season - a.season);
  return seasons[0] ?? null;
}

export function competitionModules(
  c: CompetitionAvailability | null | undefined,
  has: { table: boolean; leaders: boolean },
): CompetitionModules {
  const base = familyLevel(c, "base");
  const limited = base === "D";
  const tabs: CompetitionTab[] = [];
  const notOffered: CompetitionModules["notOffered"] = [];
  if (has.table && !limited) tabs.push("table");
  else if (limited) notOffered.push("table");
  tabs.push("calendar");
  if (has.leaders && !limited) tabs.push("leaders");
  else if (limited) notOffered.push("leaders");
  if (c) tabs.push("coverage");
  return { tabs, notOffered, level: c ? c.summary : null, label: c ? c.summary_label : null };
}

/** The tab asked in the address when the page offers it; else the first one (the table, or the calendar). */
export function chosenTab(
  asked: string | undefined,
  tabs: readonly CompetitionTab[],
): CompetitionTab {
  const found = tabs.find((x) => x === asked);
  return found ?? tabs[0] ?? "calendar";
}

/** The seven families in the order the coverage tab lists them. */
export const FAMILY_ORDER: readonly CoverageFamily[] = [
  "base",
  "team_stats",
  "player_stats",
  "xg",
  "referee",
  "main_odds",
  "stat_odds",
];
