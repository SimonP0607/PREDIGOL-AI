/**
 * Every bookmaker's price of a market, read from GET /matches/{id}/markets (REVIEW PREDIGOL, point 10): the
 * rows of the "Todas las casas" table, where each best price opened, and how a capture is labelled - the same
 * numbers the Cronología shows.
 */
import type { SelectionQuotes } from "@/lib/api/v1/types_profile";
import { t } from "@/lib/i18n";
import { fmtOdds, toNumber } from "@/lib/i18n/format";
import { SELECTIONS } from "./model";

export interface BookCell {
  odds: string;
  opening_odds: string;
  /** The highest price of this selection among the bookmakers: PrediGol gold. */
  best: boolean;
}

export interface BookRow {
  bookmaker: string;
  cells: Array<BookCell | null>;
}

const same = (a: number, b: number) => Math.abs(a - b) < 1e-6;

/** The line each selection of a row is quoted at: AH's away side carries the opposite sign. */
function lineOf(market: string, selection: string, rowLine: number): number {
  if (market === "AH" && selection === "Away") return -rowLine;
  return market === "OU" || market === "AH" ? rowLine : 0;
}

export function bookRows(
  market: string,
  selections: readonly SelectionQuotes[],
  rowLine: number,
): BookRow[] {
  const order = SELECTIONS[market] ?? [];
  const bySel = order.map((sel) =>
    selections.find(
      (s) =>
        s.market_key === market &&
        s.selection === sel &&
        same(toNumber(s.line) ?? 0, lineOf(market, sel, rowLine)),
    ),
  );
  const tops = bySel.map((s) => Math.max(0, ...(s?.books ?? []).map((b) => toNumber(b.odds) ?? 0)));
  const names = new Map<string, BookRow>();
  bySel.forEach((s, i) => {
    for (const b of s?.books ?? []) {
      const row = names.get(b.bookmaker) ?? {
        bookmaker: b.bookmaker,
        cells: order.map(() => null),
      };
      const odds = toNumber(b.odds) ?? 0;
      row.cells[i] = {
        odds: b.odds,
        opening_odds: b.opening_odds,
        best: odds > 0 && same(odds, tops[i] ?? 0),
      };
      names.set(b.bookmaker, row);
    }
  });
  return [...names.values()].sort((a, b) => a.bookmaker.localeCompare(b.bookmaker));
}

/** "abrió 2,10": where the best price of a selection opened, when it is not where it is now. */
export function openingNote(
  selections: readonly SelectionQuotes[],
  selection: string,
  line: number,
  bestNow: string,
): string | null {
  const s = selections.find((x) => x.selection === selection && same(toNumber(x.line) ?? 0, line));
  if (!s || s.books.length === 0) return null;
  const opened = Math.max(...s.books.map((b) => toNumber(b.opening_odds) ?? 0));
  const now = toNumber(bestNow);
  if (!opened || now === null || same(opened, now)) return null;
  return t("match.books.opened", { odds: fmtOdds(opened) });
}

/** T-72 h, T-3 h, T-25 min: how far from kick-off a capture was taken. */
export function captureLabel(minutesToKickoff: number): string {
  if (minutesToKickoff < 0) return `T+${-minutesToKickoff} min`;
  if (minutesToKickoff >= 60) return `T-${Math.round(minutesToKickoff / 60)} h`;
  return `T-${minutesToKickoff} min`;
}
