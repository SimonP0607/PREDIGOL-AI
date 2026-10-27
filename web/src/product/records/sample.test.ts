/// <reference types="bun" />
import { afterAll, describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { setLocale } from "@/lib/i18n";
import type { PicksTally } from "@/lib/api/v1/types_mypicks";
import { CONCLUSIVE, MIN_SAMPLE, enough, marginOf, sampleLine } from "./sample";
import { bandLabel, countsText, lineValueText, signedPct } from "./picksText";

afterAll(() => setLocale("es"));

/** Intl puts a no-break space before «%» in Spanish: compared as a plain one. */
const plain = (s: string | null) => (s ?? "").replace(/[\u00a0\u202f]/g, " ");

describe("the sample of a result in Mis picks (plan UX, B5, section 30)", () => {
  test("the numbers are the server's and «Cómo le va a PrediGol»'s: 25 to show, 100 to conclude", () => {
    expect(MIN_SAMPLE).toBe(25);
    expect(CONCLUSIVE).toBe(100);
    expect(enough(24)).toBe(false);
    expect(enough(25)).toBe(true);
  });

  test("the margin the plan quotes: ±20 points with 25, ±14 with 50, ±10 with 100, ±5 with 400", () => {
    expect(marginOf(0)).toBeNull();
    expect(Math.round((marginOf(25) ?? 0) * 100)).toBe(20);
    expect(Math.round((marginOf(50) ?? 0) * 100)).toBe(14);
    expect(Math.round((marginOf(100) ?? 0) * 100)).toBe(10);
    expect(Math.round((marginOf(400) ?? 0) * 100)).toBe(5);
  });

  test("below 25 settled only the counts and from how many the figures appear", () => {
    setLocale("es");
    expect(sampleLine({ n: 1, margin: null })).toBe(
      "1 liquidado: los aciertos, las unidades y la rentabilidad se ven desde 25.",
    );
    expect(sampleLine({ n: 24, margin: 0.2 })).toBe(
      "24 liquidados: los aciertos, las unidades y la rentabilidad se ven desde 25.",
    );
    setLocale("en");
    expect(sampleLine({ n: 12, margin: null })).toBe(
      "12 settled: hit rate, units and return show from 25.",
    );
  });

  test("from 25 the margin, and below 100 the notice that the sample does not allow a conclusion yet", () => {
    setLocale("es");
    expect(sampleLine({ n: 50, margin: marginOf(50) })).toBe(
      "±14 puntos sobre 50 liquidados: la muestra todavía no permite concluir.",
    );
    expect(sampleLine({ n: 400, margin: marginOf(400) })).toBe("±5 puntos sobre 400 liquidados.");
    setLocale("en");
    expect(sampleLine({ n: 25, margin: marginOf(25) })).toBe(
      "±20 points over 25 settled: the sample does not allow a conclusion yet.",
    );
    expect(sampleLine({ n: 100, margin: marginOf(100) })).toBe("±10 points over 100 settled.");
  });

  test("the server's own numbers are followed when it sends them", () => {
    setLocale("es");
    expect(sampleLine({ n: 30, margin: 0.18, min: 40, conclusive: 200 })).toBe(
      "30 liquidados: los aciertos, las unidades y la rentabilidad se ven desde 40.",
    );
    expect(sampleLine({ n: 150, margin: 0.08, min: 40, conclusive: 200 })).toBe(
      "±8 puntos sobre 150 liquidados: la muestra todavía no permite concluir.",
    );
  });
});

const tally = (patch: Partial<PicksTally>): PicksTally => ({
  total: 0,
  pending: 0,
  won: 0,
  lost: 0,
  half_won: 0,
  half_lost: 0,
  push: 0,
  void: 0,
  settled: 0,
  units: null,
  roi: null,
  margin: null,
  hit_rate: null,
  sample: "counts_only",
  ...patch,
});

describe("the words of «Picks guardados»", () => {
  test("a share with its sign; a dash without a value", () => {
    setLocale("es");
    expect(plain(signedPct("0.031"))).toBe("+3,1 %");
    expect(plain(signedPct(-0.02))).toBe("−2,0 %");
    expect(signedPct(null)).toBe("—");
    setLocale("en");
    expect(signedPct("0.031")).toBe("+3.1%");
  });

  test("every count of a tally, the zero ones left out (won and lost always)", () => {
    setLocale("es");
    expect(countsText(tally({ total: 3, won: 2, lost: 0, pending: 1 }))).toBe(
      "2 ganados · 0 perdidos · 1 pendiente",
    );
    expect(countsText(tally({ total: 5, won: 1, lost: 1, half_won: 1, push: 2 }))).toBe(
      "1 ganado · 1 perdido · 1 medio ganado · 2 devueltos",
    );
  });

  test("the line value of a saved pick only when it has one", () => {
    setLocale("es");
    expect(plain(lineValueText("0.045"))).toBe("Valor de línea +4,5 %");
    expect(lineValueText(null)).toBeNull();
    expect(lineValueText(undefined)).toBeNull();
    setLocale("en");
    expect(lineValueText("-0.012")).toBe("Line value −1.2%");
  });

  test("an odds range reads in the reader's language", () => {
    setLocale("es");
    expect(bandLabel("lt1.5")).toBe("< 1,50");
    expect(bandLabel("5+")).toBe("5 o más");
    setLocale("en");
    expect(bandLabel("1.5-2")).toBe("1.50–2");
  });
});

describe("no streak in Mis picks (plan UX, B5: «Sin rachas»)", () => {
  test("neither language has a streak to show", () => {
    for (const lang of ["es", "en"]) {
      const text = readFileSync(
        `${import.meta.dir}/../../locales/${lang}/records.json`,
        "utf8",
      ).toLowerCase();
      expect(text.includes("streak")).toBe(false);
      expect(text.includes("racha")).toBe(false);
    }
  });
});
