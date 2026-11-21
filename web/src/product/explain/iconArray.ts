/**
 * «Probabilidad en iconos» (plan PM, PM-10-07, OP-45; lámina I09 «M08»; UX-182): the result forecast PrediGol already shows as bars,
 * counted in 100 icons - «de cada 100 partidos como este…». Pure: no React, no fetching. It explains a published figure and computes
 * none: each whole percentage the bars show is a number of icons, in a fixed order (home, draw, away) so that the part and the whole
 * are seen at once (frequency formats, Gigerenzer et al. 2005).
 *
 * The contract (ficha PM-10-07, field 9): no icons unless the probability is calibrated and authorised - state 5 of C-16 («calibrada y
 * autorizada»: a validated calibrator, `basis` «champion», and readers may see the forecast, which the API decides before sending it).
 * A market that is not the result (1X2), that lacks one of its three outcomes or brings a number that is not a probability gets no
 * icons: the bars stay, as they were.
 */
import { toNumber } from "@/lib/i18n/format";
import type { ChartReview } from "@/components/analytics/evidence";
import type { ForecastMarket, ForecastOutcome } from "@/lib/api/v1/types_forecast";

export type IconSide = "home" | "draw" | "away";

/** The three sides in the order the icons are laid out and the legend reads. */
export const ICON_SIDES: readonly IconSide[] = ["home", "draw", "away"] as const;

/** How many icons the grid has: a fixed denominator of 100. */
export const ICON_TOTAL = 100;

/** Icons per row: a 10 × 10 grid. */
export const ICONS_PER_ROW = 10;

export interface IconCounts {
  home: number;
  draw: number;
  away: number;
  /**
   * The three whole percentages the bars show did not add up to 100 (33 + 33 + 33): the icons follow the largest remainders and one
   * side shows one icon more (or fewer) than its bar - and the page says so, instead of drawing 99 or 101 icons.
   */
  adjusted: boolean;
}

/** The side of a result outcome as the API names it (`Home`, `Draw`, `Away`; `1`, `X`, `2` as well), or null. */
export function sideOf(selection: string): IconSide | null {
  const s = selection.trim().toLowerCase();
  if (s === "home" || s === "1") return "home";
  if (s === "draw" || s === "x") return "draw";
  if (s === "away" || s === "2") return "away";
  return null;
}

/**
 * The whole percentage a bar shows for a probability, rounded as `fmtPct(p, 0)` rounds it (Intl: half away from zero on the decimal
 * the number reads as, so 0.145 → 15 although 0.145 × 100 is 14.4999… in binary).
 */
export function shownPercent(p: number): number {
  return Math.round(Number((p * 100).toPrecision(12)));
}

/**
 * Whether a market may be drawn in icons: the result (1X2), calibrated with a validated calibrator (state 5 of C-16). Everything
 * else keeps its bars.
 */
export function iconsAllowed(
  market: Pick<ForecastMarket, "market" | "calibration" | "basis">,
): boolean {
  return (
    market.market === "1X2" && market.calibration === "CALIBRATED" && market.basis === "champion"
  );
}

/**
 * The icons of each side from the probabilities the API sent, or null when they cannot be drawn honestly (a side missing or
 * repeated, a number that is not a probability, three probabilities that do not add up to one within a whole point).
 */
export function iconCounts(
  outcomes: readonly Pick<ForecastOutcome, "selection" | "probability">[],
): IconCounts | null {
  const p: Partial<Record<IconSide, number>> = {};
  for (const o of outcomes) {
    const side = sideOf(o.selection);
    const n = toNumber(o.probability);
    if (side === null || n === null || !Number.isFinite(n) || n < 0 || n > 1) return null;
    if (p[side] !== undefined) return null;
    p[side] = n;
  }
  if (p.home === undefined || p.draw === undefined || p.away === undefined) return null;
  const sum = p.home + p.draw + p.away;
  if (Math.abs(sum - 1) > 0.01) return null;
  const shown: Record<IconSide, number> = {
    home: shownPercent(p.home),
    draw: shownPercent(p.draw),
    away: shownPercent(p.away),
  };
  const total = shown.home + shown.draw + shown.away;
  if (total === ICON_TOTAL) return { ...shown, adjusted: false };
  // Largest remainders on the exact numbers: the closest 100 icons to what the model said, never a new estimate.
  const exact = ICON_SIDES.map((side) => ({ side, v: ((p[side] as number) / sum) * ICON_TOTAL }));
  const floors = exact.map((e) => ({ side: e.side, n: Math.floor(e.v), r: e.v - Math.floor(e.v) }));
  let left = ICON_TOTAL - floors.reduce((a, f) => a + f.n, 0);
  const order = [...floors].sort(
    (a, b) => b.r - a.r || ICON_SIDES.indexOf(a.side) - ICON_SIDES.indexOf(b.side),
  );
  for (const f of order) {
    if (left <= 0) break;
    f.n += 1;
    left -= 1;
  }
  const out: Record<IconSide, number> = { home: 0, draw: 0, away: 0 };
  for (const f of floors) out[f.side] = f.n;
  return { ...out, adjusted: true };
}

/** The 100 cells of the grid, row by row: the home side's icons first, then the draws, then the away side's. */
export function iconCells(counts: Pick<IconCounts, IconSide>): IconSide[] {
  const cells: IconSide[] = [];
  for (const side of ICON_SIDES) for (let i = 0; i < counts[side]; i++) cells.push(side);
  return cells.slice(0, ICON_TOTAL);
}

/**
 * The hand review of the 14 critical checks of FE-004 (PM-10-06) for the icons. It is not an `EvidenceChart`: that card states the
 * evidence of a statistic (n, Wilson's interval, the league's value), and this counts a forecast already shown as bars, with its
 * interval in the sentence under it; the review is kept to the same standard and tested with `reviewProblems`.
 */
export const PROB_ICONS_REVIEW: ChartReview = {
  checks: {
    contraste: "ok",
    alternativa_textual: "ok",
    texto_minimo: "ok",
    sin_parpadeo: "ok",
    color_no_unico: "ok",
    teclado: "ok",
    foco_visible: "ok",
    instrucciones: "ok",
    titulo_y_resumen: "ok",
    incertidumbre: "ok",
    lenguaje_llano: "ok",
    tabla_equivalente: "ok",
    zoom_y_espaciado: "ok",
    lector_de_pantalla: "ok",
  },
  reviewedBy: "PM-10-07 (UX-182)",
  reviewedOn: "2026-11-21",
};
