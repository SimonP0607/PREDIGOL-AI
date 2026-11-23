/// <reference types="bun" />
/**
 * AP-T03: the sentence of the price-movement charts says where the best price started and where it stands, from the captures
 * stored; one capture is no movement.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { setLocale } from "@/lib/i18n";
import { movementReading } from "./movementReading";

afterEach(() => setLocale("es"));

const at = (t: number, odds: number) => ({ t: t * 60_000, odds, bookmaker: "X" });

describe("movement, in words", () => {
  test("from where to where, with the change the panel shows and the captures behind it", () => {
    setLocale("es");
    const r = movementReading([
      { title: "Local", points: [at(1, 2.1), at(2, 2.0), at(3, 1.95)] },
      { title: "Empate", points: [at(1, 3.4), at(2, 3.5)] },
    ])!;
    expect(r.sentence).toBe(
      "Local: la mejor cuota pasó de 2,10 a 1,95 (-7,1\u00a0%) en 3 capturas. Empate: la mejor cuota pasó de 3,40 a 3,50 (+2,9\u00a0%) en 2 capturas.",
    );
    expect(r.n).toBe(2);
    expect(r.n).toBeGreaterThanOrEqual(r.minSample);
  });

  test("one capture is an anecdote, and no capture gives no sentence", () => {
    setLocale("es");
    const r = movementReading([{ title: "Local", points: [at(1, 2.1)] }])!;
    expect(r.sentence).toContain("Local: la mejor cuota es 2,10.");
    expect(r.sentence).toContain("todavía no hay movimiento que leer");
    expect(r.n).toBeLessThan(r.minSample);
    expect(movementReading([{ title: "Local", points: [] }])).toBeNull();
  });

  test("English", () => {
    setLocale("en");
    expect(
      movementReading([{ title: "Home", points: [at(1, 2.1), at(2, 2.5)] }])!.sentence,
    ).toContain("the best price went from 2.10 to 2.50 (+19.0%) over 2 captures.");
  });
});
