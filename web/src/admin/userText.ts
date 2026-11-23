/**
 * The words of the user's file and of the views of «Usuarios» (namespace `userfile`, plan Correcciones UX, AP-A03). They travel in
 * the chunk of the console screen that shows them, not in the first visit's JS (the boot cannot grow). Keys are written whole:
 * `userfile.tabs.account`.
 */
import { addCatalog, t as translate } from "@/lib/i18n";
import es from "@/locales/es/userfile.json";
import en from "@/locales/en/userfile.json";

export const USERFILE_CATALOG = { es, en };

let added = false;

/** `t` of `@/lib/i18n`, with the `userfile` namespace loaded. */
export function t(key: string, vars?: Parameters<typeof translate>[1]): string {
  if (!added) {
    addCatalog("userfile", USERFILE_CATALOG);
    added = true;
  }
  return translate(key, vars);
}

addCatalog("userfile", USERFILE_CATALOG);
