/**
 * The one glossary (plan UX, A3): every word PrediGol uses, with one definition, in Spanish and English
 * (src/locales/<lang>/glossary.json, namespace "glossary"). A screen opens a term with <GlossaryTerm term="...">
 * (src/components/system/GlossaryTerm.tsx); /help/glossary lists them all; a figure inside a card's link carries the
 * same short definition as its hint. One word, one definition: «cuota justa» is the market's, margin removed, and the
 * model's is «cuota según PrediGol» - never the other way round (the audit found both called «cuota justa»).
 *
 * The Admin Console's older metric definitions (./admin.ts) are obsolete: nothing new reads them.
 */
import { t } from "@/lib/i18n";

export const CATEGORIES = ["predigol", "prices", "parlays", "results"] as const;
export type Category = (typeof CATEGORIES)[number];

interface TermInfo {
  category: Category;
  /** Terms worth reading next, shown under the definition on the glossary page (each one a key of TERMS: tested). */
  related: readonly string[];
}

/** Every term, in the order the glossary page lists them inside their category. */
export const TERMS = {
  forecast: {
    category: "predigol",
    related: ["probability", "calibrated", "range", "value", "pick"],
  },
  range: { category: "predigol", related: ["forecast", "probability"] },
  calibrated: { category: "predigol", related: ["forecast", "probability"] },
  value: { category: "predigol", related: ["expectedValue", "odds", "probability", "pick"] },
  expectedValue: { category: "predigol", related: ["value", "odds", "probability"] },
  edge: { category: "predigol", related: ["marketProbability", "expectedValue"] },
  pick: { category: "predigol", related: ["forecast", "value", "bookmaker"] },
  probability: {
    category: "prices",
    related: ["impliedProbability", "marketProbability", "forecast"],
  },
  impliedProbability: { category: "prices", related: ["odds", "margin"] },
  marketProbability: { category: "prices", related: ["margin", "fairOdds", "edge"] },
  odds: { category: "prices", related: ["impliedProbability", "bestOdds", "units"] },
  bestOdds: { category: "prices", related: ["odds", "bookmaker"] },
  margin: { category: "prices", related: ["impliedProbability", "marketProbability", "fairOdds"] },
  fairOdds: { category: "prices", related: ["marketProbability", "margin", "predigolOdds"] },
  predigolOdds: { category: "prices", related: ["forecast", "value", "fairOdds"] },
  bookmaker: { category: "prices", related: ["odds", "bestOdds", "margin"] },
  market: { category: "prices", related: ["line", "settlement"] },
  line: { category: "prices", related: ["push", "halfWon", "halfLost"] },
  parlay: { category: "parlays", related: ["dependency", "odds", "void"] },
  dependency: { category: "parlays", related: ["parlay", "probability"] },
  settlement: { category: "results", related: ["push", "void", "halfWon", "halfLost", "units"] },
  push: { category: "results", related: ["line", "settlement", "void"] },
  void: { category: "results", related: ["settlement", "push"] },
  halfWon: { category: "results", related: ["line", "halfLost"] },
  halfLost: { category: "results", related: ["line", "halfWon"] },
  units: { category: "results", related: ["roi", "odds"] },
  roi: { category: "results", related: ["units", "sample", "settlement"] },
  sample: { category: "results", related: ["roi", "lineValue"] },
  lineValue: { category: "results", related: ["odds", "marketProbability", "margin", "sample"] },
} as const satisfies Record<string, TermInfo>;

export type TermKey = keyof typeof TERMS;

export const TERM_KEYS = Object.keys(TERMS) as TermKey[];

/**
 * The minimal concepts of the plan (section 48, A3): each one must be here, with one definition in each language.
 * The test of the glossary checks it.
 */
export const REQUIRED: readonly TermKey[] = [
  "pick",
  "forecast",
  "probability",
  "odds",
  "fairOdds",
  "margin",
  "value",
  "calibrated",
  "roi",
  "units",
  "sample",
  "parlay",
  "dependency",
  "settlement",
  "push",
  "void",
  "halfWon",
];

export const GLOSSARY_PATH = "/help/glossary";

export function isTerm(key: string): key is TermKey {
  return Object.prototype.hasOwnProperty.call(TERMS, key);
}

export function termName(key: TermKey): string {
  return t(`glossary.terms.${key}.name`);
}

/** One or two sentences: the definition a tap opens. */
export function termShort(key: TermKey): string {
  return t(`glossary.terms.${key}.short`);
}

/** The rest of it, with an example where one helps: on the glossary page, after the short one. */
export function termLong(key: TermKey): string {
  return t(`glossary.terms.${key}.long`);
}

export function termCategory(key: TermKey): Category {
  return TERMS[key].category;
}

export function relatedTerms(key: TermKey): TermKey[] {
  return (TERMS[key].related as readonly string[]).filter(isTerm);
}

/** The id of a term on the glossary page: /help/glossary#term-fairOdds. */
export function termAnchor(key: TermKey): string {
  return `term-${key}`;
}

/** Lower case, without accents: «Línea» is found by «linea». */
export function fold(text: string): string {
  return text
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase();
}

/** Whether a term answers a search: its name or its definition contain every word of the query. */
export function termMatches(key: TermKey, query: string): boolean {
  const words = fold(query).split(/\s+/).filter(Boolean);
  if (words.length === 0) return true;
  const haystack = fold(`${termName(key)} ${termShort(key)} ${termLong(key)}`);
  return words.every((w) => haystack.includes(w));
}
