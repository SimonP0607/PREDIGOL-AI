/** The wait before signing in again, said in minutes (plan UX, A1, defect F01: the page always said "60 s"). */
import { afterAll, describe, expect, test } from "bun:test";
import { setLocale } from "@/lib/i18n";
import { tooManyAttempts, waitText } from "./wait";

afterAll(() => setLocale("es"));

describe("the wait, in the reader's words", () => {
  test("Spanish: minutes, then hours and minutes - never the old 60 s", () => {
    setLocale("es");
    expect(waitText(901)).toBe("15 minutos"); // a fresh 15-minute lock, as the API rounds it
    expect(waitText(1801)).toBe("30 minutos"); // the lock doubled
    expect(waitText(61)).toBe("1 minuto");
    expect(waitText(60)).toBe("1 minuto");
    expect(waitText(59)).toBe("menos de un minuto");
    expect(waitText(3601)).toBe("1 hora");
    expect(waitText(5101)).toBe("1 h y 25 min");
    expect(waitText(86_401)).toBe("24 horas"); // the longest lock
    expect(waitText(null)).toBe("unos minutos");
    expect(waitText(0)).toBe("unos minutos");
    expect(tooManyAttempts(901)).toBe("Demasiados intentos. Espera 15 minutos y vuelve a probar.");
    expect(tooManyAttempts(901)).not.toContain("60 s");
  });

  test("English", () => {
    setLocale("en");
    expect(waitText(901)).toBe("15 minutes");
    expect(waitText(61)).toBe("1 minute");
    expect(waitText(30)).toBe("less than a minute");
    expect(waitText(7201)).toBe("2 hours");
    expect(waitText(5101)).toBe("1 h 25 min");
    expect(tooManyAttempts(null)).toBe("Too many attempts. Wait a few minutes and try again.");
  });
});
