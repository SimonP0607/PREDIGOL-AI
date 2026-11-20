/**
 * The words of «información no disponible» and of the availability console (namespace `availability`, plan PM, PM-14-01): they
 * travel in the chunk of the screen that uses them, not in the first visit's JS, which cannot grow (UX-139). Every caller translates
 * through this `t`, which adds the namespace before the first lookup: a call, not an import for its side effect, so the bundler
 * cannot drop it.
 */
import { addCatalog, t as translate } from "@/lib/i18n";
import es from "@/locales/es/availability.json";
import en from "@/locales/en/availability.json";

export const AVAILABILITY_CATALOG = { es, en };

let added = false;

/** `t` of `@/lib/i18n`, with the `availability` namespace loaded. */
export function t(key: string, vars?: Parameters<typeof translate>[1]): string {
  if (!added) {
    addCatalog("availability", AVAILABILITY_CATALOG);
    added = true;
  }
  return translate(key, vars);
}

addCatalog("availability", AVAILABILITY_CATALOG);
