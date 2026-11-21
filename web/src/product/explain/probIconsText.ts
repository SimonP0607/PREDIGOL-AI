/**
 * The words of «Probabilidad en iconos» and «Mito o dato» (plan PM, PM-10-07, lámina I09; UX-182; namespace `probicons`): they travel
 * in the match page's chunk, not in the first visit's JS, which cannot grow (UX-139). Every caller translates through this `t`, which
 * adds the namespace before the first lookup: a call, not an import for its side effect, so the bundler cannot drop it.
 */
import { addCatalog, t as translate } from "@/lib/i18n";
import es from "@/locales/es/probicons.json";
import en from "@/locales/en/probicons.json";

export const PROBICONS_CATALOG = { es, en };

let added = false;

/** `t` of `@/lib/i18n`, with the `probicons` namespace loaded. */
export function t(key: string, vars?: Parameters<typeof translate>[1]): string {
  if (!added) {
    addCatalog("probicons", PROBICONS_CATALOG);
    added = true;
  }
  return translate(key, vars);
}

addCatalog("probicons", PROBICONS_CATALOG);
