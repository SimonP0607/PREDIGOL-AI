/// <reference types="bun" />
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import { FunnelLine } from "./FunnelLine";

setLocale("es");

describe("how a pick of the day gets here (REVIEW B1)", () => {
  test("every step, the risk cap and PrediGol Intelligence - never a model's name", () => {
    const html = renderToStaticMarkup(<FunnelLine />).replace(/<[^>]+>/g, " ");
    for (const step of [
      "Datos válidos",
      "Mercado",
      "Modelo",
      "Calibración",
      "Valor",
      "Riesgo (cuota ≤ 3,00)",
      "PrediGol Intelligence",
      "Selección (máx. 5)",
    ]) {
      expect(html).toContain(step);
    }
    expect(html).not.toMatch(/elo_ologit|dixon|poisson/i);
  });
});
