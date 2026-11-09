/**
 * «Comparar casas» (plan Cuotas, section 5, after OddsPortal): every bookmaker's price of the row's line, one column per
 * selection, with each bookmaker's margin - its cut, what its prices add up to above a fair book. Pure.
 *
 * A margin is only worked out where it means something: an exhaustive market (its selections cover every outcome) that the
 * bookmaker quotes in full. A double chance's three selections cover every outcome twice, so its book is halved first.
 */
import { toNumber } from "@/lib/i18n/format";
import { parseMarketKey } from "./markets";
import type {
  BookmakerRef,
  MatchOddsBook,
  OddsBookLine,
  OddsBookMarket,
  OddsMarketInfo,
  OddsSelectionPrice,
} from "./model";
import { sameLine } from "./rows";

/** The book's market for this key and period. */
export function bookMarket(
  book: MatchOddsBook | undefined,
  key: string,
  period: string,
): OddsBookMarket | null {
  for (const family of book?.families ?? []) {
    const m = family.markets.find((x) => x.info.key === key && x.period === period);
    if (m) return m;
  }
  return null;
}

/** The line of the row on show (an Asian handicap's home line), else the book's main line. */
export function bookLine(market: OddsBookMarket | null, line: string | null): OddsBookLine | null {
  if (!market) return null;
  return (
    market.lines.find((l) => sameLine(l.line, line)) ??
    market.lines.find((l) => sameLine(l.line, market.main_line)) ??
    null
  );
}

function isDoubleChance(info: Pick<OddsMarketInfo, "key">): boolean {
  return parseMarketKey(info.key).base.endsWith(".double_chance");
}

/**
 * A bookmaker's margin on one line: Σ 1/odds − 1 (halved for a double chance), or null when it does not quote every
 * selection, or the market is not exhaustive (no fair book to be above).
 */
export function bookMargin(
  info: Pick<OddsMarketInfo, "key" | "fair">,
  odds: ReadonlyArray<string | null>,
): number | null {
  if (!info.fair || odds.length < 2) return null;
  let sum = 0;
  for (const o of odds) {
    const n = toNumber(o);
    if (n === null || n <= 1) return null;
    sum += 1 / n;
  }
  return (isDoubleChance(info) ? sum / 2 : sum) - 1;
}

export interface CompareCell {
  odds: string | null;
  /** The highest price of the column: the best price. */
  best: boolean;
}

export interface CompareRow {
  bookmaker_id: number;
  bookmaker: string;
  cells: CompareCell[];
  margin: number | null;
}

export interface CompareGrid {
  selections: OddsSelectionPrice[];
  rows: CompareRow[];
}

/** The grid: bookmakers by name, each price where it quotes one, the best of each column marked. */
export function compareGrid(
  info: Pick<OddsMarketInfo, "key" | "fair">,
  line: OddsBookLine,
  bookmakers: readonly BookmakerRef[],
): CompareGrid {
  const names = new Map(bookmakers.map((b) => [b.id, b.name]));
  const tops = line.selections.map((_, i) =>
    Math.max(0, ...line.books.map((b) => toNumber(b.odds[i] ?? null) ?? 0)),
  );
  const rows = line.books.map((b) => ({
    bookmaker_id: b.bookmaker_id,
    bookmaker: names.get(b.bookmaker_id) ?? `#${b.bookmaker_id}`,
    cells: line.selections.map((_, i) => {
      const odds = b.odds[i] ?? null;
      const n = toNumber(odds);
      return { odds, best: n !== null && n > 0 && Math.abs(n - (tops[i] ?? 0)) < 1e-9 };
    }),
    margin: bookMargin(
      info,
      line.selections.map((_, i) => b.odds[i] ?? null),
    ),
  }));
  rows.sort((a, b) => a.bookmaker.localeCompare(b.bookmaker));
  return { selections: line.selections, rows };
}
