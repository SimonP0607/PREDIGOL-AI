/// <reference types="bun" />
/**
 * The explorer's rules that are about words and code, not data (plan Cuotas, sections 5 and 8):
 *
 * - no text presents a price difference as an advantage («ventaja», «valor», «oportunidad» - a market called «doble
 *   oportunidad» aside - and their English), no urgency, no model figure; «margen» is the bookmaker's cut; «justa» is the
 *   market's; and no internal term (the product's vetoed list) - in both languages, which have the same keys;
 * - the fair price and the difference are grey, never gold, and nothing sparkles;
 * - the UI does not import the API layer (the wiring step does), recharts travels only in the lazily loaded chart, and the
 *   in-memory data is for the tests alone.
 */
import { describe, expect, test } from "bun:test";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { CATALOGS, type Catalog } from "@/lib/i18n/catalogs";
import { MOTION, onlyWithMotion } from "./motion";

const DIR = import.meta.dir;

function leaves(node: Catalog, prefix = ""): Array<[string, string]> {
  return Object.entries(node).flatMap(([k, v]): Array<[string, string]> =>
    typeof v === "string" ? [[`${prefix}${k}`, v]] : leaves(v, `${prefix}${k}.`),
  );
}

const texts = {
  es: leaves(CATALOGS.es["explorer"] as Catalog, "explorer."),
  en: leaves(CATALOGS.en["explorer"] as Catalog, "explorer."),
};

const sources = readdirSync(DIR)
  .filter((n) => /\.(ts|tsx)$/.test(n) && !/\.test\.tsx?$/.test(n))
  .map((name) => ({ name, text: readFileSync(join(DIR, name), "utf8") }));

describe("the explorer's words", () => {
  test("Spanish and English have the same keys, none empty", () => {
    const es = texts.es.map(([k]) => k).sort();
    const en = texts.en.map(([k]) => k).sort();
    expect(es).toEqual(en);
    expect([...texts.es, ...texts.en].filter(([, v]) => v.trim() === "")).toEqual([]);
  });

  test("no price difference is an advantage, a value or an opportunity; no urgency, no model figure", () => {
    const banned: Record<"es" | "en", RegExp> = {
      es: /ventaja|\bvalor|oportunidad|chollo|ganga|ahora mismo|no te lo pierdas|seguro|garantiza|valor esperado|\bVE\b|modelo/i,
      en: /advantage|\bvalue|opportunit|bargain|edge|right now|don't miss|sure bet|guarantee|expected value|\bEV\b|model/i,
    };
    for (const locale of ["es", "en"] as const) {
      const found = texts[locale]
        // «Doble oportunidad» / «double chance» is a market's name, not a promise
        .map(([k, v]) => [k, v.replace(/doble oportunidad/gi, "")] as const)
        .filter(([, v]) => banned[locale].test(v));
      expect(found).toEqual([]);
    }
  });

  test("«margen» is the bookmaker's cut, never how far a price sits above the fair one", () => {
    const misuse = [...texts.es, ...texts.en].filter(([, v]) =>
      /margen (sobre|que pide|de diferencia)|margin (over|our rule|above)/i.test(v),
    );
    expect(misuse).toEqual([]);
  });

  test("«justa» is always the market's: named so, or beside the market's own figures", () => {
    const fairWords = texts.es.filter(([, v]) => /\bjust[ao]s?\b/i.test(v.replace(/\{\w+\}/g, "")));
    expect(fairWords.length).toBeGreaterThan(5);
    // none of them speaks of PrediGol's numbers as fair
    expect(fairWords.filter(([, v]) => /según PrediGol|del modelo|nuestra/i.test(v))).toEqual([]);
    expect(
      CATALOGS.es["explorer"] && texts.es.find(([k]) => k === "explorer.price.srFair")?.[1],
    ).toBe("Justa del mercado {fair}.");
  });

  test("no internal term reaches the reader", () => {
    const internal =
      /\bshadow\b|\bsombra\b|modo (de )?evaluaci[oó]n|evaluation mode|calificad[oa]s?|\bqualified\b|\benforce\b|SUPER_ADMIN|\bUSER\b|tax-v3|book_current/i;
    expect([...texts.es, ...texts.en].filter(([, v]) => internal.test(v))).toEqual([]);
  });
});

describe("the explorer's code", () => {
  test("the fair price and the difference are grey: no gold and no sparkles outside the parlay's own pieces", () => {
    for (const { name, text } of sources) {
      expect(text, name).not.toMatch(/Sparkles/);
      expect(text, name).not.toMatch(/text-positive/);
      // Gold is Mi Parlay's colour in the product: only its bar uses it here
      if (name !== "Status.tsx") expect(text, name).not.toMatch(/\bgold\b|-gold/);
    }
  });

  test("the UI never imports the API layer; nothing but the tests imports the in-memory data", () => {
    for (const { name, text } of sources) {
      expect(text, name).not.toMatch(/from "@\/lib\/api/);
      if (name !== "fake.ts") expect(text, name).not.toMatch(/from "\.\/fake"/);
    }
  });

  test("recharts only in the chart, and the chart only through a dynamic import", () => {
    for (const { name, text } of sources) {
      if (name === "MovementChart.tsx") {
        expect(text).toMatch(/from "recharts"/);
        continue;
      }
      expect(text, name).not.toMatch(/recharts/);
      // ../MovementPanel and ../OddsBoard carry recharts statically
      expect(text, name).not.toMatch(/from "\.\.\/(MovementPanel|OddsBoard)"/);
      expect(text, name).not.toMatch(/import [^(]*from "\.\/MovementChart"/);
    }
    expect(sources.find((s) => s.name === "Panels.tsx")?.text).toContain(
      'lazy(() => import("./MovementChart"))',
    );
  });

  test("every animation runs only without «reduce motion»", () => {
    for (const [name, classes] of Object.entries(MOTION)) {
      expect(onlyWithMotion(classes), name).toBe(true);
    }
    expect(onlyWithMotion("animate-in fade-in")).toBe(false);
    expect(MOTION.tint).toContain("motion-reduce:hidden");
  });
});
