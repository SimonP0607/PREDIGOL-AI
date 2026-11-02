/**
 * Page titles in the reader's language (plan UX, A1, defect F08: "PrediGol — Iniciar sesión" for everyone, an
 * English tagline in a Spanish product). A route's head reads the language the page is served in from the root
 * route's loader (the server's Accept-Language, then the reader's own: requestLocale.ts) and names its page:
 * "Mis picks · PrediGol" / "My picks · PrediGol".
 */
import { isLocale, translate } from "./index";
import type { Locale } from "./catalogs";

/** The language in the root match's loader data (__root.tsx), Spanish if it is not there yet. */
export function localeOfMatches(matches: ReadonlyArray<{ loaderData?: unknown }>): Locale {
  const root = matches[0]?.loaderData as { locale?: unknown } | undefined;
  return isLocale(root?.locale) ? root.locale : "es";
}

export function pageTitle(locale: Locale, key: string): string {
  return `${translate(key, undefined, locale)} · PrediGol`;
}

/** A route's head: its page title, from a catalog key. */
export function titled(key: string) {
  return ({ matches }: { matches: ReadonlyArray<{ loaderData?: unknown }> }) => ({
    meta: [{ title: pageTitle(localeOfMatches(matches), key) }],
  });
}
