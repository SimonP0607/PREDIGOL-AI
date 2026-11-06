/// <reference types="bun" />
/**
 * One sentence about what PrediGol is, said the same way on every screen that says it (plan de cierre UX, 1.1): a
 * sports-analysis and value-detection platform that guarantees no result or profit, is not a bookmaker, takes no money
 * for bets and is only for people aged 18 or over. The terms and the policy say it in the backend
 * (tests/unit/test_customer_legal.py); here the footer notice, the app's description, the welcome and the
 * membership block - in both languages - and the installed app's manifest.
 */
import { afterAll, describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { Disclaimer } from "@/components/system/Disclaimer";
import type { MembershipPlan as Plan } from "@/lib/api/v1/types_membership";
import { setLocale, t } from "@/lib/i18n";
import { MembershipPlan } from "@/product/membership/MembershipPlan";

afterAll(() => setLocale("es"));

const PLAN: Plan = { trial_days: 20, prices: [{ currency: "COP", amount: "150000" }] };

/** What every surface must say, by language. Each phrase is a lower-case fragment of the sentence. */
const SAYS = {
  es: [
    "no garantiza resultados ni beneficios",
    "no es una casa de apuestas",
    "recibe dinero de apuestas",
  ],
  en: ["guarantees no results or profits", "is not a bookmaker", "money for bets"],
} as const;
const LOCALES = ["es", "en"] as const;

describe("the same sentence on every screen", () => {
  test("the sentence itself says what PrediGol is, what it is not and who it is for", () => {
    for (const l of LOCALES) {
      setLocale(l);
      const what = t("common.what").toLowerCase();
      expect(what).toContain(
        l === "es"
          ? "plataforma de análisis deportivo y detección de valor"
          : "sports-analysis and value-detection platform",
      );
      expect(what).toContain(
        l === "es"
          ? "no garantiza resultados ni beneficios"
          : "does not guarantee results or profits",
      );
      expect(what).toContain(l === "es" ? "no es una casa de apuestas" : "is not a bookmaker");
      expect(what).toContain(l === "es" ? "recibe dinero de apuestas" : "money for bets");
      expect(what).toContain(l === "es" ? "18 años" : "18 or over");
    }
  });

  test("the notice on every screen: an analysis platform, no result or profit promised, not a bookmaker, +18", () => {
    for (const l of LOCALES) {
      setLocale(l);
      const html = renderToStaticMarkup(<Disclaimer />).toLowerCase();
      for (const phrase of SAYS[l]) expect(html).toContain(phrase);
      expect(html).toContain(l === "es" ? "+18" : "18+");
    }
  });

  test("the app's description (the page's head) does not call PrediGol a bookmaker and says what it is", () => {
    setLocale("es");
    expect(t("common.meta.description")).toContain(
      "plataforma de análisis deportivo y detección de valor",
    );
    expect(t("common.meta.description")).toContain("No es una casa de apuestas");
    setLocale("en");
    expect(t("common.meta.description")).toContain("sports-analysis and value-detection platform");
    expect(t("common.meta.description")).toContain("Not a bookmaker");
  });

  test("the installed app's manifest says the same", () => {
    const manifest = JSON.parse(
      readFileSync(
        join(import.meta.dir, "..", "..", "..", "public", "manifest.webmanifest"),
        "utf8",
      ),
    ) as { description: string };
    expect(manifest.description).toContain("Plataforma de análisis deportivo y detección de valor");
    expect(manifest.description).toContain("No es una casa de apuestas");
  });

  test("the membership block says what the membership pays for: access to the analysis, never bets", () => {
    for (const l of LOCALES) {
      setLocale(l);
      const html = renderToStaticMarkup(<MembershipPlan plan={PLAN} />);
      expect(html).toContain('data-testid="membership-not-bets"');
      expect(html.toLowerCase()).toContain(
        l === "es" ? "no es una casa de apuestas" : "is not a bookmaker",
      );
      expect(html.toLowerCase()).toContain(
        l === "es" ? "recibe dinero de apuestas" : "money for bets",
      );
    }
  });
});
