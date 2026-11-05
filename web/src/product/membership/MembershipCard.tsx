/**
 * The profile's Membership block (plan UX, A8): the state now in one sentence with its date, the days left, the plan
 * (its price and trial, UX-004), how to renew, and the periods with their payments (amount, currency, method). Read from /me/membership, which no gate
 * closes: a limited reader sees here why, and how to come back.
 */
import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { v1 } from "@/lib/api/v1/client";
import type { MyPeriod } from "@/lib/api/v1/types_membership";
import { t } from "@/lib/i18n";
import { formatDateYear } from "@/lib/time";
import { cn } from "@/lib/utils";
import { ErrorState } from "@/product/shared/States";
import { membershipLine, showsDaysLeft } from "./membership";
import { MembershipPlan } from "./MembershipPlan";
import { RenewOptions } from "./RenewOptions";

function amountOf(p: MyPeriod): string | null {
  if (!p.amount || !p.currency) return null;
  const value = Number(p.amount);
  const number = Number.isFinite(value)
    ? new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value)
    : p.amount;
  return `${number} ${p.currency}`;
}

export function MembershipCard() {
  const q = useQuery({ queryKey: ["v1", "me", "membership"], queryFn: v1.myMembership });
  if (q.isPending)
    return <Loader2 aria-hidden className="h-4 w-4 animate-spin text-muted-foreground" />;
  if (q.isError) {
    return (
      <div className="rounded-md border border-border" data-testid="membership-error">
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      </div>
    );
  }
  const { membership: m, periods, renew, enforced, plan } = q.data;
  if (!m) return null;
  const ended = m.state === "expired" || m.state === "grace" || m.state === "suspended";
  return (
    <div className="space-y-3" data-testid="membership-card" data-state={m.state}>
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={cn(
            "rounded-full border px-2 py-0.5 text-micro font-bold",
            ended
              ? "border-gold/45 bg-gold-soft text-gold-strong"
              : "border-positive/40 text-positive",
          )}
          data-testid="membership-state"
        >
          {t(`profile.membership.state.${m.state}`)}
        </span>
        <span className="text-sm" data-testid="membership-line">
          {membershipLine(m)}
        </span>
      </div>
      {showsDaysLeft(m) ? (
        <p className="text-xs text-muted-foreground" data-testid="membership-days-left">
          {t("profile.membership.daysLeft", { count: m.days_left ?? 0 })}
        </p>
      ) : null}
      {m.will_not_renew ? (
        <p className="text-xs text-muted-foreground">{t("profile.membership.willNotRenew")}</p>
      ) : null}
      {!enforced && m.state === "expired" ? (
        <p className="text-xs text-muted-foreground">{t("profile.membership.notEnforced")}</p>
      ) : null}
      <MembershipPlan plan={plan} />
      {m.state !== "none" ? (
        <div className="space-y-2 rounded-md border border-border p-3">
          <h3 className="text-sm font-semibold">{t("profile.membership.howToRenew")}</h3>
          <p className="text-xs text-muted-foreground">{t("profile.membership.renewHelp")}</p>
          <RenewOptions contact={renew} />
        </div>
      ) : null}
      {periods.length ? (
        <div className="space-y-1.5">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-subtle-foreground">
            {t("profile.membership.history")}
          </h3>
          <ul className="space-y-1 text-xs" data-testid="membership-periods">
            {periods.map((p) => (
              <li key={`${p.kind}-${p.starts_at}`} className="flex flex-wrap gap-x-2">
                <span className="font-medium">{t(`profile.membership.period.${p.kind}`)}</span>
                <span className="numeric text-muted-foreground">
                  {t("profile.membership.range", {
                    from: formatDateYear(p.starts_at),
                    to: formatDateYear(p.ends_at),
                  })}
                </span>
                {amountOf(p) ? (
                  <span className="numeric text-muted-foreground">
                    · {amountOf(p)}
                    {p.method ? ` (${t(`admin.membership.methods.${p.method}`)})` : ""}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
