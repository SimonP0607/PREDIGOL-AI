/// <reference types="bun" />
/** C-11 1.1 (AP-A04): each code of the closed list has its phrase in both languages; a sentence with no code stays as the server wrote it. */
import { describe, expect, test } from "bun:test";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { setLocale } from "@/lib/i18n";
import type { ResearchReasonCode } from "@/lib/api/v1/types_research";
import { reasonText, RESEARCH_REASON_CATALOG } from "./researchReasonText";

const CODES: ResearchReasonCode[] = [
  "campeon_mercado",
  "variante_mercado",
  "mejor_que_mercado",
  "aporta_informacion",
  "rechazado_peor_que_mercado",
  "evidencia_insuficiente",
  "sin_partidos_comunes",
  "muestra_insuficiente",
];

describe("the reason of a research role", () => {
  test("every code has a phrase in Spanish and in English, and nothing else is left over", () => {
    for (const lang of ["es", "en"] as const) {
      const keys = Object.keys(RESEARCH_REASON_CATALOG[lang]).filter((k) => k !== "title");
      expect(keys.sort()).toEqual([...CODES].sort());
    }
  });

  test("the codes are the server's list (fbi.research.reason_codes)", () => {
    const path = join(import.meta.dir, "../../../backend/src/fbi/research/reason_codes.py");
    if (!existsSync(path)) return; // the web checked out alone
    const source = readFileSync(path, "utf8");
    const block = /ReasonCode = Literal\[([\s\S]*?)\]/.exec(source)?.[1] ?? "";
    const server = [...block.matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
    expect(server.sort()).toEqual([...CODES].sort());
  });

  test("a code reads in the reader's language; no code keeps the server's sentence; neither is null", () => {
    setLocale("es");
    const es = reasonText({
      role_reason: "worse than the champion and adds nothing to it",
      role_reason_code: "rechazado_peor_que_mercado",
    });
    expect(es).toBe(RESEARCH_REASON_CATALOG.es.rechazado_peor_que_mercado);
    setLocale("en");
    expect(reasonText({ role_reason: "x", role_reason_code: "campeon_mercado" })).toBe(
      RESEARCH_REASON_CATALOG.en.campeon_mercado,
    );
    expect(
      reasonText({ role_reason: "a sentence the list does not know", role_reason_code: null }),
    ).toBe("a sentence the list does not know");
    expect(reasonText({ role_reason: "an older answer" })).toBe("an older answer");
    expect(reasonText({ role_reason: null, role_reason_code: null })).toBeNull();
    setLocale("es");
  });
});
