/// <reference types="bun" />
/**
 * Backtesting, explained in three lines (plan AP-A05, audit A4): what it is, how to read it and what it decides - in Spanish
 * and in English, in words the owner reads in a minute, with no method names.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import { BacktestGuide } from "./ResearchLive";

afterEach(() => setLocale("es"));

function words(): string {
  return renderToStaticMarkup(<BacktestGuide />)
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ");
}

describe("the backtesting guide", () => {
  test("three lines in Spanish: what it is, how to read it, what it decides", () => {
    setLocale("es");
    const text = words();
    expect(text).toContain("Cómo leer esta pantalla");
    expect(text).toContain("Qué es");
    expect(text).toContain("Cómo leerlo");
    expect(text).toContain("Qué decide");
    expect(text).toContain("sin ver el futuro");
    expect(text).toContain("el número en verde es la combinación elegida");
    expect(text).toContain("Qué modelo puede generar picks");
  });

  test("and in English", () => {
    setLocale("en");
    const text = words();
    expect(text).toContain("How to read this screen");
    expect(text).toContain("without seeing the future");
    expect(text).toContain("the green number is the combination chosen");
    expect(text).toContain("Which model may generate picks");
  });
});
