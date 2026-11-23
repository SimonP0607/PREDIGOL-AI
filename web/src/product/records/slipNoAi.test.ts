import { describe, expect, test } from "bun:test";
import esRecords from "@/locales/es/records.json";
import enRecords from "@/locales/en/records.json";
import esOdds from "@/locales/es/odds.json";
import enOdds from "@/locales/en/odds.json";

/**
 * AP-L01 (plan de correcciones UX, auditoría del dueño L4): Mi parlay no dice «sin IA» ni afirma que ninguna
 * IA analiza el parlay. La nota se quitó sin afirmar lo contrario; si vuelve una clave con ese texto, falla aquí.
 */
describe("Mi parlay no declara «sin IA»", () => {
  const all: Record<string, unknown> = { esRecords, enRecords, esOdds, enOdds };
  const strings = (
    value: unknown,
    path: string,
    out: Array<[string, string]>,
  ): Array<[string, string]> => {
    if (typeof value === "string") out.push([path, value]);
    else if (value && typeof value === "object")
      for (const [k, v] of Object.entries(value as Record<string, unknown>))
        strings(v, `${path}.${k}`, out);
    return out;
  };

  test("ningún texto de parlay y cuotas dice «sin IA» o «Ninguna IA analiza»", () => {
    const hits = Object.entries(all)
      .flatMap(([name, catalog]) => strings(catalog, name, []))
      .filter(
        ([path, text]) =>
          /sin IA|no AI\b|Ninguna IA|No AI analyses/i.test(text) &&
          !/(aiNone|noReview|noBrief|withoutMarket)/.test(path),
      );
    expect(hits).toEqual([]);
  });

  test("las claves retiradas no existen", () => {
    expect((esRecords as { slip: Record<string, unknown> }).slip.noAi).toBeUndefined();
    expect((enRecords as { slip: Record<string, unknown> }).slip.noAi).toBeUndefined();
    expect((esOdds as { byMatch: Record<string, unknown> }).byMatch.noAi).toBeUndefined();
    expect((enOdds as { byMatch: Record<string, unknown> }).byMatch.noAi).toBeUndefined();
  });
});
