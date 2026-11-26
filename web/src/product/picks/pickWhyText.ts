/**
 * The words around the server's reason and highlight in «¿Por qué este pick?» (namespace `pickwhy`, C-02 1.1, AP-K06): they
 * travel in the pick's chunk, not in the first visit's JS. Translate through this `t`, which adds the namespace before the
 * first lookup.
 */
import { addCatalog, t as translate } from "@/lib/i18n";
import es from "@/locales/es/pickwhy.json";
import en from "@/locales/en/pickwhy.json";

export const PICK_WHY_CATALOG = { es, en };

let added = false;

/** `t` of `@/lib/i18n`, with the `pickwhy` namespace loaded. */
export function t(key: string, vars?: Parameters<typeof translate>[1]): string {
  if (!added) {
    addCatalog("pickwhy", PICK_WHY_CATALOG);
    added = true;
  }
  return translate(key, vars);
}

addCatalog("pickwhy", PICK_WHY_CATALOG);
