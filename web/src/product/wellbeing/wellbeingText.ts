/**
 * The words of «solo fútbol» and the voluntary pause (namespace `wellbeing`, plan PM, PM-14-07): they travel in the chunk of the
 * screen that uses them (Perfil, the page of a reader who sees no prices), not in the first visit's JS, which cannot grow (UX-139).
 * Every caller translates through this `t`, which adds the namespace before the first lookup.
 */
import { addCatalog, t as translate } from "@/lib/i18n";
import es from "@/locales/es/wellbeing.json";
import en from "@/locales/en/wellbeing.json";

export const WELLBEING_CATALOG = { es, en };

let added = false;

/** `t` of `@/lib/i18n`, with the `wellbeing` namespace loaded. */
export function t(key: string, vars?: Parameters<typeof translate>[1]): string {
  if (!added) {
    addCatalog("wellbeing", WELLBEING_CATALOG);
    added = true;
  }
  return translate(key, vars);
}

addCatalog("wellbeing", WELLBEING_CATALOG);
