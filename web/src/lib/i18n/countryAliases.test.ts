/// <reference types="bun" />
/** AP-B02: «España» finds Spain in the three searches: the table, and the merge. */
import { afterEach, describe, expect, test } from "bun:test";
import { setLocale } from "@/lib/i18n";
import { countryAliases, mergeAliased } from "./countryAliases";

afterEach(() => setLocale("es"));

describe("what a Spanish reader types", () => {
  const cases: Array<[string, string]> = [
    ["España", "Spain"],
    ["espana", "Spain"],
    ["Inglaterra", "England"],
    ["Alemania", "Germany"],
    ["Brasil", "Brazil"],
    ["Bélgica", "Belgium"],
    ["Sudáfrica", "South Africa"],
    ["Estados Unidos", "USA"],
    ["Países Bajos", "Netherlands"],
    ["Escocia", "Scotland"],
    ["Irlanda del Norte", "Northern Ireland"],
  ];
  for (const [typed, english] of cases)
    test(`«${typed}» also searches «${english}»`, () => {
      setLocale("es");
      expect(countryAliases(typed)).toContain(english);
    });

  test("the exact name comes first: «Estados Unidos» before «Estonia»", () => {
    setLocale("es");
    const list = countryAliases("Esta");
    expect(list.length).toBeLessThanOrEqual(3);
    expect(countryAliases("Estados Unidos")[0]).toBe("United States");
  });

  test("two letters, nothing: «es» is not Spain", () => {
    setLocale("es");
    expect(countryAliases("es")).toEqual([]);
    expect(countryAliases("")).toEqual([]);
  });

  test("a text the provider's own search already finds is not asked twice", () => {
    setLocale("es");
    expect(countryAliases("Spain")).toEqual([]);
    expect(countryAliases("Mexico")).toEqual([]);
  });
});

describe("what an English reader types", () => {
  test("the provider's own spelling that differs: «United States» also searches «USA»", () => {
    setLocale("en");
    expect(countryAliases("United States")).toContain("USA");
    expect(countryAliases("Spain")).toEqual([]);
  });
});

describe("the merge", () => {
  const team = (id: number, name: string) => ({ id, name });

  test("the national team first, then the typed text's own, never twice", () => {
    const own = [team(5, "Real Espana"), team(2, "Spain")];
    const aliased = [[team(9, "Spain U21"), team(2, "Spain"), team(7, "Spain W")]];
    const merged = mergeAliased(own, aliased, ["Spain"]);
    expect(merged.map((t) => t.id)).toEqual([2, 5, 9, 7]);
  });

  test("nothing aliased: the answer is the own list", () => {
    const own = [team(1, "A"), team(2, "B")];
    expect(mergeAliased(own, [], [])).toEqual(own);
  });
});
