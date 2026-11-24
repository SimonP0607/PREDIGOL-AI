/**
 * «España» finds Spain (Plan Maestro de Correcciones, AP-B02; audit B3).
 *
 * The provider names its teams in English only, and the three searches (the favourites' picker, Equipos, the global search)
 * match what is typed against those names: «España» found «Real Espana», «Spain» found the national team. The readers'
 * search no longer needs this (C-10 1.1 carries the Spanish names, UX-242); it stays for the lists that do not read the
 * search index (the earlier `GET /search`, Equipos, the favourites' picker): the web asks a second time: when what is typed is the start of a
 * country's name in the reader's language, the provider's English name goes out as one more term, and the answers are
 * merged without repeats, the country's own national team first.
 *
 * The table comes from `Intl.DisplayNames` (the web already translates countries with it, product/matches/country.ts), plus
 * the home nations and the provider's own spellings that Intl does not give («USA», «Czech Republic», «Ivory Coast»).
 */
import { intlTag, translateOr } from "@/lib/i18n";
import { englishCodes, plain, SPELLINGS } from "@/product/matches/country";

/** A name needs this many letters before it stands for a country: «es» is not Spain. */
const MIN_LETTERS = 3;
/** At most this many extra searches for one text (the closest names first). */
const MAX_ALIASES = 3;

const HOME_NATIONS: Record<string, string> = {
  "GB-ENG": "England",
  "GB-SCT": "Scotland",
  "GB-WLS": "Wales",
  "GB-NIR": "Northern Ireland",
};

interface Country {
  code: string;
  /** The names the provider may give it, the most common first. */
  english: string[];
}

let table: Country[] | null = null;

function title(plainName: string): string {
  return plainName
    .split(" ")
    .map((w) =>
      ["usa", "dr", "dpr"].includes(w) ? w.toUpperCase() : w[0]?.toUpperCase() + w.slice(1),
    )
    .join(" ");
}

function countries(): Country[] {
  if (table) return table;
  const byCode = new Map<string, string[]>();
  let names: Intl.DisplayNames | null = null;
  try {
    names = new Intl.DisplayNames(["en"], { type: "region" });
  } catch {
    names = null;
  }
  for (const [, code] of englishCodes()) {
    const english = names?.of(code);
    if (english && english !== code) byCode.set(code, [english]);
  }
  // the provider's spellings (they come after Intl's: «United States», then «USA»)
  for (const [spelling, code] of Object.entries(SPELLINGS)) {
    // the long official forms («United States Of America») are nobody's provider spelling
    if (spelling.includes(" of ")) continue;
    const list = byCode.get(code) ?? [];
    const variant = HOME_NATIONS[code] ?? title(spelling);
    if (!list.some((n) => plain(n) === plain(variant))) list.push(variant);
    byCode.set(code, list);
  }
  for (const [code, name] of Object.entries(HOME_NATIONS)) byCode.set(code, [name]);
  table = Array.from(byCode, ([code, english]) => ({ code, english }));
  return table;
}

const LOCAL = new Map<string, Intl.DisplayNames | null>();

/** A country's name in the reader's language (the code Intl knows, or the home nation's catalog entry). */
function localName(code: string): string | null {
  if (code.startsWith("GB-")) return translateOr(`matches.country.${code}`, "") || null;
  const tag = intlTag();
  if (!LOCAL.has(tag)) {
    try {
      LOCAL.set(tag, new Intl.DisplayNames([tag], { type: "region" }));
    } catch {
      LOCAL.set(tag, null);
    }
  }
  try {
    const name = LOCAL.get(tag)?.of(code);
    return name && name !== code ? name : null;
  } catch {
    return null;
  }
}

/**
 * The provider's English names to search besides what the reader typed: for each country whose name in the reader's language
 * starts with the text (the exact name first), its English names that the provider's own search would not already find.
 */
export function countryAliases(typed: string): string[] {
  const key = plain(typed);
  if (key.replace(/ /g, "").length < MIN_LETTERS) return [];
  const found: Array<{ exact: boolean; names: string[] }> = [];
  for (const c of countries()) {
    const local = localName(c.code);
    if (!local) continue;
    const name = plain(local);
    const exact = name === key;
    if (!exact && !name.startsWith(key)) continue;
    // what the provider's search finds already (its own spelling contains the text) is not asked twice
    const names = c.english.filter((n) => !plain(n).includes(key));
    if (names.length > 0) found.push({ exact, names });
  }
  found.sort((a, b) => Number(b.exact) - Number(a.exact));
  const out: string[] = [];
  for (const f of found)
    for (const n of f.names) if (!out.includes(n) && out.length < MAX_ALIASES) out.push(n);
  return out;
}

/** An answer of a search: a name and an id are all the merge needs. */
export interface Named {
  id: number;
  name: string;
}

/**
 * The answers of the typed text and of its aliases as one list: the national team of an aliased country first (its name is
 * exactly the English name asked: «Spain», not «Spain U21» nor «Real Espana»), then the typed text's own, then the rest; no
 * one twice. `key` and `name` read an answer that is not shaped {id, name} (a search hit: its type and id, its label).
 */
export function mergeAliased<T>(
  own: readonly T[],
  aliased: ReadonlyArray<readonly T[]>,
  aliases: readonly string[],
  key: (t: T) => string | number = (t) => (t as unknown as Named).id,
  name: (t: T) => string = (t) => (t as unknown as Named).name,
): T[] {
  const wanted = new Set(aliases.map((a) => plain(a)));
  const seen = new Set<string | number>();
  const out: T[] = [];
  const push = (t: T) => {
    const k = key(t);
    if (seen.has(k)) return;
    seen.add(k);
    out.push(t);
  };
  const extra = aliased.flat();
  for (const t of [...extra, ...own]) if (wanted.has(plain(name(t)))) push(t);
  for (const t of own) push(t);
  for (const t of extra) push(t);
  return out;
}
