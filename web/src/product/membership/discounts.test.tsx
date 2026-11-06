/// <reference types="bun" />
/**
 * The discounts in the profile's Membership block and the owner's coupons (UX-005), without a browser: what the reader
 * is told about the next payment, the loyalty rule, the coupons held and the field to type a code - and nothing the
 * server did not say; the amounts the console proposes; and the three states of a coupon.
 */
import { afterAll, describe, expect, test } from "bun:test";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import type { ReactNode } from "react";
import type { AdminCoupon, MyDiscounts } from "@/lib/api/v1/types_membership";
import { couponState, lastMomentOf } from "@/admin/coupons";
import { setLocale, t } from "@/lib/i18n";
import { offerSource, suggestedAmount } from "./membership";
import { MembershipDiscounts } from "./MembershipDiscounts";

afterAll(() => setLocale("es"));

function html(node: ReactNode): string {
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>{node}</QueryClientProvider>,
  );
}

const NOTHING: MyDiscounts = { offer: null, coupons: [], loyalty: null };
const LOYALTY = { percent: 20, after_months: 2, paid_months: 1, active: false };
const PRICES = [
  { currency: "COP", amount: "120000" },
  { currency: "USD", amount: "40" },
];

describe("the reader's discounts", () => {
  test("nothing offered, no loyalty rule: it says none, and still has the field for a code", () => {
    setLocale("es");
    const out = html(<MembershipDiscounts discounts={NOTHING} />);
    expect(out).toContain('data-testid="membership-no-offer"');
    expect(out).toContain(t("profile.membership.discount.none"));
    expect(out).not.toContain('data-testid="membership-loyalty"');
    expect(out).not.toContain('data-testid="membership-coupons"');
    expect(out).toContain('data-testid="coupon-code"');
    expect(out).toContain('data-testid="coupon-submit"');
  });

  test("the loyalty rule, with where the reader stands, while it is not reached", () => {
    setLocale("es");
    const out = html(<MembershipDiscounts discounts={{ ...NOTHING, loyalty: LOYALTY }} />);
    expect(out).toContain("20% en cada renovación");
    expect(out).toContain("2 meses de membresía pagados");
    expect(out).toContain("Llevas 1 mes pagado.");
    expect(out).not.toContain('data-testid="membership-offer"');
    setLocale("en");
    expect(html(<MembershipDiscounts discounts={{ ...NOTHING, loyalty: LOYALTY }} />)).toContain(
      "You have paid 1 month so far.",
    );
  });

  test("the loyalty discount in force: the percentage, the prices with it, and how it is applied", () => {
    setLocale("es");
    const out = html(
      <MembershipDiscounts
        discounts={{
          offer: { kind: "loyalty", percent: 20, code: null, prices: PRICES },
          coupons: [],
          loyalty: { ...LOYALTY, paid_months: 3, active: true },
        }}
      />,
    );
    expect(out).toContain("20% de descuento por tu fidelidad");
    expect(out).toContain("120.000 COP o 40 USD al mes");
    expect(out).toContain('data-kind="loyalty"');
    expect(out).toContain("Ya lo tienes.");
    expect(out).toContain(t("profile.membership.discount.how"));
    expect(out).toContain("No se cobra nada automáticamente");
  });

  test("a coupon: its code in the sentence, the coupons held, and the rule that they do not add up", () => {
    setLocale("es");
    const out = html(
      <MembershipDiscounts
        discounts={{
          offer: { kind: "coupon", percent: 30, code: "BIENVENIDA", prices: PRICES },
          coupons: [
            { code: "BIENVENIDA", percent: 30 },
            { code: "OTRO", percent: 10 },
          ],
          loyalty: null,
        }}
      />,
    );
    expect(out).toContain("30% de descuento por el cupón BIENVENIDA");
    expect(out).toContain('data-kind="coupon"');
    expect(out).toContain("BIENVENIDA · 30%");
    expect(out).toContain("OTRO · 10%");
    expect(out).toContain("no se suma al descuento por fidelidad: se aplica el mayor");
  });

  test("a price is not said when the owner offers none", () => {
    setLocale("es");
    const out = html(
      <MembershipDiscounts
        discounts={{
          offer: { kind: "coupon", percent: 30, code: "X1Y2", prices: [] },
          coupons: [],
          loyalty: null,
        }}
      />,
    );
    expect(out).toContain("30% de descuento");
    expect(out).not.toContain('data-testid="membership-offer-price"');
  });

  test("where a discount comes from, in both languages", () => {
    setLocale("es");
    expect(offerSource({ kind: "coupon", code: "AMIGOS" })).toBe("el cupón AMIGOS");
    expect(offerSource({ kind: "loyalty", code: null })).toBe("tu fidelidad");
    setLocale("en");
    expect(offerSource({ kind: "coupon", code: "AMIGOS" })).toBe("the coupon AMIGOS");
    expect(offerSource({ kind: "loyalty", code: null })).toBe("your loyalty");
  });
});

describe("the amount the console proposes", () => {
  const BASE = [
    { currency: "COP", amount: "150000" },
    { currency: "USD", amount: "50" },
  ];
  test("the months at the monthly price, in the currency of the form", () => {
    expect(suggestedAmount(BASE, "COP", 1)).toBe("150000");
    expect(suggestedAmount(BASE, "cop", 3)).toBe("450000");
    expect(suggestedAmount(BASE, " USD ", 2)).toBe("100");
    expect(suggestedAmount(PRICES, "COP", 2)).toBe("240000");
  });
  test("with cents when there are, and nothing for a currency the owner does not offer", () => {
    expect(suggestedAmount([{ currency: "USD", amount: "42.5" }], "USD", 3)).toBe("127.50");
    expect(suggestedAmount([{ currency: "USD", amount: "19.99" }], "USD", 1)).toBe("19.99");
    expect(suggestedAmount(BASE, "EUR", 1)).toBeNull();
    expect(suggestedAmount([], "COP", 1)).toBeNull();
    expect(suggestedAmount([{ currency: "COP", amount: "nope" }], "COP", 1)).toBeNull();
  });
});

describe("the owner's coupons", () => {
  const coupon = (over: Partial<AdminCoupon>): AdminCoupon => ({
    id: 1,
    code: "AMIGOS",
    percent: 10,
    note: null,
    valid_until: null,
    max_redemptions: null,
    created_at: "2026-11-05T12:00:00Z",
    disabled_at: null,
    redemptions: 0,
    used: 0,
    active: true,
    ...over,
  });
  const NOW = Date.parse("2026-11-10T12:00:00Z");

  test("off, past its last day, out of places or live - in that order of weight", () => {
    expect(couponState(coupon({}), NOW)).toBe("active");
    expect(couponState(coupon({ disabled_at: "2026-11-06T00:00:00Z" }), NOW)).toBe("disabled");
    expect(couponState(coupon({ valid_until: "2026-11-09T00:00:00Z" }), NOW)).toBe("expired");
    expect(couponState(coupon({ valid_until: "2026-11-11T00:00:00Z" }), NOW)).toBe("active");
    expect(couponState(coupon({ max_redemptions: 5, redemptions: 5 }), NOW)).toBe("full");
    expect(couponState(coupon({ max_redemptions: 5, redemptions: 4 }), NOW)).toBe("active");
    expect(
      couponState(
        coupon({ disabled_at: "2026-11-06T00:00:00Z", valid_until: "2026-11-09T00:00:00Z" }),
        NOW,
      ),
    ).toBe("disabled");
  });

  test("the last day of a date field is the end of that day; nothing for an empty or wrong one", () => {
    const end = lastMomentOf("2026-12-31");
    expect(end).not.toBeNull();
    const d = new Date(end!);
    expect([d.getFullYear(), d.getMonth() + 1, d.getDate(), d.getHours()]).toEqual([
      2026, 12, 31, 23,
    ]);
    expect(lastMomentOf("")).toBeNull();
    expect(lastMomentOf("31/12/2026")).toBeNull();
    expect(lastMomentOf("2026-13-45")).not.toBe("2026-13-45");
  });

  test("every word of the console's coupons and of the discounts exists in Spanish and English", () => {
    for (const locale of ["es", "en"] as const) {
      setLocale(locale);
      for (const key of [
        "title",
        "description",
        "code",
        "percent",
        "note",
        "validUntil",
        "maxRedemptions",
        "create",
        "created",
        "empty",
        "holders",
        "used",
        "noLimit",
        "noDate",
        "state.active",
        "state.disabled",
        "state.expired",
        "state.full",
        "disable",
        "confirmDisable",
        "yes",
        "no",
      ])
        expect(t(`admin.coupons.${key}`, { code: "X", percent: 1 }), key).not.toContain("admin.");
      for (const key of [
        "title",
        "offer",
        "sourceCoupon",
        "sourceLoyalty",
        "offerPrice",
        "how",
        "none",
        "loyalty",
        "loyaltyActive",
        "held",
        "rule",
        "haveOne",
        "placeholder",
        "use",
        "redeemed",
        "tooMany",
        "carried",
      ])
        expect(
          t(`profile.membership.discount.${key}`, { code: "X", percent: 1, months: 2 }),
          key,
        ).not.toContain("profile.");
      for (const code of [
        "coupon_invalid",
        "coupon_expired",
        "coupon_exhausted",
        "coupon_already_yours",
        "invalid_coupon_code",
        "coupon_exists",
        "coupon_not_found",
        "coupon_disabled",
        "invalid_percent",
        "invalid_note",
        "invalid_valid_until",
        "invalid_max_redemptions",
        "no_discount",
      ])
        expect(t(`errors.code.${code}`), code).not.toContain("errors.");
    }
  });
});
