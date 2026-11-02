/// <reference types="bun" />
import { describe, expect, test } from "bun:test";
import { localeFromAcceptLanguage } from "./negotiate";

describe("the reader's language from Accept-Language (plan UX, A1, F08)", () => {
  test("the first of ours in the reader's order", () => {
    expect(localeFromAcceptLanguage("en-GB,en;q=0.9,es;q=0.8")).toBe("en");
    expect(localeFromAcceptLanguage("es-CO,es;q=0.9,en;q=0.8")).toBe("es");
    expect(localeFromAcceptLanguage("fr-FR,fr;q=0.9,en;q=0.7,es;q=0.5")).toBe("en");
    expect(localeFromAcceptLanguage("es;q=0.4,en;q=0.6")).toBe("en");
    expect(localeFromAcceptLanguage("EN-us")).toBe("en");
  });

  test("Spanish when none of ours is asked for, or nothing is said", () => {
    expect(localeFromAcceptLanguage("fr-FR,de;q=0.8")).toBe("es");
    expect(localeFromAcceptLanguage("")).toBe("es");
    expect(localeFromAcceptLanguage(null)).toBe("es");
    expect(localeFromAcceptLanguage("en;q=0")).toBe("es");
    expect(localeFromAcceptLanguage("*")).toBe("es");
  });
});
