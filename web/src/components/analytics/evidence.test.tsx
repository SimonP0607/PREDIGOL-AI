/// <reference types="bun" />
/**
 * Plan PM, PM-10-06 (OP-16; FE-004): the reading sentences, word for word (the templates were reviewed by hand: these are their
 * snapshots), the evidence level capped by the sample, the review of the 14 checks, and the card that carries all three.
 */
import { afterAll, describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import { contrast, over, rootTokens } from "@/lib/a11y/contrast";
import {
  CHART_CHECKS,
  cappedLevel,
  readingSentence,
  reviewProblems,
  type ChartReview,
  type Reading,
} from "./evidence";
import { EvidenceChart } from "./EvidenceChart";

afterAll(() => setLocale("es"));

const EIGHT_OF_TEN: Reading = {
  kind: "rate",
  subject: "Ambos marcan",
  k: 8,
  n: 10,
  interval: [0.49, 0.94],
  minSample: 10,
};
const SEASON: Reading = {
  kind: "rate",
  subject: "Más de 2,5 goles",
  k: 21,
  n: 38,
  interval: [0.4, 0.7],
  league: 0.52,
  minSample: 10,
};
const CORNERS: Reading = {
  kind: "mean",
  subject: "Córners a favor",
  value: 5.43,
  n: 38,
  league: 4.9,
  minSample: 10,
};
const THIN: Reading = { kind: "mean", subject: "Tarjetas", value: 2.5, n: 4, minSample: 10 };

const REVIEW: ChartReview = {
  checks: Object.fromEntries(CHART_CHECKS.map((c) => [c, "ok"])) as ChartReview["checks"],
  reviewedBy: "revisión manual",
  reviewedOn: "2026-11-20",
};

describe("reading sentences (snapshots of the reviewed templates)", () => {
  test("Spanish", () => {
    setLocale("es");
    expect(readingSentence(EIGHT_OF_TEN)).toBe(
      "Ambos marcan: 8 de 10 partidos (80 %). Con esta muestra, el valor real puede estar entre el 49 % y el 94 %.",
    );
    expect(readingSentence(SEASON)).toBe(
      "Más de 2,5 goles: 21 de 38 partidos (55 %). Con esta muestra, el valor real puede estar entre el 40 % y el 70 %; en la liga, 52 %.",
    );
    expect(readingSentence(CORNERS)).toBe(
      "Córners a favor: 5,43 por partido en 38 partidos; en la liga, 4,90.",
    );
    expect(readingSentence(THIN)).toBe(
      "Tarjetas: 2,50 por partido en solo 4 partidos. Muestra pequeña: no es una tendencia.",
    );
    expect(readingSentence({ ...EIGHT_OF_TEN, n: 6, k: 5 })).toBe(
      "Ambos marcan: 5 de 6 partidos. Muestra pequeña: no es una tendencia.",
    );
  });

  test("English", () => {
    setLocale("en");
    expect(readingSentence(EIGHT_OF_TEN)).toBe(
      "Ambos marcan: 8 of 10 matches (80 %). With this sample, the true value may lie between 49 % and 94 %.",
    );
    expect(readingSentence(CORNERS)).toBe(
      "Córners a favor: 5.43 per match over 38 matches; in the league, 4.90.",
    );
    setLocale("es");
  });

  test("an interval in 0-100 reads the same as in 0-1", () => {
    setLocale("es");
    expect(readingSentence({ ...EIGHT_OF_TEN, interval: [49, 94] })).toBe(
      readingSentence(EIGHT_OF_TEN),
    );
  });
});

describe("evidence and review", () => {
  test("under the minimum sample a chart is an anecdote, whatever it claims", () => {
    expect(cappedLevel("E2", THIN)).toBe("E0");
    expect(cappedLevel("E1", SEASON)).toBe("E1");
  });

  test("a review must answer the 14 checks, and some always apply", () => {
    expect(CHART_CHECKS).toHaveLength(14);
    expect(reviewProblems(REVIEW)).toEqual([]);
    const static_ = {
      ...REVIEW,
      checks: { ...REVIEW.checks, teclado: "no_aplica", instrucciones: "no_aplica" },
    };
    expect(reviewProblems(static_ as ChartReview)).toEqual([]);
    const skipped = { ...REVIEW, checks: { ...REVIEW.checks, contraste: "no_aplica" } };
    expect(reviewProblems(skipped as ChartReview)).toEqual(["contraste: siempre aplica"]);
    const missing = { ...REVIEW, checks: { ...REVIEW.checks } } as Record<string, unknown>;
    delete (missing["checks"] as Record<string, unknown>)["tabla_equivalente"];
    expect(reviewProblems(missing as unknown as ChartReview)).toEqual([
      "tabla_equivalente: sin revisar",
    ]);
    expect(reviewProblems({ ...REVIEW, reviewedBy: " ", reviewedOn: "20/11" })).toEqual([
      "revisor: vacío",
      "fecha: no es AAAA-MM-DD",
    ]);
  });
});

describe("EvidenceChart", () => {
  test("the tag, the sentence as the chart's description and the review's state", () => {
    setLocale("es");
    const html = renderToStaticMarkup(
      <EvidenceChart title="Ambos marcan" evidence="E1" reading={EIGHT_OF_TEN} review={REVIEW}>
        <svg role="img" aria-label="barras" />
      </EvidenceChart>,
    );
    expect(html).toContain("E1 · descriptivo");
    expect(html).toContain(
      "Nivel de evidencia E1 · descriptivo: Lo que pasó, con su muestra y su intervalo.",
    );
    const id = /<p id="([^"]+)"/.exec(html)?.[1];
    expect(id).toBeTruthy();
    expect(html).toContain(`aria-describedby="${id}"`);
    expect(html).toContain('data-review="completa"');
    expect(html).toContain("8 de 10 partidos (80 %)");
  });

  test("a thin sample shows E0 even when the piece claims more", () => {
    setLocale("es");
    const html = renderToStaticMarkup(
      <EvidenceChart title="Tarjetas" evidence="E2" reading={THIN} review={REVIEW}>
        <svg />
      </EvidenceChart>,
    );
    expect(html).toContain('data-evidence="E0"');
    expect(html).toContain("E0 · anécdota");
  });

  test("the tags read at 4.5:1 on their card", () => {
    const tok = rootTokens(readFileSync(join(import.meta.dir, "..", "..", "styles.css"), "utf8"));
    const card = tok["card"]!.rgb;
    const pairs: Array<[string, number]> = (["info", "primary", "positive"] as const).map(
      (name) => {
        const c = tok[name]!;
        return [name, contrast(c.rgb, over({ rgb: c.rgb, alpha: 0.14 }, card))];
      },
    );
    pairs.push([
      "neutral",
      contrast(
        tok["foreground-soft"]!.rgb,
        over({ rgb: tok["foreground"]!.rgb, alpha: 0.07 }, card),
      ),
    ]);
    expect(pairs.filter(([, r]) => r < 4.5).map(([n, r]) => `${n}: ${r.toFixed(2)}`)).toEqual([]);
  });
});
