/// <reference types="bun" />
/**
 * Technical vocabulary on a reader's screen (Plan Maestro de Correcciones, AP-Q02; audit P11, P12, E4, K3).
 *
 * The first veto (vetoed.test.ts) keeps the system's inside - «shadow», «modo evaluación», the raw role - out of the
 * catalogs a reader sees. The owner's audit found a second family in the texts: the data provider's name, a model's
 * version («pulso-v1»), the methods («Kaplan», «bootstrap», «Dixon-Coles», «Poisson», «Elo», «logit», «backtest»), a
 * percentile written «p90» and decimals written with a point in Spanish.
 *
 * Those texts were not rewritten in one go, so they are LISTED here, each with the piece of the plan that will
 * rewrite it. The list is a ratchet:
 *   - a text that is not on the list and uses one of the terms fails the test (nothing new gets in);
 *   - a text on the list that no longer uses the term fails the test too, until its line is removed (the list only
 *     shrinks);
 *   - the number of entries can never grow past `CEILING`.
 */
import { describe, expect, test } from "bun:test";
import { CATALOGS, type Catalog, type Locale } from "./catalogs";
// The namespaces added when their screen loads (`addCatalog`): imported so the list does not depend on test order.
import "@/product/shared/availabilityText";
import "@/components/analytics/evidenceText";
import "@/components/analytics/stats/readText";
import "@/product/competitions/text";
import "@/product/match/stats/matchvizText";
import "@/product/teams/stats/playerText";
import "@/product/explain/probIconsText";
import "@/product/news/storyText";

/** Namespaces a reader's pages read: the first veto's list plus the ones it did not watch (AP-Q02). */
const READER = [
  "auth",
  "common",
  "errors",
  "home",
  "live",
  "markets",
  "match",
  "matches",
  "nav",
  "odds",
  "parlays",
  "picks",
  "profile",
  "records",
  "glossary",
  "legal",
  "push",
  "explain",
  "profiles",
  "stats",
  "support",
  "onboarding",
  "guides",
  "transparency",
  "evidence",
  "readchart",
  "competitions",
  "players",
  "matchviz",
  "probicons",
  "families",
  "explorer",
  "notices",
  "stories",
] as const;

type Term = readonly [RegExp, string, Locale[]];

const TERMS: readonly Term[] = [
  [/API-?Football/i, "API-Football", ["es", "en"]],
  [/\b(?:forecast|pulso)-v\d/i, "versión de modelo", ["es", "en"]],
  [/\bKaplan\b/i, "Kaplan-Meier", ["es", "en"]],
  [/\bbootstrap\b/i, "bootstrap", ["es", "en"]],
  [/\bbacktest(?:ing)?\b/i, "backtest", ["es", "en"]],
  [/\bDixon-?Coles\b/i, "Dixon-Coles", ["es", "en"]],
  [/\bPoisson\b/i, "Poisson", ["es", "en"]],
  [/\bElo\b/, "Elo", ["es", "en"]],
  [/\blogit\b/i, "logit", ["es", "en"]],
  [/\bshrink(?:age)?\b/i, "shrinkage", ["es", "en"]],
  // AP-T01b: the label of an unchecked forecast is «Estimación preliminar», the validated one «Probabilidad de PrediGol».
  [/\b(?:sin calibrar|uncalibrated|not calibrated)\b/i, "«sin calibrar»", ["es", "en"]],
  [/\b(?:modelo validado|validated model)\b/i, "«modelo validado»", ["es", "en"]],
  [
    /\b(?:consenso sin margen|consensus without margin|margin-free consensus)\b/i,
    "consenso sin margen",
    ["es", "en"],
  ],
  [
    /\b(?:los mismos números|the same numbers|seis ejes fijos|six fixed axes)\b/i,
    "relleno de lector",
    ["es", "en"],
  ],
  [/\bp\d{2}\b/, "percentil pNN", ["es", "en"]],
  // Spanish writes 2,5; a point is the English reader's decimal. A version number («16.4») is not a decimal.
  [/(?<![\d.])\d\.\d(?!\d*\.)/, "decimal con punto", ["es"]],
];

/**
 * Texts that still use a term, «locale:key|term» -> the piece of the plan that rewrites it. Built from the catalogs of
 * 23-nov-2026; AP-T01 rewrote all but one.
 */
const KNOWN: Readonly<Record<string, string>> = {
  // «4.000 caracteres»: the thousands separator of Spanish, read by the test as a decimal point. AP-T02 decides it.
  "es:errors.code.invalid_message|decimal con punto": "AP-T02",
};

/** The most entries the list may ever have. Lowering it is welcome; raising it is not allowed. */
const CEILING = 1;

function entries(node: Catalog, prefix: string): Array<[string, string]> {
  return Object.entries(node).flatMap(([k, v]): Array<[string, string]> =>
    typeof v === "string" ? [[`${prefix}${k}`, v]] : entries(v, `${prefix}${k}.`),
  );
}

function current(): string[] {
  const found: string[] = [];
  for (const locale of ["es", "en"] as const) {
    for (const ns of READER) {
      const node = CATALOGS[locale][ns];
      if (typeof node !== "object") continue;
      for (const [key, text] of entries(node, `${ns}.`)) {
        for (const [re, name, locales] of TERMS) {
          if (locales.includes(locale) && re.test(text)) found.push(`${locale}:${key}|${name}`);
        }
      }
    }
  }
  return found.sort();
}

describe("technical vocabulary in a reader's catalogs (AP-Q02)", () => {
  test("nothing new gets in", () => {
    const fresh = current().filter((id) => !(id in KNOWN));
    expect(fresh).toEqual([]);
  });

  test("a rewritten text leaves the list", () => {
    const now = new Set(current());
    const stale = Object.keys(KNOWN).filter((id) => !now.has(id));
    expect(stale).toEqual([]);
  });

  test("the list never grows", () => {
    expect(Object.keys(KNOWN).length).toBeLessThanOrEqual(CEILING);
  });

  test("the terms catch what the audit found", () => {
    const seen = [
      "Pronóstico de API-Football",
      "pulso-v1 con bootstrap",
      "curva de Kaplan-Meier",
      "Poisson, Dixon-Coles y Elo",
      "percentil p90",
      "más de 2.5 goles",
    ];
    for (const text of seen) {
      expect(
        TERMS.some(([re]) => re.test(text)),
        text,
      ).toBe(true);
    }
    expect(TERMS.some(([re]) => re.test("iOS 16.4"))).toBe(false);
    expect(TERMS.some(([re]) => re.test("más de 2,5 goles"))).toBe(false);
  });

  // The console in Spanish showed English sentences (audit A3). Those came from the server's own texts, which the web
  // translates (AP-T02); the catalogs themselves must not hold English, in any namespace.
  test("no Spanish catalog holds an English sentence", () => {
    const en =
      /\b(the|and|with|for|of|is|are|not|to|from|this|that|has|have|failed|loading|your|you|can|will|was|were|by|at|on)\b/gi;
    const es = /\b(el|la|los|las|de|del|que|con|para|sin|por|una|un|es|en|se|no|su|al|más|y|o)\b/gi;
    const found: string[] = [];
    for (const [ns, node] of Object.entries(CATALOGS.es)) {
      if (typeof node !== "object") continue;
      for (const [key, text] of entries(node, `${ns}.`)) {
        const english = (text.match(en) ?? []).length;
        if (english >= 3 && english > (text.match(es) ?? []).length * 2)
          found.push(`${key}: ${text.slice(0, 60)}`);
      }
    }
    expect(found).toEqual([]);
  });
});
