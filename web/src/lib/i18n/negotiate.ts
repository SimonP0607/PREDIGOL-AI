/**
 * The reader's language as the server sees it (plan UX, A1, defect F08): from the request's Accept-Language, the
 * first of the product's languages in the reader's own order of preference, Spanish when none is there. The server
 * writes it in <html lang>, the page title and its error page; once the page runs, the account's language (or the
 * one the reader chose) takes over (Localized in __root.tsx).
 */
import type { Locale } from "./catalogs";

export function localeFromAcceptLanguage(header: string | null | undefined): Locale {
  if (!header) return "es";
  const ranked = header
    .split(",")
    .map((part, index) => {
      const [tag = "", ...params] = part.trim().split(";");
      const q = params.map((p) => p.trim()).find((p) => p.startsWith("q="));
      const weight = q === undefined ? 1 : Number(q.slice(2));
      return { tag: tag.trim().toLowerCase(), weight: Number.isFinite(weight) ? weight : 0, index };
    })
    .filter((x) => x.tag !== "" && x.weight > 0)
    .sort((a, b) => b.weight - a.weight || a.index - b.index);
  for (const { tag } of ranked) {
    if (tag === "es" || tag.startsWith("es-")) return "es";
    if (tag === "en" || tag.startsWith("en-")) return "en";
  }
  return "es";
}
