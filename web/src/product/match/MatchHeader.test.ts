/// <reference types="bun" />
/**
 * The header's referee (plan Partidos y Match Center, C3): the provider names the referee's country in English only
 * («Spain»); the reader sees it in their language («España»), and a country that cannot be named with certainty is left
 * out rather than shown in English.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { setLocale } from "@/lib/i18n";
import { countryFromEnglish } from "@/product/matches/country";
import { refereeText } from "./model";

setLocale("es");
afterEach(() => setLocale("es"));

describe("the referee's country, in the reader's language", () => {
  test("in Spanish: «(España)», never «(Spain)»", () => {
    expect(refereeText("J. Hernández Maeso", "Spain")).toBe("Árbitro: J. Hernández Maeso (España)");
    expect(refereeText("A. Taylor", "England")).toBe("Árbitro: A. Taylor (Inglaterra)");
    expect(refereeText("W. Roldán", "Colombia")).toBe("Árbitro: W. Roldán (Colombia)");
  });

  test("in English, the country in English", () => {
    setLocale("en");
    expect(refereeText("J. Hernández Maeso", "Spain")).toBe("Referee: J. Hernández Maeso (Spain)");
  });

  test("no country, or one that cannot be named with certainty: the name alone", () => {
    expect(refereeText("J. Hernández Maeso", null)).toBe("Árbitro: J. Hernández Maeso");
    expect(refereeText("J. Brooks", "John, England")).toBe("Árbitro: J. Brooks");
    expect(refereeText("X", "Atlantis")).toBe("Árbitro: X");
    expect(refereeText("X", "Unknown")).toBe("Árbitro: X");
  });

  test("the provider's own spellings: hyphens, short forms and old names", () => {
    expect(countryFromEnglish("Czech-Republic")).toBe("Chequia");
    expect(countryFromEnglish("Saudi-Arabia")).toBe("Arabia Saudí");
    expect(countryFromEnglish("USA")).toBe("Estados Unidos");
    expect(countryFromEnglish("Turkey")).toBe("Turquía");
    expect(countryFromEnglish("Scotland")).toBe("Escocia");
    expect(countryFromEnglish("  spain ")).toBe("España");
    expect(countryFromEnglish("")).toBeNull();
    expect(countryFromEnglish(undefined)).toBeNull();
  });
});
