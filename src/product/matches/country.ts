/**
 * A competition's country in the reader's language.
 *
 * The API stores the provider's English name ("Netherlands") and, when it has one, an
 * ISO code ("NL", or "GB-ENG" for the home nations). The code is what gets translated;
 * "World" competitions (friendlies, Nations League...) carry no country at all.
 */
import { intlTag, translateOr } from "@/lib/i18n";

const NAMES = new Map<string, Intl.DisplayNames | null>();

function displayNames(tag: string): Intl.DisplayNames | null {
  if (!NAMES.has(tag)) {
    try {
      NAMES.set(tag, new Intl.DisplayNames([tag], { type: "region" }));
    } catch {
      NAMES.set(tag, null);
    }
  }
  return NAMES.get(tag) ?? null;
}

export function countryLabel(
  country: string | null | undefined,
  code: string | null | undefined,
): string | null {
  const name = (country ?? "").trim();
  if (!name || name.toLowerCase() === "world") return null;
  const iso = (code ?? "").trim().toUpperCase();
  if (/^[A-Z]{2}$/.test(iso)) {
    try {
      const local = displayNames(intlTag())?.of(iso);
      if (local && local !== iso) return local;
    } catch {
      /* unknown code: the stored name stands */
    }
  }
  if (iso.startsWith("GB-")) return translateOr(`matches.country.${iso}`, name);
  return name;
}
