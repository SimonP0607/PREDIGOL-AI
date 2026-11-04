/**
 * The reader's markets first in a match's «Mercados» (plan UX, B2; section 26: «desde B2, los mercados que el propio cliente
 * más consulta van primero, con reglas visibles y sin aprendizaje automático»). GET /me/personal says which and why - the
 * markets they consulted two times or more in the last 30 days, most first -; here they go first and the rest keep the usual
 * order. Only the order changes: every market, price and probability is the same for every reader. Pure.
 */
import type { MarketViews } from "@/lib/api/v1/types_personal";
import { intlTag, t } from "@/lib/i18n";
import { marketName } from "@/product/shared/markets";

/** The reader's markets first, in their order; the rest as they came (the usual order). Stable. */
export function orderBoards<B extends { market: string }>(
  boards: readonly B[],
  first: readonly string[],
): B[] {
  if (first.length === 0) return [...boards];
  const rank = new Map(first.map((market, i) => [market, i]));
  return [...boards].sort(
    (a, b) => (rank.get(a.market) ?? first.length) - (rank.get(b.market) ?? first.length),
  );
}

/** «Más/Menos de goles (3) y Ambos marcan (2)»: the reader's markets and how many times they consulted each. */
export function viewsText(views: readonly MarketViews[]): string {
  const parts = views.map((v) => `${marketName(v.market)} (${v.views})`);
  return new Intl.ListFormat(intlTag(), { type: "conjunction" }).format(parts);
}

/** The sentence of the rule, when the reader's order is in use. */
export function orderSentence(views: readonly MarketViews[]): string {
  return t("match.markets.order.mine", { list: viewsText(views) });
}
