/// <reference types="bun" />
/**
 * Plan PM, PM-12-01 (IA-153): the owner's private evaluation board shows, for each market, PrediGol, the market and the provider on
 * the same matches with their sample and intervals, the Brier split into reliability and resolution, the paired differences with
 * their reading, and the verdict of each competition's own sample - saying it is not a proof of an edge - and says when there is no
 * weekly board yet.
 */
import { afterAll, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import type { EvalWindow, EvaluationBoard } from "@/lib/api/v1/types_evaluation_board";
import { EvaluationBoardView } from "./EvaluationBoardPanel";

afterAll(() => setLocale("es"));

const iv = (value: number, low: number | null = null, high: number | null = null) => ({
  value,
  low,
  high,
});

const win: EvalWindow = {
  from: "2026-11-09",
  to: "2026-11-15",
  matches: 412,
  with_each: { modelo: 412, mercado: 398, proveedor: 371 },
  common: 360,
  sources: [
    {
      source: "modelo",
      n: 360,
      days: 7,
      log_loss: iv(0.9876, 0.95, 1.02),
      brier: iv(0.5912, 0.57, 0.61),
      reliability: iv(0.0123, 0.008, 0.02),
      resolution: iv(0.0611, 0.05, 0.07),
      uncertainty: 0.64,
      residual: 0.0004,
    },
    {
      source: "mercado",
      n: 360,
      days: 7,
      log_loss: iv(0.9701),
      brier: iv(0.58),
      reliability: iv(0.008),
      resolution: iv(0.07),
      uncertainty: 0.64,
      residual: 0.0,
    },
  ],
  pairs: [
    {
      a: "modelo",
      b: "mercado",
      metric: "log_loss",
      n: 398,
      value: 0.0175,
      low: 0.004,
      high: 0.031,
      verdict: "modelo_peor",
    },
    {
      a: "modelo",
      b: "proveedor",
      metric: "log_loss",
      n: 371,
      value: -0.01,
      low: -0.03,
      high: 0.01,
      verdict: "indistinguible",
    },
  ],
};

const board: EvaluationBoard = {
  notice_es: "x",
  weekly: {
    report_id: 3,
    version: "weekly-board-v1",
    period_from: "2026-11-09",
    period_to: "2026-11-15",
    cumulative_from: "2026-10-23",
    computed_at: "2026-11-16T08:05:00Z",
    markets: [{ market: "1X2", line: 0, week: win, cumulative: { ...win, from: "2026-10-23" } }],
  },
  segments: {
    report_id: 2,
    version: "segments-v1",
    period_from: "2026-10-23",
    period_to: "2026-11-16",
    computed_at: "2026-11-16T08:04:00Z",
    needed: 300,
    reproduced: true,
    counts: [{ source: "forecast", kind: "competition", verdict: "insuficiente", segments: 120 }],
    competitions: [
      {
        competition_id: 7,
        name: "Primera A",
        model: "elo_ologit",
        market: "1X2",
        n: 142,
        days: 24,
        log_loss: 1.01,
        log_loss_low: 0.96,
        log_loss_high: 1.07,
        skill: -0.01,
        skill_low: -0.04,
        skill_high: 0.02,
        verdict: "insuficiente",
      },
    ],
  },
};

describe("the evaluation board", () => {
  test("each source with its sample and intervals, reliability and resolution apart, and the pairs", () => {
    setLocale("es");
    const html = renderToStaticMarkup(<EvaluationBoardView board={board} />);
    expect(html).toContain("Evaluación de los modelos (privado)");
    expect(html).toContain("No es una prueba de ventaja");
    expect(html).toContain("Semana 2026-11-09 a 2026-11-15");
    expect(html).toContain("412 partidos con pronóstico; 360 con todas las fuentes");
    expect(html).toContain("Fiabilidad (menor es mejor)");
    expect(html).toContain("Resolución (mayor es mejor)");
    expect(html).toContain("0,0123 [0,0080; 0,0200]");
    expect(html).toContain("Mercado (Shin)");
    expect(html).toContain("el modelo puntúa peor");
    expect(html).toContain("indistinguible");
    expect(html).toContain("Primera A");
    expect(html).toContain("muestra insuficiente");
    expect(html).toContain("Una competición necesita 300 partidos propios");
    expect(html).toContain("Los segmentos reproducen la cifra global");
  });

  test("before the first weekly board, it says so", () => {
    setLocale("es");
    const html = renderToStaticMarkup(
      <EvaluationBoardView board={{ ...board, weekly: null, segments: null }} />,
    );
    expect(html).toContain("Aún no hay informe semanal");
    expect(html).not.toContain("Primera A");
  });

  test("in English", () => {
    setLocale("en");
    const html = renderToStaticMarkup(<EvaluationBoardView board={board} />);
    expect(html).toContain("Model evaluation (private)");
    expect(html).toContain("the model scores worse");
  });
});
