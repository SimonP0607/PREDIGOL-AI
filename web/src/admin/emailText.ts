/**
 * The words of the console's e-mail preview (namespace `emailpreview`, plan de correcciones UX, AP-M02): they travel in the
 * Messages page's chunk, not in the first visit's JS. Translate through this `t`, which adds the namespace before the first lookup.
 */
import { addCatalog, t as translate } from "@/lib/i18n";
import es from "@/locales/es/emailpreview.json";
import en from "@/locales/en/emailpreview.json";

export const EMAIL_PREVIEW_CATALOG = { es, en };

let added = false;

/** `t` of `@/lib/i18n`, with the `emailpreview` namespace loaded. */
export function t(key: string, vars?: Parameters<typeof translate>[1]): string {
  if (!added) {
    addCatalog("emailpreview", EMAIL_PREVIEW_CATALOG);
    added = true;
  }
  return translate(key, vars);
}

addCatalog("emailpreview", EMAIL_PREVIEW_CATALOG);
