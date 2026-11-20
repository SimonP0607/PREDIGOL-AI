/**
 * The words of the player's profile with the new data (namespace `players`, plan PM, PM-08-06): they travel in the chunk of the
 * profile, not in the first visit's JS, which cannot grow (UX-139).
 */
import { addCatalog, t as translate } from "@/lib/i18n";
import es from "@/locales/es/players.json";
import en from "@/locales/en/players.json";

export const PLAYERS_CATALOG = { es, en };

let added = false;

/** `t` of `@/lib/i18n`, with the `players` namespace loaded. */
export function t(key: string, vars?: Parameters<typeof translate>[1]): string {
  if (!added) {
    addCatalog("players", PLAYERS_CATALOG);
    added = true;
  }
  return translate(key, vars);
}

addCatalog("players", PLAYERS_CATALOG);
