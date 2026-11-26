/**
 * The words of the owner's list of what the help could not answer (namespace `helpgaps`, plan de correcciones UX, AP-H02): they travel in the
 * console's chunk, not in the first visit's JS. Translate through this `t`, which adds the namespace before the first lookup.
 */
import { addCatalog, t as translate } from "@/lib/i18n";
import es from "@/locales/es/helpgaps.json";
import en from "@/locales/en/helpgaps.json";

export const HELPGAPS_CATALOG = { es, en };

let added = false;

/** `t` of `@/lib/i18n`, with the `helpgaps` namespace loaded. */
export function t(key: string, vars?: Parameters<typeof translate>[1]): string {
  if (!added) {
    addCatalog("helpgaps", HELPGAPS_CATALOG);
    added = true;
  }
  return translate(key, vars);
}

addCatalog("helpgaps", HELPGAPS_CATALOG);
