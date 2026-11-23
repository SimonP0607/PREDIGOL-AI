/**
 * The words of the learning page's flow diagram (namespace `pipeline`, plan de correcciones UX, AP-A08): they travel with the page's
 * chunk, not in the first visit's JS. Translate through this `t`, which adds the namespace before the first lookup.
 */
import { addCatalog, t as translate } from "@/lib/i18n";
import es from "@/locales/es/pipeline.json";
import en from "@/locales/en/pipeline.json";

export const PIPELINE_CATALOG = { es, en };

let added = false;

/** `t` of `@/lib/i18n`, with the `pipeline` namespace loaded. */
export function t(key: string, vars?: Parameters<typeof translate>[1]): string {
  if (!added) {
    addCatalog("pipeline", PIPELINE_CATALOG);
    added = true;
  }
  return translate(key, vars);
}

addCatalog("pipeline", PIPELINE_CATALOG);
