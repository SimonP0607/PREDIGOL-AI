/**
 * The discounts in the profile's Membership block (UX-005): the one the next payment gets, the loyalty rule with where the
 * reader stands in it, the coupons held, and the field to type a code. Nothing here charges anything - there is no payment
 * gateway: the owner records the payment and, with it, the discount - so the block says that instead of promising a
 * checkout. The loyalty rule is shown only while the owner has it on, and the reader's own counts are the server's.
 */
import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Ticket } from "lucide-react";
import { LiveApiError, v1 } from "@/lib/api/v1/client";
import type { MyDiscounts } from "@/lib/api/v1/types_membership";
import { t } from "@/lib/i18n";
import { errorMessage } from "@/product/shared/States";
import { offerSource, priceLine } from "./membership";

function couponError(e: unknown): string {
  if (e instanceof LiveApiError && e.code === "rate_limited")
    return t("profile.membership.discount.tooMany");
  return errorMessage(e);
}

export function MembershipDiscounts({ discounts }: { discounts: MyDiscounts }) {
  const qc = useQueryClient();
  const [code, setCode] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const redeem = useMutation({
    mutationFn: () => v1.redeemCoupon(code.trim()),
    onSuccess: (r) => {
      setError(null);
      setCode("");
      setDone(t("profile.membership.discount.redeemed", { code: r.code, percent: r.percent }));
      void qc.invalidateQueries({ queryKey: ["v1", "me", "membership"] });
    },
    onError: (e) => {
      setDone(null);
      setError(couponError(e));
    },
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    if (!code.trim() || redeem.isPending) return;
    redeem.mutate();
  }
  const { offer, coupons, loyalty } = discounts;
  const price = offer ? priceLine(offer.prices) : null;
  return (
    <section
      className="space-y-2 rounded-md border border-border p-3"
      data-testid="membership-discounts"
    >
      <h3 className="text-sm font-semibold">{t("profile.membership.discount.title")}</h3>
      {offer ? (
        <div className="space-y-0.5" data-testid="membership-offer" data-kind={offer.kind}>
          <p className="text-sm font-medium text-positive">
            {t("profile.membership.discount.offer", {
              percent: offer.percent,
              source: offerSource(offer),
            })}
          </p>
          {price ? (
            <p className="numeric text-xs" data-testid="membership-offer-price">
              {t("profile.membership.discount.offerPrice", { prices: price })}
            </p>
          ) : null}
          <p className="text-xs text-muted-foreground">{t("profile.membership.discount.how")}</p>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground" data-testid="membership-no-offer">
          {t("profile.membership.discount.none")}
        </p>
      )}
      {loyalty ? (
        <p className="text-xs text-muted-foreground" data-testid="membership-loyalty">
          {t("profile.membership.discount.loyalty", {
            percent: loyalty.percent,
            months: loyalty.after_months,
          })}{" "}
          {loyalty.active
            ? t("profile.membership.discount.loyaltyActive")
            : t("profile.membership.discount.loyaltyProgress", { count: loyalty.paid_months })}
        </p>
      ) : null}
      {coupons.length ? (
        <div className="space-y-1" data-testid="membership-coupons">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-subtle-foreground">
            {t("profile.membership.discount.held")}
          </h4>
          <ul className="flex flex-wrap gap-1.5 text-xs">
            {coupons.map((c) => (
              <li
                key={c.code}
                className="numeric inline-flex items-center gap-1 rounded-full border border-border-strong px-2 py-0.5"
              >
                <Ticket aria-hidden className="h-3 w-3" />
                {c.code} · {c.percent}%
              </li>
            ))}
          </ul>
          <p className="text-caption text-subtle-foreground">
            {t("profile.membership.discount.rule")}
          </p>
        </div>
      ) : null}
      <form onSubmit={submit} className="space-y-1" data-testid="membership-coupon-form">
        <label className="block text-xs font-medium" htmlFor="coupon-code">
          {t("profile.membership.discount.haveOne")}
        </label>
        <div className="flex gap-2">
          <input
            id="coupon-code"
            value={code}
            maxLength={40}
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            onChange={(e) => setCode(e.target.value)}
            placeholder={t("profile.membership.discount.placeholder")}
            className="numeric h-10 min-w-0 flex-1 rounded-md border border-input bg-background px-3 text-base uppercase focus:border-primary focus:outline-none sm:text-sm"
            data-testid="coupon-code"
          />
          <button
            type="submit"
            disabled={!code.trim() || redeem.isPending}
            className="tap-y relative inline-flex h-10 items-center gap-2 rounded-md border border-border-strong px-3 text-sm font-semibold hover:bg-elevated disabled:opacity-50"
            data-testid="coupon-submit"
          >
            {redeem.isPending ? <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> : null}
            {t("profile.membership.discount.use")}
          </button>
        </div>
        {error ? (
          <p role="alert" className="text-xs text-negative" data-testid="coupon-error">
            {error}
          </p>
        ) : null}
        {done ? (
          <p role="status" className="text-xs text-positive" data-testid="coupon-done">
            {done}
          </p>
        ) : null}
      </form>
    </section>
  );
}
