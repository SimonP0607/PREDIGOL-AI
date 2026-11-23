/**
 * AP-P08: the one line PrediGol says under a market - «PrediGol 57 % · Casas 51 % · Últimos 20: 7 veces» - read from the
 * marks the API already sends for it (C-14: `market_probs`), never calculated here. It speaks of the selection PrediGol rates
 * highest in the market (the main line of a line market); a market the model does not cover says what the houses and the
 * history say, and nothing of PrediGol. «Estimación preliminar» goes with a model figure that is not calibrated. Pure.
 */
import { present } from "@/lib/api/v1/types_intelligence";
import type { MarketMarks, SelectionMarks } from "@/lib/api/v1/types_stats";
import type { MarketView } from "./marketCatalog";

export interface MarkLine {
  /** The selection the line speaks of (its column's label, with the line for a total). */
  selection: string;
  /** PrediGol's whole percentage; null when the model does not cover the market. */
  model: number | null;
  /** The model's figure is not calibrated: «Estimación preliminar». */
  preliminary: boolean;
  /** The margin-free consensus of the houses, as a whole percentage. */
  houses: number | null;
  /** The history: `hits` of the last `n` matches in the context. */
  history: { hits: number; n: number } | null;
}

/** The marks of a view: the match's own highlights by the market they are, a catalogue market by its key. */
export function marksOf(view: MarketView, marks: readonly MarketMarks[]): MarketMarks | null {
  if (view.key) return marks.find((m) => m.key === view.key) ?? null;
  return marks.find((m) => m.unit === view.parlay && m.period === "FT") ?? null;
}

/** The line a selection of the market sits on, as the view's rows have it (a handicap's away side on its home line's row). */
function rowLine(view: MarketView, s: SelectionMarks): number {
  return view.lines === "ah" && s.selection === "Away" ? -s.line : s.line;
}

function rank(s: SelectionMarks): number {
  return present(s.model)?.pct ?? -1;
}

export function markLine(
  view: MarketView,
  marks: readonly MarketMarks[],
  label: (selection: string, line: number | null) => string,
): MarkLine | null {
  const m = marksOf(view, marks);
  if (!m) return null;
  const main = view.rows[view.main];
  const at = main?.line ?? null;
  const here = m.selections.filter(
    (s) => at === null || Math.abs(rowLine(view, s) - at) < 1e-6 || view.lines === null,
  );
  const pool = here.length ? here : m.selections;
  let top: SelectionMarks | null = null;
  for (const s of pool) {
    const better =
      !top ||
      rank(s) > rank(top) ||
      (rank(s) === rank(top) &&
        (present(s.implied)?.pct ?? -1) > (present(top.implied)?.pct ?? -1));
    if (better) top = s;
  }
  if (!top) return null;
  const model = present(top.model);
  const implied = present(top.implied);
  const history = present(top.history);
  if (!model && !implied && !history) return null;
  return {
    selection: label(top.selection, view.lines === null ? null : at),
    model: model ? model.pct : null,
    preliminary: model !== null && model.calibration !== "calibrada",
    houses: implied ? implied.pct : null,
    history: history ? { hits: history.hits, n: history.n } : null,
  };
}
