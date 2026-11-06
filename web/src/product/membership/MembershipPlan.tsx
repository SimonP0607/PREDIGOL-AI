/**
 * The one plan, in the profile's Membership block (UX-004): the monthly price in each currency the owner offers, the
 * trial, what the plan includes and how it is paid today. No payment gateway is behind it - the reader pays by the means
 * agreed and the owner records it - so the block says so instead of promising a checkout. With no price set it says no
 * price: a price is never guessed.
 */
import { Check } from "lucide-react";
import type { MembershipPlan as Plan } from "@/lib/api/v1/types_membership";
import { t } from "@/lib/i18n";
import { priceLine } from "./membership";

const INCLUDES = ["analysis", "forecast", "explain", "picks", "myPicks", "help"] as const;

export function MembershipPlan({ plan }: { plan: Plan }) {
  const price = priceLine(plan.prices);
  return (
    <section
      className="space-y-2 rounded-md border border-border p-3"
      data-testid="membership-plan"
    >
      <h3 className="text-sm font-semibold">{t("profile.membership.plan.title")}</h3>
      {price ? (
        <p className="text-sm" data-testid="membership-price">
          <span className="numeric font-semibold">{price}</span>
          {plan.prices.length > 1 ? (
            <span className="ml-2 text-xs text-muted-foreground">
              {t("profile.membership.plan.priceHelp")}
            </span>
          ) : null}
        </p>
      ) : null}
      <p className="text-xs text-muted-foreground" data-testid="membership-trial">
        {t("profile.membership.plan.trial", { days: plan.trial_days })}
      </p>
      <div className="space-y-1">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-subtle-foreground">
          {t("profile.membership.plan.includesTitle")}
        </h4>
        <ul className="space-y-1 text-xs" data-testid="membership-includes">
          {INCLUDES.map((key) => (
            <li key={key} className="flex gap-2">
              <Check aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0 text-positive" />
              <span>{t(`profile.membership.plan.includes.${key}`)}</span>
            </li>
          ))}
        </ul>
      </div>
      <p className="text-xs text-muted-foreground" data-testid="membership-how">
        {t("profile.membership.plan.how")}
      </p>
      <p className="text-xs text-muted-foreground" data-testid="membership-not-bets">
        {t("profile.membership.plan.notBets")}
      </p>
    </section>
  );
}
