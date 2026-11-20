/**
 * The words of a competition's page, the directory and the calculator (namespace `competitions`, plan PM, PM-09-03 to PM-09-05):
 * they travel in the chunk of the screen that uses them, not in the first visit's JS, which cannot grow (UX-139). Every caller
 * translates through this `t`, which adds the namespace before the first lookup.
 */
import { addCatalog, t as translate } from "@/lib/i18n";
import es from "@/locales/es/competitions.json";
import en from "@/locales/en/competitions.json";

export const COMPETITIONS_CATALOG = { es, en };

let added = false;

/** `t` of `@/lib/i18n`, with the `competitions` namespace loaded. */
export function t(key: string, vars?: Parameters<typeof translate>[1]): string {
  if (!added) {
    addCatalog("competitions", COMPETITIONS_CATALOG);
    added = true;
  }
  return translate(key, vars);
}

addCatalog("competitions", COMPETITIONS_CATALOG);
