/// <reference types="bun" />
/**
 * AP-A01 (audit finding A10): a console label never says a version is what the readers see. The day's selection of
 * the evaluation is not published (FBI_PICKS_SOURCE is off), so its title says so in plain words and the version
 * name stays in the technical detail.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { setLocale, t } from "@/lib/i18n";

afterEach(() => setLocale("es"));

const TITLES = ["intel.day.v5Title", "intel.day.v6Title"] as const;
const OTHERS = ["intel.day.v5Empty", "intel.day.picksOfDay"] as const;

describe("Operación: the labels of the day's selections", () => {
  test("es: the title says the users do not see it, and carries no version name", () => {
    setLocale("es");
    for (const key of TITLES) {
      const text = t(key);
      expect(text, key).toMatch(/los usuarios no la ven/);
      expect(text, key).not.toMatch(/daily-set|\bv[56]\b/i);
    }
    expect(t("intel.day.v5Title")).toBe("Selección del día (evaluación; los usuarios no la ven)");
  });

  test("en: the same", () => {
    setLocale("en");
    for (const key of TITLES) {
      const text = t(key);
      expect(text, key).toMatch(/users do not see it/);
      expect(text, key).not.toMatch(/daily-set|\bv[56]\b/i);
    }
  });

  test("no label calls a version what the users see; the version stays in the technical detail", () => {
    for (const locale of ["es", "en"] as const) {
      setLocale(locale);
      for (const key of [...TITLES, ...OTHERS]) {
        expect(t(key), `${locale} ${key}`).not.toMatch(/lo que ven los usuarios|what users see/i);
        expect(t(key), `${locale} ${key}`).not.toMatch(/daily-set|\(v[56]\)/i);
      }
      expect(t("intel.day.v5Detail")).toContain("daily-set-v5");
      expect(t("intel.day.v6Detail")).toContain("daily-set-v6");
    }
  });
});
