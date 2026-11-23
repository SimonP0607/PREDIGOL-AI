/**
 * The words of the reader's chart language (namespace `readchart`, plan Correcciones UX, AP-T03): plain titles, axis notes and the
 * «cómo leerlo» sentences. They travel in the chunk of the screen that draws the chart, not in the first visit's JS (as `evidence`).
 */
import { addCatalog, t as translate } from "@/lib/i18n";
import es from "@/locales/es/readchart.json";
import en from "@/locales/en/readchart.json";

export const READCHART_CATALOG = { es, en };

let added = false;

/** `t` of `@/lib/i18n`, with the `readchart` namespace loaded (keys are written whole: `readchart.perf.title`). */
export function t(key: string, vars?: Parameters<typeof translate>[1]): string {
  if (!added) {
    addCatalog("readchart", READCHART_CATALOG);
    added = true;
  }
  return translate(key, vars);
}

addCatalog("readchart", READCHART_CATALOG);
