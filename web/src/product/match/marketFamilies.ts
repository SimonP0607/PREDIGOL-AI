/**
 * AP-P08 (FBI_MARKETS_V3): Mercados by family, as a bookmaker lays them out - Populares, Goles, Mitades, Córners, Tarjetas,
 * Tiros and Más. The catalogue's categories keep their keys; only their order and their words change here, and a family
 * without prices in force is not offered. Pure.
 */
import type { MarketsView } from "./marketCatalog";

/** The families in the order the page lists them: «Populares» is the match's own highlights, «Más» the catalogue's «Resultado». */
export const FAMILY_ORDER: readonly MarketsView[] = [
  "featured",
  "goals",
  "goals_half",
  "corners",
  "cards",
  "shots",
  "result",
];

/** The views on offer in the families' order; one the page does not know goes last, in the order it came. */
export function familyViews(views: readonly MarketsView[]): MarketsView[] {
  const rank = (v: MarketsView) => {
    const i = FAMILY_ORDER.indexOf(v);
    return i < 0 ? FAMILY_ORDER.length : i;
  };
  return [...views].sort((a, b) => rank(a) - rank(b));
}
