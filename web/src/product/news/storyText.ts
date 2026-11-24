/**
 * The words of the news as stories (namespace `stories`, plan de correcciones UX, AP-N01 to AP-N06): they travel with the news
 * pages' chunk, not in the first visit's JS. Translate through this `t`, which adds the namespace before the first lookup.
 */
import { addCatalog, t as translate } from "@/lib/i18n";
import es from "@/locales/es/stories.json";
import en from "@/locales/en/stories.json";

export const STORIES_CATALOG = { es, en };

let added = false;

/** `t` of `@/lib/i18n`, with the `stories` namespace loaded. */
export function t(key: string, vars?: Parameters<typeof translate>[1]): string {
  if (!added) {
    addCatalog("stories", STORIES_CATALOG);
    added = true;
  }
  return translate(key, vars);
}

addCatalog("stories", STORIES_CATALOG);
