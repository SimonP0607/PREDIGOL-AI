/**
 * The owner's console of the availability matrix (plan PM, PM-02-08, lámina I11; UX-174): the rows, figures and filters of C-16's
 * private matrix (`GET /admin/availability/matrix`). Pure: it reads what the nightly recalculation measured and decides nothing.
 */
import type {
  AvailabilityPrivate,
  CompetitionAvailability,
  CoverageFamily,
  CoverageLevel,
  LevelCellPrivate,
  LevelChange,
  MarketCellPrivate,
  SeasonAvailability,
} from "@/lib/api/v1/types_availability";
import { isMissing } from "@/lib/api/v1/types_intelligence";
import { cellUnavailable, type UnavailableKind } from "@/product/shared/availabilityState";

export type PrivateSeason = SeasonAvailability<LevelCellPrivate, MarketCellPrivate>;
export type PrivateCompetition = CompetitionAvailability<PrivateSeason>;

/** The seven families, in the order of C-16's directory (data, then prices). */
export const FAMILIES: readonly CoverageFamily[] = [
  "base",
  "team_stats",
  "xg",
  "player_stats",
  "referee",
  "main_odds",
  "stat_odds",
];

export const LEVELS: readonly CoverageLevel[] = ["A", "B", "C", "D", "MI"];

/** A level a screen draws complete (section 4: B or more). */
export function visible(level: CoverageLevel): boolean {
  return level === "A" || level === "B";
}

export interface MatrixRow {
  id: number;
  name: string;
  country: string | null;
  tier: number | null;
  summary: CoverageLevel;
  families: Partial<Record<CoverageFamily, CoverageLevel>>;
  /** The season the directory is decided by (the latest with a sample). */
  season: PrivateSeason | null;
  /** Matches measured in that season (the cell of events, else the largest). */
  sample: number;
  /** When it was last measured (the latest cell). */
  measuredAt: string | null;
  /** Families under B. */
  blocked: number;
}

/** The season C-16 decided the competition by: the latest one whose summary is not MI, else the latest. */
export function headSeason(c: PrivateCompetition): PrivateSeason | null {
  return c.seasons.find((s) => s.summary !== "MI") ?? c.seasons[0] ?? null;
}

function cellsOf(s: PrivateSeason | null): Array<LevelCellPrivate | MarketCellPrivate> {
  return s ? [...s.data, ...s.markets] : [];
}

export function matrixRow(c: PrivateCompetition): MatrixRow {
  const season = headSeason(c);
  const families: Partial<Record<CoverageFamily, CoverageLevel>> = {};
  for (const f of c.families) families[f.family] = f.level;
  const cells = cellsOf(season);
  const events = season?.data.find((d) => d.key === "events");
  const sample = events?.n ?? Math.max(0, ...(season?.data.map((d) => d.n) ?? [0]));
  const measuredAt = cells.reduce<string | null>(
    (latest, cell) => (latest === null || cell.measured_at > latest ? cell.measured_at : latest),
    null,
  );
  return {
    id: c.competition_id,
    name: c.name,
    country: isMissing(c.country) ? null : c.country,
    tier: isMissing(c.tier) ? null : c.tier,
    summary: c.summary,
    families,
    season,
    sample,
    measuredAt,
    blocked: FAMILIES.filter((f) => families[f] !== undefined && !visible(families[f])).length,
  };
}

export interface MatrixFilter {
  term: string;
  level: CoverageLevel | "all";
  country: string;
  blockedOnly: boolean;
}

export const NO_FILTER: MatrixFilter = { term: "", level: "all", country: "", blockedOnly: false };

/** Filters by name or country, summary level, country and «solo bloqueadas»; ordered by priority (tier), then name. */
export function filterRows(rows: readonly MatrixRow[], f: MatrixFilter): MatrixRow[] {
  const q = f.term.trim().toLowerCase();
  return rows
    .filter((r) => {
      if (f.level !== "all" && r.summary !== f.level) return false;
      if (f.country && r.country !== f.country) return false;
      if (f.blockedOnly && r.blocked === 0) return false;
      return !q || `${r.name} ${r.country ?? ""}`.toLowerCase().includes(q);
    })
    .sort((a, b) => (a.tier ?? 99) - (b.tier ?? 99) || a.name.localeCompare(b.name));
}

export function countries(rows: readonly MatrixRow[]): string[] {
  return [...new Set(rows.map((r) => r.country).filter((c): c is string => !!c))].sort((a, b) =>
    a.localeCompare(b),
  );
}

export interface MatrixFigures {
  competitions: number;
  levelA: number;
  visibleCells: number;
  totalCells: number;
  /** The reason that keeps most cells under B, and how many it keeps; null when none is. */
  topReason: { reason: string; cells: number } | null;
  /** The state those hidden cells are in, by C-16's states. */
  hiddenByKind: Partial<Record<UnavailableKind, number>>;
  changes: number;
  up: number;
  down: number;
}

/** The four figures at the top of I11, from the matrix and its last week of changes. */
export function matrixFigures(matrix: AvailabilityPrivate): MatrixFigures {
  const rows = (matrix.competitions as PrivateCompetition[]).map(matrixRow);
  let visibleCells = 0;
  let totalCells = 0;
  const reasons = new Map<string, number>();
  const hiddenByKind: Partial<Record<UnavailableKind, number>> = {};
  for (const r of rows) {
    for (const cell of cellsOf(r.season)) {
      totalCells += 1;
      const state = cellUnavailable(cell);
      if (!state) {
        visibleCells += 1;
        continue;
      }
      hiddenByKind[state.kind] = (hiddenByKind[state.kind] ?? 0) + 1;
      const reason = cell.reason === "ninguno" ? `nivel_${cell.level}` : cell.reason;
      reasons.set(reason, (reasons.get(reason) ?? 0) + 1);
    }
  }
  const top = [...reasons.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0];
  const changes = matrix.changes.items;
  return {
    competitions: rows.length,
    levelA: rows.filter((r) => r.summary === "A").length,
    visibleCells,
    totalCells,
    topReason: top ? { reason: top[0], cells: top[1] } : null,
    hiddenByKind,
    changes: changes.length,
    up: changes.filter((c) => c.reason === "sube").length,
    down: changes.filter((c) => c.reason === "baja" || c.reason === "incumple_una_vez").length,
  };
}

export interface ChangeRow extends LevelChange {
  competition: string | null;
  season: number | null;
}

/** The changes of the last week with their competition's name (by the season they belong to), newest first. */
export function changeRows(matrix: AvailabilityPrivate): ChangeRow[] {
  const bySeason = new Map<number, { name: string; season: number }>();
  for (const c of matrix.competitions as PrivateCompetition[]) {
    for (const s of c.seasons)
      bySeason.set(s.competition_season_id, { name: c.name, season: s.season });
  }
  return [...matrix.changes.items]
    .sort((a, b) => b.changed_at.localeCompare(a.changed_at))
    .map((c) => {
      const owner = bySeason.get(c.competition_season_id);
      return { ...c, competition: owner?.name ?? null, season: owner?.season ?? null };
    });
}
