/**
 * The words of the evidence label and the reading sentence of a chart (namespace `evidence`, plan PM, PM-10-06; FE-004): they travel
 * in the chunk of the screen that draws the chart, not in the first visit's JS (UX-139). Translate through this `t`.
 */
import { addCatalog, t as translate } from "@/lib/i18n";
import es from "@/locales/es/evidence.json";
import en from "@/locales/en/evidence.json";

export const EVIDENCE_CATALOG = { es, en };

let added = false;

/** `t` of `@/lib/i18n`, with the `evidence` namespace loaded. */
export function t(key: string, vars?: Parameters<typeof translate>[1]): string {
  if (!added) {
    addCatalog("evidence", EVIDENCE_CATALOG);
    added = true;
  }
  return translate(key, vars);
}

addCatalog("evidence", EVIDENCE_CATALOG);
