/// <reference types="bun" />
/**
 * The one glossary (plan UX, A3): the minimal concepts are all there, each with one definition in Spanish and in
 * English; the page's links lead to terms that exist; and «cuota justa» means one thing on every reader's screen -
 * 1 divided by the market's probability without margin. The model's number is «cuota según PrediGol» (the audit
 * found the model's 1/p and the market's 1/p both called «cuota justa»).
 */
import { describe, expect, test } from "bun:test";
import { CATALOGS, type Catalog, type Locale } from "@/lib/i18n/catalogs";
import { translate } from "@/lib/i18n";
import {
  CATEGORIES,
  REQUIRED,
  TERMS,
  TERM_KEYS,
  fold,
  isTerm,
  relatedTerms,
  termAnchor,
  termMatches,
  type TermKey,
} from "./index";

const LOCALES: readonly Locale[] = ["es", "en"];

function leaves(node: Catalog, prefix = ""): Array<[string, string]> {
  return Object.entries(node).flatMap(([k, v]) =>
    typeof v === "string"
      ? [[`${prefix}${k}`, v] as [string, string]]
      : leaves(v, `${prefix}${k}.`),
  );
}

describe("the terms", () => {
  test("every minimal concept of the plan is a term", () => {
    const missing = REQUIRED.filter((k) => !isTerm(k));
    expect(missing).toEqual([]);
    expect(REQUIRED.length).toBe(17);
  });

  test("each term has a name, a short and a long definition in both languages, none empty", () => {
    const gaps: string[] = [];
    for (const locale of LOCALES) {
      for (const key of TERM_KEYS) {
        for (const part of ["name", "short", "long"] as const) {
          const id = `glossary.terms.${key}.${part}`;
          const text = translate(id, undefined, locale);
          if (text === id || text.trim() === "") gaps.push(`${locale} ${id}`);
        }
      }
    }
    expect(gaps).toEqual([]);
  });

  test("the catalog has no term the registry does not know (and so no definition the page would hide)", () => {
    for (const locale of LOCALES) {
      const terms = (CATALOGS[locale]["glossary"] as Catalog)["terms"] as Catalog;
      expect(Object.keys(terms).sort()).toEqual([...TERM_KEYS].sort());
    }
  });

  test("one name per term in each language: no two terms share a name", () => {
    for (const locale of LOCALES) {
      const names = TERM_KEYS.map((k) =>
        fold(translate(`glossary.terms.${k}.name`, undefined, locale)),
      );
      expect(new Set(names).size).toBe(names.length);
    }
  });

  test("a short definition fits a sheet on a phone: at most 240 characters", () => {
    const long: string[] = [];
    for (const locale of LOCALES) {
      for (const key of TERM_KEYS) {
        const text = translate(`glossary.terms.${key}.short`, undefined, locale);
        if (text.length > 240) long.push(`${locale} ${key}: ${text.length}`);
      }
    }
    expect(long).toEqual([]);
  });

  test("every term is in a known group, every group has terms, and related terms exist and are others", () => {
    for (const key of TERM_KEYS) {
      expect(CATEGORIES).toContain(TERMS[key].category);
      const listed = TERMS[key].related as readonly string[];
      expect(listed.filter((r) => !isTerm(r) || r === key)).toEqual([]);
      expect(relatedTerms(key).length).toBe(listed.length);
    }
    for (const category of CATEGORIES) {
      expect(TERM_KEYS.some((k) => TERMS[k].category === category)).toBe(true);
    }
  });

  test("anchors are stable and unique", () => {
    const anchors = TERM_KEYS.map(termAnchor);
    expect(new Set(anchors).size).toBe(anchors.length);
    expect(termAnchor("fairOdds")).toBe("term-fairOdds");
  });
});

describe("the search of the page", () => {
  test("without accents or case, by name or by definition, every word must be found", () => {
    expect(fold("Línea ÁÉÍÓÚ ñ")).toBe("linea aeiou n");
    const hits = (q: string): TermKey[] => TERM_KEYS.filter((k) => termMatches(k, q));
    expect(hits("")).toEqual(TERM_KEYS);
    expect(hits("linea")).toContain("line");
    expect(hits("CUOTA JUSTA")).toContain("fairOdds");
    expect(hits("margen casa")).toContain("margin");
    expect(hits("zzzz-nothing")).toEqual([]);
  });
});

describe("«cuota justa» means the market's fair price on every reader's screen", () => {
  /** The namespaces the product reads (the Admin Console's are not a reader's screen). */
  const CLIENT = [
    "common",
    "home",
    "live",
    "markets",
    "match",
    "matches",
    "odds",
    "parlays",
    "picks",
    "records",
  ];
  const FAIR = /cuota(s)? just[ao]s?|\bprecio justo\b|\bfair (odds|price)\b|\bjust[ao]\b|\bfair\b/i;
  /** A text as a reader reads it: without its placeholders ({fair} is a number, not the word). */
  const says = (text: string) => FAIR.test(text.replace(/\{\w+\}/g, ""));
  /** Keys whose text says «justa» / «fair» and shows the MARKET's 1/p (or means something else), with the reason. */
  const MARKET_OR_OTHER: Readonly<Record<string, string>> = {
    "common.fairOdds":
      "the label of BestPrice.fair_odds = 1 / p_fair (the market's, margin removed)",
    "odds.subtitle": "the odds page compares each best price with the market's fair odds",
    "odds.highlights.subtitle": "BestHighlight: price above the market's fair odds",
    "odds.highlights.vsFair": "price_edge = best_odds × p_fair − 1",
    "odds.board.fair": "BestPrice.fair_odds",
    "odds.board.edgeHelp": "price_edge against the market's fair odds",
    "odds.board.cell": "BestPrice.fair_odds and price_edge",
    "odds.board.outlierHelp": "more than 25 % above the market's fair odds",
    "odds.fairExplainer": "the explanation of the market's fair odds",
    "odds.fairExplainerToggle": "the same explanation, folded on a phone",
    "odds.filters.aboveFair": "only prices above the market's fair odds",
    "odds.filters.sortEdge": "order by price_edge",
    "odds.filters.emptyBody": "names the filter «Solo por encima de la justa»",
    "home.best.subtitle": "BestHighlight against the market's fair odds",
    "home.best.overFair": "price_edge",
    "parlays.why.price": "builder leg: fair_odds = 1 / p_market",
    "match.knowledge.market.pushed": "«la línea quedó justa»: exact, a push - not a price",
    "match.analysis.brief.quality.fair": "«Data quality: fair» (English: middling) - not a price",
  };

  test("only the market's fair price is called fair, and every exception says why", () => {
    const found: string[] = [];
    for (const locale of LOCALES) {
      for (const ns of CLIENT) {
        for (const [key, text] of leaves(CATALOGS[locale][ns] as Catalog, `${ns}.`)) {
          if (says(text) && !(key in MARKET_OR_OTHER)) found.push(`${locale} ${key}: ${text}`);
        }
      }
    }
    expect(found).toEqual([]);
  });

  test("the list of exceptions keeps no key whose text is gone or no longer says it", () => {
    const stale = Object.keys(MARKET_OR_OTHER).filter((key) =>
      LOCALES.every((locale) => !says(translate(key, undefined, locale))),
    );
    expect(stale).toEqual([]);
  });

  test("the model's 1/p is «cuota según PrediGol» wherever a reader sees it", () => {
    expect(translate("match.analysis.figure.fair", undefined, "es")).toBe("Cuota según PrediGol");
    expect(translate("match.analysis.figure.fair", undefined, "en")).toBe("PrediGol's odds");
    expect(translate("match.priceStatus.model", undefined, "es")).toContain(
      "cuota según PrediGol {fair}",
    );
    expect(translate("match.priceStatus.model", undefined, "en")).toContain(
      "PrediGol's odds {fair}",
    );
    expect(translate("match.forecast.admin.fairOdds", undefined, "es")).toBe(
      "cuota según PrediGol {odds}",
    );
    expect(translate("glossary.terms.predigolOdds.name", undefined, "es")).toBe(
      "Cuota según PrediGol",
    );
    expect(translate("glossary.terms.fairOdds.short", undefined, "es")).toContain(
      "probabilidad del mercado sin margen",
    );
  });

  test("«margen» is the bookmaker's cut, never how far a price sits above fair", () => {
    const misuse: string[] = [];
    for (const locale of LOCALES) {
      for (const ns of CLIENT) {
        for (const [key, text] of leaves(CATALOGS[locale][ns] as Catalog, `${ns}.`)) {
          if (/margen (sobre|que pide)|margin (over|our rule)/i.test(text))
            misuse.push(`${locale} ${key}: ${text}`);
        }
      }
    }
    expect(misuse).toEqual([]);
  });
});
