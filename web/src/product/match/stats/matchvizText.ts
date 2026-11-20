/**
 * The words of the Match Center's new pieces of plan PM, block 10 (namespace `matchviz`: the shot funnel and its two zones,
 * PM-10-01; FE-005): they travel in the match page's chunk, not in the first visit's JS, which cannot grow (UX-139). Every caller
 * translates through this `t`, which adds the namespace before the first lookup: a call, not an import for its side effect, so the
 * bundler cannot drop it.
 */
import { addCatalog, t as translate } from "@/lib/i18n";
import es from "@/locales/es/matchviz.json";
import en from "@/locales/en/matchviz.json";

export const MATCHVIZ_CATALOG = { es, en };

let added = false;

/** `t` of `@/lib/i18n`, with the `matchviz` namespace loaded. */
export function t(key: string, vars?: Parameters<typeof translate>[1]): string {
  if (!added) {
    addCatalog("matchviz", MATCHVIZ_CATALOG);
    added = true;
  }
  return translate(key, vars);
}

addCatalog("matchviz", MATCHVIZ_CATALOG);
