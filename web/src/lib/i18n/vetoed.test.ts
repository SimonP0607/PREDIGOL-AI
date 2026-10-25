/// <reference types="bun" />
/**
 * No internal term on a reader's screen (plan UX, A1, defect F16). The audit found the vocabulary of the system's
 * inside in the texts a client reads - «modo evaluación», «calificada», SHADOW, QUALIFIED - and the raw role "USER".
 * They were rewritten in plain words; this test keeps them out of every catalog the product (not the Admin Console)
 * reads, in both languages.
 *
 * A few texts in those catalogs are read only by the owner - the evaluation preview, the console's own layers - and
 * may name the inside: each is listed with the reason, and the list is checked too, so it cannot keep an exception
 * whose text is gone.
 */
import { describe, expect, test } from "bun:test";
import { CATALOGS, type Catalog, type Locale } from "./catalogs";

/** The namespaces the product's pages read (src/product, the user shell); admin, ops, ai, intel... are the console's. */
const CLIENT = [
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
] as const;

const VETOED: ReadonlyArray<readonly [RegExp, string]> = [
  [/\bshadow\b/i, "shadow"],
  [/\bsombra\b/i, "sombra"],
  [/\bmodo (de )?evaluaci[oó]n\b/i, "modo evaluación"],
  [/\bevaluation mode\b/i, "evaluation mode"],
  [/\bcalificad[oa]s?\b/i, "calificada"],
  [/\bqualified\b/i, "qualified"],
  [/\benforce\b/i, "enforce"],
  [/\bSUPER_ADMIN\b/, "SUPER_ADMIN"],
  [/\bUSER\b/, "USER"],
];

/** Read only by the owner: a key, or a prefix ending in ".", with the reason. */
const OWNER_ONLY: Readonly<Record<string, string>> = {
  "common.source.shadowPreview": "the banner of the owner's evaluation preview (preview=shadow)",
  "common.source.shadowPreviewShort": "the badge of the owner's evaluation preview",
  "match.picks.noneShadow": "the owner's evaluation preview of a match without picks",
  "match.knowledge.admin.": "the layers of a match's knowledge only the owner sees",
  "parlays.builder.result.shadow": "the owner's preview of the builder with evaluation picks",
  "records.chain.evaluation": "a recorded evaluation pick, shown only in the owner's preview",
  "records.evaluation.": "the label and note of the owner's evaluation records",
  "markets.reason.no_shadow_picks": "the reason of an empty evaluation preview",
  "errors.code.last_super_admin": "refused when the owner manages accounts in the console",
};

function entries(node: Catalog, prefix: string): Array<[string, string]> {
  return Object.entries(node).flatMap(([k, v]): Array<[string, string]> =>
    typeof v === "string" ? [[`${prefix}${k}`, v]] : entries(v, `${prefix}${k}.`),
  );
}

function ownerOnly(key: string): boolean {
  return Object.keys(OWNER_ONLY).some((k) => (k.endsWith(".") ? key.startsWith(k) : key === k));
}

function clientTexts(locale: Locale): Array<[string, string]> {
  return CLIENT.flatMap((ns) => {
    const node = CATALOGS[locale][ns];
    if (typeof node !== "object") throw new Error(`no catalog ${ns}`);
    return entries(node, `${ns}.`);
  });
}

describe("no internal term in the catalogs a reader sees", () => {
  for (const locale of ["es", "en"] as const) {
    test(locale, () => {
      const found: string[] = [];
      for (const [key, text] of clientTexts(locale)) {
        if (ownerOnly(key)) continue;
        for (const [re, term] of VETOED) {
          if (re.test(text)) found.push(`${key}: «${term}» in "${text}"`);
        }
      }
      expect(found).toEqual([]);
    });
  }

  test("every owner-only exception names a text that exists", () => {
    const keys = clientTexts("es").map(([k]) => k);
    for (const exception of Object.keys(OWNER_ONLY)) {
      const exists = exception.endsWith(".")
        ? keys.some((k) => k.startsWith(exception))
        : keys.includes(exception);
      expect(exists, exception).toBe(true);
    }
  });

  test("the test would catch the old texts", () => {
    const old = [
      "Modelo (modo evaluación): {selection}",
      "Todas las selecciones calificadas",
      "No qualified picks for this match.",
      "Ver como USER",
    ];
    for (const text of old)
      expect(
        VETOED.some(([re]) => re.test(text)),
        text,
      ).toBe(true);
  });
});
