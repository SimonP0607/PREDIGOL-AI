/**
 * The words of the owner's console of the provider's requests (namespace `usage`, plan PM, PM-04-05; UX-175): they travel in the
 * console's chunk, not in the first visit's JS (UX-139). Translate through this `t`, which adds the namespace before the first lookup.
 */
import { addCatalog, t as translate } from "@/lib/i18n";
import es from "@/locales/es/usage.json";
import en from "@/locales/en/usage.json";

export const USAGE_CATALOG = { es, en };

let added = false;

/** `t` of `@/lib/i18n`, with the `usage` namespace loaded. */
export function t(key: string, vars?: Parameters<typeof translate>[1]): string {
  if (!added) {
    addCatalog("usage", USAGE_CATALOG);
    added = true;
  }
  return translate(key, vars);
}

addCatalog("usage", USAGE_CATALOG);
