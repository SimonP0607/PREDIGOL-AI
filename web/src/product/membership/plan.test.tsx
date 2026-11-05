/// <reference types="bun" />
/**
 * The plan in the profile's Membership block (UX-004): the owner's price in each currency, the trial, what the plan
 * includes and how it is paid - and no price at all while none is set.
 */
import { afterAll, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import type { MembershipPlan as Plan } from "@/lib/api/v1/types_membership";
import { setLocale, t } from "@/lib/i18n";
import { priceLine, priceText } from "./membership";
import { MembershipPlan } from "./MembershipPlan";

afterAll(() => setLocale("es"));

const PLAN: Plan = {
  trial_days: 20,
  prices: [
    { currency: "COP", amount: "150000" },
    { currency: "USD", amount: "50" },
  ],
};

describe("the price in words", () => {
  test("each currency is said in the reader's language", () => {
    setLocale("es");
    expect(priceText(PLAN.prices[0]!)).toBe("150.000 COP");
    expect(priceText({ currency: "USD", amount: "49.9" })).toBe("49,9 USD");
    setLocale("en");
    expect(priceText(PLAN.prices[0]!)).toBe("150,000 COP");
    expect(priceText({ currency: "USD", amount: "49.9" })).toBe("49.9 USD");
  });

  test("both prices on one line, one when only one is set, none when none is", () => {
    setLocale("es");
    expect(priceLine(PLAN.prices)).toBe("150.000 COP o 50 USD al mes");
    expect(priceLine([PLAN.prices[1]!])).toBe("50 USD al mes");
    expect(priceLine([])).toBeNull();
    setLocale("en");
    expect(priceLine(PLAN.prices)).toBe("150,000 COP or 50 USD a month");
  });
});

describe("the plan block", () => {
  test("price, trial, what it includes and how it is paid", () => {
    setLocale("es");
    const out = renderToStaticMarkup(<MembershipPlan plan={PLAN} />);
    expect(out).toContain("150.000 COP o 50 USD al mes");
    expect(out).toContain("20 días de prueba");
    expect(out).toContain('data-testid="membership-includes"');
    expect(out.match(/<li /g)).toHaveLength(6);
    expect(out).toContain(t("profile.membership.plan.how"));
    expect(out).toContain("nunca se inventa uno para llenar el espacio");
  });

  test("with no price set it shows none and still tells the trial", () => {
    setLocale("es");
    const out = renderToStaticMarkup(<MembershipPlan plan={{ trial_days: 20, prices: [] }} />);
    expect(out).not.toContain('data-testid="membership-price"');
    expect(out).toContain("20 días de prueba");
  });

  test("every line exists in both languages", () => {
    for (const locale of ["es", "en"] as const) {
      setLocale(locale);
      for (const key of ["title", "price", "or", "priceHelp", "trial", "includesTitle", "how"])
        expect(t(`profile.membership.plan.${key}`, { prices: "x", days: 1 })).not.toContain(
          "profile.membership.plan",
        );
      for (const key of ["analysis", "forecast", "explain", "picks", "myPicks", "help"])
        expect(t(`profile.membership.plan.includes.${key}`)).not.toContain("profile.membership");
    }
  });
});
