/**
 * Cuotas «Por partido» (plan maestro unificado, UX-141; sheets C01, C02, C06): the boards of three markets - result, goals
 * over/under 2.5 and both teams to score - read with the explorer's own endpoint and put together match by match. Pure: it
 * joins what the API said, it computes no price.
 */
import { toNumber } from "@/lib/i18n/format";
import type {
  BookmakerRef,
  CompetitionBadge,
  OddsBoardPage,
  OddsBoardRow,
  OddsMarketInfo,
  OddsSelectionPrice,
  TeamBadge,
} from "../explorer/model";
import { rowEdge } from "../explorer/rows";

/** The three markets of the view, in the sheet's column order. */
export const BY_MATCH_MARKETS = [
  { key: "result.1x2", line: "main", selections: ["Home", "Draw", "Away"] },
  { key: "goals.total", line: "2.5", selections: ["Over", "Under"] },
  { key: "goals.btts", line: "main", selections: ["Yes", "No"] },
] as const;

export type ByMatchMarket = (typeof BY_MATCH_MARKETS)[number]["key"];

export interface MatchCell {
  market: ByMatchMarket;
  row: OddsBoardRow;
  info: OddsMarketInfo;
  /** One price per column of the market, in its order; null where no bookmaker quotes it. */
  prices: (OddsSelectionPrice | null)[];
}

export interface MatchLine {
  fixture_id: number;
  kickoff_at: string;
  competition_id: number;
  home: TeamBadge;
  away: TeamBadge;
  cells: Partial<Record<ByMatchMarket, MatchCell>>;
  /** The oldest capture among its markets: the row is as old as its oldest price. */
  captured_at: string;
  stale: boolean;
  /** The widest difference with a fair price among its prices; null without fair prices. */
  edge: number | null;
}

export interface MatchBoard {
  lines: MatchLine[];
  competitions: Map<number, CompetitionBadge>;
  bookmakers: Map<number, string>;
  /** When the newest of the three answers was served (ms); 0 without any. */
  generatedAt: number;
}

function older(a: string, b: string): string {
  return Date.parse(a) <= Date.parse(b) ? a : b;
}

/** The three markets' pages, joined by match. A match missing from one market simply has no cell there. */
export function joinBoards(
  pages: Partial<Record<ByMatchMarket, readonly OddsBoardPage[] | undefined>>,
): MatchBoard {
  const byId = new Map<number, MatchLine>();
  const competitions = new Map<number, CompetitionBadge>();
  const bookmakers = new Map<number, string>();
  let generatedAt = 0;
  for (const spec of BY_MATCH_MARKETS) {
    for (const page of pages[spec.key] ?? []) {
      generatedAt = Math.max(generatedAt, Date.parse(page.generated_at) || 0);
      for (const c of page.competitions) competitions.set(c.id, c);
      for (const b of page.bookmakers as readonly BookmakerRef[]) bookmakers.set(b.id, b.name);
      for (const row of page.rows) {
        const cell: MatchCell = {
          market: spec.key,
          row,
          info: page.market,
          prices: spec.selections.map((s) => row.selections.find((p) => p.selection === s) ?? null),
        };
        const known = byId.get(row.fixture_id);
        if (known) {
          known.cells[spec.key] = cell;
          known.captured_at = older(known.captured_at, row.captured_at);
          known.stale = known.stale || row.state === "stale";
        } else {
          byId.set(row.fixture_id, {
            fixture_id: row.fixture_id,
            kickoff_at: row.kickoff_at,
            competition_id: row.competition_id,
            home: row.home,
            away: row.away,
            cells: { [spec.key]: cell },
            captured_at: row.captured_at,
            stale: row.state === "stale",
            edge: null,
          });
        }
      }
    }
  }
  const lines = [...byId.values()];
  for (const l of lines) l.edge = lineEdge(l);
  lines.sort(
    (a, b) => Date.parse(a.kickoff_at) - Date.parse(b.kickoff_at) || a.fixture_id - b.fixture_id,
  );
  return { lines, competitions, bookmakers, generatedAt };
}

function lineEdge(line: MatchLine): number | null {
  let best: number | null = null;
  for (const cell of Object.values(line.cells)) {
    if (!cell) continue;
    const e = rowEdge(cell.row);
    if (e !== null && (best === null || e > best)) best = e;
  }
  return best;
}

/** A price PrediGol sees value in: above its fair price, not an outlier. */
export function hasValue(price: OddsSelectionPrice | null): boolean {
  if (!price || price.outlier) return false;
  const e = toNumber(price.price_edge);
  return e !== null && e > 0;
}

export type ByMatchSort = "time" | "value";

export interface ByMatchFilters {
  competition: number | null;
  valueOnly: boolean;
  sort: ByMatchSort;
}

export function filterLines(lines: readonly MatchLine[], f: ByMatchFilters): MatchLine[] {
  const kept = lines.filter(
    (l) =>
      (f.competition === null || l.competition_id === f.competition) &&
      (!f.valueOnly || (l.edge !== null && l.edge > 0)),
  );
  if (f.sort === "value")
    return [...kept].sort(
      (a, b) =>
        (b.edge ?? Number.NEGATIVE_INFINITY) - (a.edge ?? Number.NEGATIVE_INFINITY) ||
        Date.parse(a.kickoff_at) - Date.parse(b.kickoff_at),
    );
  return kept;
}

export interface CompetitionGroup {
  key: string;
  competition: CompetitionBadge | null;
  lines: MatchLine[];
}

/** By kick-off: one group per competition, in the order its first match plays; by value: one list. */
export function groupLines(
  lines: readonly MatchLine[],
  sort: ByMatchSort,
  competitions: ReadonlyMap<number, CompetitionBadge>,
): CompetitionGroup[] {
  if (sort === "value")
    return lines.length ? [{ key: "all", competition: null, lines: [...lines] }] : [];
  const groups = new Map<number, CompetitionGroup>();
  for (const l of lines) {
    const g = groups.get(l.competition_id);
    if (g) g.lines.push(l);
    else
      groups.set(l.competition_id, {
        key: String(l.competition_id),
        competition: competitions.get(l.competition_id) ?? null,
        lines: [l],
      });
  }
  return [...groups.values()];
}

/** The competitions on show, the busiest first: the chips of the sheet. */
export function competitionChips(
  lines: readonly MatchLine[],
  competitions: ReadonlyMap<number, CompetitionBadge>,
): { id: number; name: string; count: number }[] {
  const count = new Map<number, number>();
  for (const l of lines) count.set(l.competition_id, (count.get(l.competition_id) ?? 0) + 1);
  return [...count.entries()]
    .map(([id, n]) => ({ id, name: competitions.get(id)?.name ?? "—", count: n }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
}
