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

/**
 * The provider's spellings that are not the English name Intl gives the country («USA», «Czech Republic», «Turkey»): the
 * code they stand for. The home nations are GB-*, named from the catalogs.
 */
const SPELLINGS: Record<string, string> = {
  usa: "US",
  "united states of america": "US",
  "korea republic": "KR",
  "korea dpr": "KP",
  "czech republic": "CZ",
  turkey: "TR",
  turkiye: "TR",
  "ivory coast": "CI",
  "cote d ivoire": "CI",
  bosnia: "BA",
  "bosnia and herzegovina": "BA",
  macedonia: "MK",
  "fyr macedonia": "MK",
  "chinese taipei": "TW",
  "hong kong": "HK",
  "cape verde": "CV",
  "cape verde islands": "CV",
  "congo dr": "CD",
  "dr congo": "CD",
  "trinidad and tobago": "TT",
  "republic of ireland": "IE",
  england: "GB-ENG",
  scotland: "GB-SCT",
  wales: "GB-WLS",
  "northern ireland": "GB-NIR",
};

/** «Czech-Republic», «Côte d'Ivoire» -> «czech republic», «cote d ivoire»: how a name is compared. */
function plain(name: string): string {
  return name
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

let english: Map<string, string> | null = null;

/** Codes Intl names that are not a country a referee comes from (the EU, the UN, «Unknown Region», pseudo-locales). */
const NOT_COUNTRIES = new Set(["EU", "EZ", "UN", "ZZ", "QO", "XA", "XB"]);

/** Every region's English name, as Intl spells it, to its ISO code: built once. */
function englishCodes(): Map<string, string> {
  if (english) return english;
  english = new Map();
  const names = displayNames("en");
  if (!names) return english;
  const A = "A".charCodeAt(0);
  for (let i = 0; i < 26; i++) {
    for (let j = 0; j < 26; j++) {
      const code = String.fromCharCode(A + i, A + j);
      if (NOT_COUNTRIES.has(code)) continue;
      try {
        const name = names.of(code);
        if (name && name !== code) english.set(plain(name), code);
      } catch {
        /* not a region code */
      }
    }
  }
  return english;
}

/**
 * A country the provider names only in English («Spain», «Czech-Republic», «England»), in the reader's language
 * («España», «República Checa», «Inglaterra»). Null when the name cannot be matched to a country with certainty: a name in
 * the provider's English is never shown to a Spanish reader, it is left out.
 */
export function countryFromEnglish(country: string | null | undefined): string | null {
  const key = plain(country ?? "");
  if (!key) return null;
  const code = SPELLINGS[key] ?? englishCodes().get(key);
  if (!code) return null;
  if (code.startsWith("GB-")) {
    const name = translateOr(`matches.country.${code}`, "");
    return name || null;
  }
  try {
    const local = displayNames(intlTag())?.of(code);
    return local && local !== code ? local : null;
  } catch {
    return null;
  }
}
