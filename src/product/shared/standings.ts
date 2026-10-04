/**
 * A competition season's tables kept apart: sections by stage (Apertura, Clausura, a group stage,
 * an annual aggregate), and a row's all / home / away figures. The API maps each table to the
 * stage it ranks (fbi.competitions.phases); nothing here guesses a phase from a label.
 */
import type {
  CompetitionTable,
  StandingLine,
  StandingsTable,
  TableKind,
  TableRow,
  TableSplit,
} from "@/lib/api/v1/types_center";

export type Split = "all" | "home" | "away";

export interface Figures {
  played: number;
  wins: number;
  draws: number;
  losses: number;
  goalsFor: number;
  goalsAgainst: number;
  goalDiff: number;
  points: number;
}

export interface RankedRow {
  rank: number;
  row: TableRow;
  figures: Figures;
}

function fromSplit(s: TableSplit | null | undefined): Figures | null {
  if (!s || s.played === null) return null;
  const wins = s.wins ?? 0;
  const draws = s.draws ?? 0;
  const gf = s.goals_for ?? 0;
  const ga = s.goals_against ?? 0;
  return {
    played: s.played,
    wins,
    draws,
    losses: s.losses ?? 0,
    goalsFor: gf,
    goalsAgainst: ga,
    goalDiff: gf - ga,
    points: 3 * wins + draws,
  };
}

/** A row's figures for all games, or its home or away games only (null when the provider gave none). */
export function figures(r: TableRow, split: Split): Figures | null {
  if (split === "home") return fromSplit(r.home);
  if (split === "away") return fromSplit(r.away);
  return {
    played: r.played,
    wins: r.wins,
    draws: r.draws,
    losses: r.losses,
    goalsFor: r.goals_for,
    goalsAgainst: r.goals_against,
    goalDiff: r.goals_diff ?? r.goals_for - r.goals_against,
    points: r.points,
  };
}

/**
 * The rows in order: the provider's rank for all games; for home or away games, ranked by points,
 * goal difference, goals scored (the provider ranks only the whole table), ties keeping its order.
 */
export function rankedRows(rows: TableRow[], split: Split): RankedRow[] {
  const withFigures = rows
    .map((row) => ({ row, figures: figures(row, split) }))
    .filter((x): x is { row: TableRow; figures: Figures } => x.figures !== null);
  if (split === "all") {
    return [...withFigures]
      .sort((a, b) => a.row.rank - b.row.rank)
      .map((x) => ({ rank: x.row.rank, ...x }));
  }
  const sorted = [...withFigures].sort(
    (a, b) =>
      b.figures.points - a.figures.points ||
      b.figures.goalDiff - a.figures.goalDiff ||
      b.figures.goalsFor - a.figures.goalsFor ||
      a.row.rank - b.row.rank,
  );
  return sorted.map((x, i) => ({ rank: i + 1, ...x }));
}

export function hasSplits(rows: TableRow[]): boolean {
  return rows.some((r) => (r.home?.played ?? null) !== null || (r.away?.played ?? null) !== null);
}

export interface TableSection {
  /** The stage, or "aggregate:<stages>" / "other" for tables that rank no single stage. */
  id: string;
  stage: string | null;
  phase: string | null;
  kind: "stage" | "aggregate" | "other";
  current: boolean;
  tables: StandingsTable[];
}

/** Tables grouped by the stage they rank, in the API's order (stage order, then aggregates, then others). */
export function tableSections(t: CompetitionTable): TableSection[] {
  const tables = t.tables ?? [];
  const out: TableSection[] = [];
  const byId = new Map<string, TableSection>();
  for (const table of tables) {
    const kind: TableSection["kind"] =
      table.stage !== null ? "stage" : table.kind === "aggregate" ? "aggregate" : "other";
    const id =
      kind === "stage"
        ? `stage:${table.stage}`
        : kind === "aggregate"
          ? `aggregate:${table.stages.join("+")}:${table.key}`
          : "other";
    let section = byId.get(id);
    if (!section) {
      section = {
        id,
        stage: table.stage,
        phase: table.phase,
        kind,
        current: false,
        tables: [],
      };
      byId.set(id, section);
      out.push(section);
    }
    section.tables.push(table);
    section.current = section.current || table.is_current;
  }
  return out;
}

/** The section shown first: the stage being played, else the last stage with a table. */
export function defaultSection(sections: TableSection[]): string | null {
  const current = sections.find((s) => s.current);
  if (current) return current.id;
  const stages = sections.filter((s) => s.kind === "stage");
  return (stages[stages.length - 1] ?? sections[0])?.id ?? null;
}

/** i18n key of a table kind's short label. */
export function kindKey(kind: TableKind): string {
  return `match.standings.kind.${kind}`;
}

/** The tables a Match Center's two rows come from, in their order: one, or each team's group. */
export function matchTables(
  lines: StandingLine[],
  tables: StandingsTable[] | undefined,
): StandingsTable[] {
  const keys = new Set(lines.map((l) => l.table_key).filter((k): k is string => !!k));
  return (tables ?? []).filter((t) => keys.has(t.key));
}
