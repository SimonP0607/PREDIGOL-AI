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
import "@/product/competitions/text";
import "@/product/match/stats/matchvizText";
import "@/product/teams/stats/playerText";
import "@/product/explain/probIconsText";

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
  "competitions",
  "players",
  "matchviz",
  "probicons",
  "families",
  "explorer",
  "notices",
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
  [/\bp\d{2}\b/, "percentil pNN", ["es", "en"]],
  // Spanish writes 2,5; a point is the English reader's decimal. A version number («16.4») is not a decimal.
  [/(?<![\d.])\d\.\d(?!\d*\.)/, "decimal con punto", ["es"]],
];

/**
 * Texts that still use a term, «locale:key|term» -> the piece of the plan that rewrites it. Built from the catalogs of
 * 23-nov-2026; every piece removes its lines.
 */
const KNOWN: Readonly<Record<string, string>> = {
  "en:matchviz.layers.source|API-Football": "AP-T01",
  "en:matchviz.scoreState.source|API-Football": "AP-T01",
  "en:matchviz.source.api_football|API-Football": "AP-T01",
  "en:matchviz.zones.xgSource|API-Football": "AP-T01",
  "en:players.sourceMixed|API-Football": "AP-T01",
  "en:players.sourceProvider|API-Football": "AP-T01",
  "es:matchviz.layers.source|API-Football": "AP-T01",
  "es:matchviz.scoreState.source|API-Football": "AP-T01",
  "es:matchviz.source.api_football|API-Football": "AP-T01",
  "es:matchviz.zones.xgSource|API-Football": "AP-T01",
  "es:players.sourceMixed|API-Football": "AP-T01",
  "es:players.sourceProvider|API-Football": "AP-T01",
  "en:markets.gate.not_qualified|backtest": "AP-K03",
  "en:match.analysis.block.elo|Elo": "AP-P07",
  "en:match.forecast.models.dixon_coles|Dixon-Coles": "AP-P07",
  "en:match.forecast.models.elo_ologit|Elo": "AP-P07",
  "en:match.forecast.models.elo_ologit|logit": "AP-P07",
  "en:match.forecast.models.poisson|Poisson": "AP-P07",
  "en:match.providerPrediction.label|API-Football": "AP-T01",
  "en:match.providerPrediction.label|Poisson": "AP-P07",
  "en:match.providerPrediction.title|API-Football": "AP-T01",
  "en:records.daily.emptyBody|backtest": "AP-K03",
  "en:records.noPick.reason.not_qualified|backtest": "AP-K03",
  "en:stats.pulseNote|versión de modelo": "AP-T03",
  "en:stats.pulseSub|bootstrap": "AP-T03",
  "en:stats.settlesWith.player|API-Football": "AP-T01",
  "en:stats.settlesWith.stats|API-Football": "AP-T01",
  "en:stats.source|API-Football": "AP-T01",
  "en:stats.survivalSub|Kaplan-Meier": "AP-T03",
  "es:errors.code.invalid_message|decimal con punto": "AP-T02",
  "es:markets.gate.not_qualified|backtest": "AP-K03",
  "es:match.analysis.block.elo|Elo": "AP-P07",
  "es:match.forecast.models.dixon_coles|Dixon-Coles": "AP-P07",
  "es:match.forecast.models.elo_ologit|Elo": "AP-P07",
  "es:match.forecast.models.elo_ologit|logit": "AP-P07",
  "es:match.forecast.models.poisson|Poisson": "AP-P07",
  "es:match.providerPrediction.label|API-Football": "AP-T01",
  "es:match.providerPrediction.label|Poisson": "AP-P07",
  "es:match.providerPrediction.title|API-Football": "AP-T01",
  "es:records.daily.emptyBody|backtest": "AP-K03",
  "es:records.noPick.reason.not_qualified|backtest": "AP-K03",
  "es:stats.pulseMethod|decimal con punto": "AP-T03",
  "es:stats.pulseNote|versión de modelo": "AP-T03",
  "es:stats.pulseSub|bootstrap": "AP-T03",
  "es:stats.settlesWith.player|API-Football": "AP-T01",
  "es:stats.settlesWith.stats|API-Football": "AP-T01",
  "es:stats.source|API-Football": "AP-T01",
  "es:stats.survivalSub|Kaplan-Meier": "AP-T03",
};

/** The most entries the list may ever have. Lowering it is welcome; raising it is not allowed. */
const CEILING = 48;

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
