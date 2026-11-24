/**
 * The words of the markets as in a bookmaker (namespace `marketsv3`, plan de correcciones UX, AP-P08): they travel with the match
 * page's chunk, not in the first visit's JS. Translate through this `t`, which adds the namespace before the first lookup.
 */
import { addCatalog, t as translate } from "@/lib/i18n";
import es from "@/locales/es/marketsv3.json";
import en from "@/locales/en/marketsv3.json";

export const MARKETS_V3_CATALOG = { es, en };

let added = false;

/** `t` of `@/lib/i18n`, with the `marketsv3` namespace loaded. */
export function t(key: string, vars?: Parameters<typeof translate>[1]): string {
  if (!added) {
    addCatalog("marketsv3", MARKETS_V3_CATALOG);
    added = true;
  }
  return translate(key, vars);
}

addCatalog("marketsv3", MARKETS_V3_CATALOG);
