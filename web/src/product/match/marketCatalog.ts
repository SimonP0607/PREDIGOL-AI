/**
 * The Mercados tab before kick-off by category (plan Partidos y Match Center, F4b: M1-M4). Pure.
 *
 * One shape for every market on show, whichever its source: «Destacados» are the five markets of the match itself
 * (GET /matches/{id}, the ones that are settled and go to the parlay), the categories are the catalogue's
 * (GET /matches/{id}/markets/catalog?category=, each price the one IN FORCE). A market is its rows - one per line, the
 * main one first in view -, each selection's best price with its bookmaker and since when, and every bookmaker's price.
 *
 * The API names a market by stable keys (code, period, subject, selection); the words are here, in the reader's
 * language, and a key without a translation reads as a generic text, never as the key itself.
 */
import type { SelectionQuotes } from "@/lib/api/v1/types_profile";
import type {
  CatalogCategory,
  MarketCatalogCategory,
  MarketCatalogMarket,
  MarketCatalogSelection,
} from "@/lib/api/v1/types_market_catalog";
import { t, translateOr } from "@/lib/i18n";
import { fmtLine, toNumber } from "@/lib/i18n/format";
import { MARKETS, marketName } from "@/product/shared/markets";
import { bookRows, openingNote } from "./books";
import { SELECTIONS, tileLabel, type BestPrice, type MarketBoard } from "./model";

type Sides = { home: string; away: string };

/** «Destacados» and the catalogue's categories: what the chips switch between. */
export type MarketsView = "featured" | CatalogCategory;

/** The highlights, in this order: 1X2, over/under 2.5 and both teams score. */
export const FEATURED: readonly string[] = ["1X2", "OU", "BTTS"];
/** The other two of the five: in «Resultado», or among the highlights while the catalogue has no «Resultado». */
const RESULT_FIVE: readonly string[] = ["AH", "DC"];
/** The over/under line the highlights open on. */
export const FEATURED_OU_LINE = 2.5;

const FIVE = new Set<string>(MARKETS);

/** One bookmaker's price of a selection, in the «Ver todas las casas» table. */
export interface BookPrice {
  odds: string;
  /** In force at least since then (the catalogue); null where it is not known. */
  since: string | null;
  /** The first price we saw from this bookmaker (the five markets only): the arrow beside the price. */
  firstSeen: string | null;
  /** The highest price of the selection among the bookmakers: PrediGol gold. */
  best: boolean;
}

export interface BookLine {
  bookmaker: string;
  cells: Array<BookPrice | null>;
}

export interface ViewRow {
  key: string;
  /** Over/under: the total; handicap: the home side's; null for a market without lines. */
  line: number | null;
  cells: Array<BestPrice | null>;
  /** Every bookmaker's price of this row's selections (empty when not loaded). */
  books: BookLine[];
  /** Under a tile, per cell: «primera cuota vista 2,10» when the best price is no longer the first one seen. */
  notes?: Array<string | null> | undefined;
}

export interface ViewColumn {
  selection: string;
  /** What heads the column of a line table, or names the tile. */
  label: string;
}

export interface MarketView {
  /** The market's identity on the page: 1X2, OU... for the five; the catalogue's key for the others. */
  id: string;
  /** The catalogue's key (`code.period.subject`): what a link from Cuotas names. Empty for the match's own highlights. */
  key: string;
  title: string;
  /** 90', 1.ª parte, 2.ª parte (the catalogue's markets). */
  period: string | null;
  /** One of the five settled markets: its prices go to the parlay and can be saved. Null: shown, never settled. */
  parlay: string | null;
  /** How the rows read: "ou" a total per row, "ah" a handicap per row, null a single row of selections. */
  lines: "ou" | "ah" | null;
  columns: ViewColumn[];
  rows: ViewRow[];
  /** The row shown first (the most balanced line, or the one the highlights ask for). */
  main: number;
  /** Bookmakers that price the market. */
  books: number;
}

const same = (a: number, b: number) => Math.abs(a - b) < 1e-6;

/** The row whose first two prices are closest; otherwise the one most bookmakers quote. */
export function mainRow(rows: ReadonlyArray<{ cells: Array<BestPrice | null> }>): number {
  let best = -1;
  let gap = Infinity;
  rows.forEach((r, i) => {
    const a = toNumber(r.cells[0]?.odds);
    const b = toNumber(r.cells[1]?.odds);
    if (a === null || b === null || a <= 0 || b <= 0) return;
    const g = Math.abs(Math.log(a / b));
    if (g < gap) {
      gap = g;
      best = i;
    }
  });
  if (best >= 0) return best;
  const quoted = (r: { cells: Array<BestPrice | null> }) =>
    r.cells.reduce((n, c) => n + (c?.books ?? 0), 0);
  return rows.reduce((bi, r, i, all) => (quoted(r) > quoted(all[bi] ?? r) ? i : bi), 0);
}

// ── words ──────────────────────────────────────────────────────────────────────────────────────

/** «Más/menos córners · Valencia (local)»: the market's name and, for a team's market, the team. */
export function catalogTitle(
  m: Pick<MarketCatalogMarket, "code" | "subject">,
  sides: Sides,
): string {
  const name = translateOr(`match.catalog.market.${m.code}`, t("match.catalog.market.other"));
  if (m.subject !== "home" && m.subject !== "away") return name;
  const team = m.subject === "home" ? sides.home : sides.away;
  return `${name} · ${t(`match.catalog.subject.${m.subject}`, { team })}`;
}

/** 90', 1.ª parte, 2.ª parte; a period without a translation reads as «Otro período». */
export function periodLabel(period: string): string {
  return translateOr(`match.catalog.period.${period}`, t("match.catalog.period.other"));
}

/** The words of the provider's half-time/full-time pairs («Home/Draw»): each side named. */
function sideWord(word: string, sides: Sides): string | null {
  if (word === "Home") return sides.home;
  if (word === "Away") return sides.away;
  if (word === "Draw") return t("common.draw");
  return null;
}

/**
 * A selection of a catalogue market in the reader's words: «Valencia», «Más de 9,5», «Valencia o empate», «Impar»,
 * «Valencia / Empate». `index` names one without a translation («Opción 2»), never the provider's key.
 */
export function catalogSelection(
  kind: string,
  selection: string,
  line: number | null,
  sides: Sides,
  index: number,
): string {
  const lineText = line === null ? "" : fmtLine(line, kind === "asian_handicap");
  if (kind === "half_time_full_time") {
    const [ht, ft, ...rest] = selection.split("/").map((w) => w.trim());
    const a = ht ? sideWord(ht, sides) : null;
    const b = ft ? sideWord(ft, sides) : null;
    if (a && b && rest.length === 0) return t("match.catalog.selection.htft", { ht: a, ft: b });
  }
  return translateOr(
    `match.catalog.selection.${kind}.${selection}`,
    t("match.catalog.selection.other", { n: index + 1 }),
    { home: sides.home, away: sides.away, line: lineText },
  ).trim();
}

// ── the five markets of the match ──────────────────────────────────────────────────────────────

function boardBooks(market: string, all: readonly SelectionQuotes[], line: number): BookLine[] {
  return bookRows(market, all, line).map((r) => ({
    bookmaker: r.bookmaker,
    cells: r.cells.map((c) =>
      c ? { odds: c.odds, since: null, firstSeen: c.opening_odds, best: c.best } : null,
    ),
  }));
}

/**
 * One of the five, from the match's own prices (the ones the parlay settles). `all` is every bookmaker's price
 * (GET /matches/{id}/markets) when it has loaded; `mainLine` the line to open on when the market has it.
 */
export function boardView(
  board: MarketBoard,
  all: readonly SelectionQuotes[] | null,
  sides: Sides,
  mainLine?: number,
): MarketView {
  const market = board.market;
  const lines = market === "OU" ? "ou" : market === "AH" ? "ah" : null;
  const sels = SELECTIONS[market] ?? [];
  const mine = all?.filter((s) => s.market_key === market) ?? [];
  const asked =
    mainLine === undefined ? -1 : board.rows.findIndex((r) => same(r.line ?? NaN, mainLine));
  return {
    id: market,
    key: "",
    title: marketName(market),
    period: null,
    parlay: market,
    lines,
    columns: sels.map((s) => ({
      selection: s,
      label:
        lines === "ou"
          ? s === "Over"
            ? t("match.markets.over")
            : t("match.markets.under")
          : lines === "ah"
            ? s === "Home"
              ? sides.home
              : sides.away
            : tileLabel(market, s, null, sides),
    })),
    rows: board.rows.map((r) => ({
      key: r.key,
      line: r.line,
      cells: r.cells,
      books: boardBooks(market, mine, r.line ?? 0),
      notes:
        lines === null
          ? r.cells.map((c) => (c ? openingNote(mine, c.selection, 0, c.odds) : null))
          : undefined,
    })),
    main: asked >= 0 ? asked : board.main,
    books: board.books,
  };
}

/**
 * «Destacados»: 1X2, over/under (on 2.5 when it is priced) and both teams score, in the reader's order when they keep
 * one. Handicap and double chance join them while the catalogue has no «Resultado» to hold them (`resultInCatalog`
 * false: loaded without it, or failed), so no market that was on show disappears; null while it loads.
 */
export function featuredBoards(
  boards: readonly MarketBoard[],
  resultInCatalog: boolean | null,
): MarketBoard[] {
  const wanted = resultInCatalog === false ? [...FEATURED, ...RESULT_FIVE] : FEATURED;
  return boards.filter((b) => wanted.includes(b.market));
}

// ── the catalogue ──────────────────────────────────────────────────────────────────────────────

function catalogPrice(market: MarketCatalogMarket, s: MarketCatalogSelection): BestPrice {
  return {
    market: market.market_key ?? market.key,
    selection: s.selection,
    line: toNumber(s.line) ?? 0,
    odds: s.best_odds,
    bookmaker: s.bookmaker,
    books: s.bookmakers,
    capturedAt: s.captured_at,
  };
}

function catalogBooks(cells: ReadonlyArray<MarketCatalogSelection | null>): BookLine[] {
  const names = new Map<string, BookLine>();
  cells.forEach((s, i) => {
    const top = toNumber(s?.best_odds) ?? 0;
    for (const b of s?.books ?? []) {
      const row = names.get(b.bookmaker) ?? {
        bookmaker: b.bookmaker,
        cells: cells.map(() => null),
      };
      const odds = toNumber(b.odds) ?? 0;
      row.cells[i] = {
        odds: b.odds,
        since: b.captured_at,
        firstSeen: null,
        best: odds > 0 && same(odds, top),
      };
      names.set(b.bookmaker, row);
    }
  });
  return [...names.values()].sort((a, b) => a.bookmaker.localeCompare(b.bookmaker));
}

/**
 * A catalogue market as shown: its selections in the API's order as columns, one row per line (a handicap's away side on
 * its home line's row), the most balanced line first in view. The five settled markets keep their parlay key.
 */
export function catalogView(m: MarketCatalogMarket, sides: Sides): MarketView {
  const lines = !m.has_line ? null : m.kind === "asian_handicap" ? "ah" : "ou";
  const order: string[] = [];
  for (const s of m.selections) if (!order.includes(s.selection)) order.push(s.selection);
  const byRow = new Map<number, Array<MarketCatalogSelection | null>>();
  for (const s of m.selections) {
    const line = toNumber(s.line) ?? 0;
    const rowLine = lines === null ? 0 : lines === "ah" && s.selection === "Away" ? -line : line;
    const key = Math.round(rowLine * 100) / 100;
    const cells = byRow.get(key) ?? order.map(() => null);
    cells[order.indexOf(s.selection)] = s;
    byRow.set(key, cells);
  }
  const rows: ViewRow[] = [...byRow.entries()]
    .sort(([a], [b]) => a - b)
    .map(([line, cells]) => ({
      key: `${m.key}|${line}`,
      line: lines === null ? null : line,
      cells: cells.map((s) => (s ? catalogPrice(m, s) : null)),
      books: catalogBooks(cells),
    }));
  const parlay = m.market_key && FIVE.has(m.market_key) ? m.market_key : null;
  return {
    id: parlay ?? m.key,
    key: m.key,
    title: catalogTitle(m, sides),
    period: periodLabel(m.period),
    parlay,
    lines,
    columns: order.map((s, i) => ({
      selection: s,
      label:
        lines === "ou"
          ? s === "Over"
            ? t("match.markets.over")
            : s === "Under"
              ? t("match.markets.under")
              : catalogSelection(m.kind, s, null, sides, i)
          : catalogSelection(m.kind, s, null, sides, i),
    })),
    rows,
    main: mainRow(rows),
    books: m.bookmakers,
  };
}

/** «Ver 6 líneas más»: the rows a market keeps behind its main line. */
export function hiddenLines(view: Pick<MarketView, "rows" | "lines">): number {
  return view.lines === null ? 0 : Math.max(0, view.rows.length - 1);
}

/** The bookmakers the page names in its header: the most any category or the match's own prices have in force. */
export function headerBooks(
  matchBooks: number,
  categories: readonly MarketCatalogCategory[] | null | undefined,
): number {
  return Math.max(matchBooks, ...(categories ?? []).map((c) => c.bookmakers));
}

/** The later of two instants (ISO), either of which may be missing. */
export function later(a: string | null | undefined, b: string | null | undefined): string | null {
  if (!a) return b ?? null;
  if (!b) return a;
  return Date.parse(a) >= Date.parse(b) ? a : b;
}
