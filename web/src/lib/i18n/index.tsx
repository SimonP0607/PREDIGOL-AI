/**
 * Spanish and English from catalogs - never translated at runtime.
 *
 *   t("nav.home")                       -> "Inicio" | "Home"
 *   t("admin.users.count", { count: 3 }) -> admin.users.count_one / _other by plural rules
 *   t("common.updated", { when: "…" })  -> "{when}" placeholders filled in
 *
 * A missing key falls back to the other language, then to the key itself (and warns
 * once in development), so a gap is visible but never a crash.
 */
import { createContext, useContext, useMemo, type ReactNode } from "react";
import { CATALOGS, type Catalog, type Locale } from "./catalogs";

export type { Locale } from "./catalogs";
export const LOCALES: readonly Locale[] = ["es", "en"] as const;
export const DEFAULT_LOCALE: Locale = "es";

const INTL_TAG: Record<Locale, string> = { es: "es-ES", en: "en-GB" };
let current: Locale = DEFAULT_LOCALE;
const warned = new Set<string>();

export function isLocale(value: unknown): value is Locale {
  return value === "es" || value === "en";
}

export function setLocale(locale: Locale): void {
  current = locale;
}

export function getLocale(): Locale {
  return current;
}

/** The BCP 47 tag Intl uses for this locale: es-ES, en-GB (24-hour clocks in both). */
export function intlTag(locale: Locale = current): string {
  return INTL_TAG[locale];
}

/**
 * Dots separate levels, but a leaf may contain dots itself: audit actions are keys like "login.succeeded"
 * under `profile.securityPanel.action`. When a level has no child with the next part, the rest of the key is
 * tried whole at that level.
 */
function lookup(locale: Locale, key: string): string | undefined {
  const parts = key.split(".");
  let node: string | Catalog | undefined = CATALOGS[locale];
  for (let i = 0; i < parts.length; i++) {
    if (node === undefined || typeof node === "string") return undefined;
    const next: string | Catalog | undefined = node[parts[i] as string];
    if (next === undefined) {
      const rest = node[parts.slice(i).join(".")];
      return typeof rest === "string" ? rest : undefined;
    }
    node = next;
  }
  return typeof node === "string" ? node : undefined;
}

export function hasKey(key: string, locale: Locale = current): boolean {
  return lookup(locale, key) !== undefined;
}

type Vars = Record<string, string | number | null | undefined>;

function interpolate(text: string, vars: Vars | undefined): string {
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, (whole, name: string) => {
    const v = vars[name];
    return v === undefined || v === null ? whole : String(v);
  });
}

function resolve(key: string, vars: Vars | undefined, locale: Locale): string | undefined {
  const count = vars?.["count"];
  if (typeof count === "number") {
    const form = new Intl.PluralRules(intlTag(locale)).select(count);
    const plural = lookup(locale, `${key}_${form}`) ?? lookup(locale, `${key}_other`);
    if (plural !== undefined) return plural;
  }
  return lookup(locale, key);
}

export function translate(key: string, vars?: Vars, locale: Locale = current): string {
  const text = resolve(key, vars, locale) ?? resolve(key, vars, locale === "es" ? "en" : "es");
  if (text === undefined) {
    if (import.meta.env?.DEV && !warned.has(key)) {
      warned.add(key);
      console.warn(`[i18n] missing key: ${key}`);
    }
    return key;
  }
  return interpolate(text, vars);
}

/** Translate if the key exists in either language, otherwise return the fallback as given. */
export function translateOr(key: string, fallback: string, vars?: Vars): string {
  return hasKey(key) || hasKey(key, current === "es" ? "en" : "es")
    ? translate(key, vars)
    : fallback;
}

export const t = translate;

interface I18nValue {
  locale: Locale;
  t: typeof translate;
}

const I18nContext = createContext<I18nValue>({ locale: DEFAULT_LOCALE, t: translate });

/** Sets the module locale before children render, so plain `t()` calls agree with the context. */
export function I18nProvider({ locale, children }: { locale: Locale; children: ReactNode }) {
  setLocale(locale);
  const value = useMemo<I18nValue>(
    () => ({ locale, t: (k, v) => translate(k, v, locale) }),
    [locale],
  );
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  return useContext(I18nContext);
}

/** The language a signed-out reader sees: their last choice on this browser, else the browser's. */
export function browserLocale(): Locale {
  try {
    const saved = window.localStorage.getItem("predigol.lang");
    if (isLocale(saved)) return saved;
  } catch {
    /* storage unavailable: fall through */
  }
  const nav = typeof navigator !== "undefined" ? navigator.language.toLowerCase() : "";
  return nav.startsWith("en") ? "en" : "es";
}

export function rememberLocale(locale: Locale): void {
  try {
    window.localStorage.setItem("predigol.lang", locale);
  } catch {
    /* storage unavailable: the account preference still applies after sign-in */
  }
}
