/** Small pieces shared by the customers' list and the customer's card (plan UX, B10). */
import type { LifecycleState } from "@/lib/api/v1/types_customers";
import type { MembershipSummary } from "@/lib/api/v1/types_membership";
import { t } from "@/lib/i18n";
import { formatDateYear } from "@/lib/time";
import { cn } from "@/lib/utils";
import { lifecycleReasons } from "./lifecycleFigures";

/** A membership's state and the date it turns on, as the owner reads it. «—» for an account that has none (the owner's). */
export function MembershipBadge({ membership }: { membership: MembershipSummary | null }) {
  if (!membership) return <span className="text-caption text-subtle-foreground">—</span>;
  const ended = ["expiring", "grace", "expired", "suspended"].includes(membership.state);
  const date = membership.state === "grace" ? membership.grace_until : membership.ends_at;
  return (
    <span
      className="inline-flex flex-col items-start gap-0.5"
      data-testid="membership-badge"
      data-state={membership.state}
    >
      <span
        className={cn(
          "inline-flex rounded-full border px-1.5 py-0.5 text-[0.65rem] font-semibold",
          ended
            ? "border-gold/45 text-gold-strong"
            : membership.state === "none"
              ? "border-border-strong text-muted-foreground"
              : "border-positive/40 text-positive",
        )}
      >
        {membership.state === "none"
          ? t("admin.membership.noPeriod")
          : t(`profile.membership.state.${membership.state}`)}
      </span>
      {date && membership.state !== "expired" && membership.state !== "none" ? (
        <span className="numeric text-caption text-muted-foreground">{formatDateYear(date)}</span>
      ) : null}
    </span>
  );
}

const LIFECYCLE_TONE: Record<LifecycleState, string> = {
  invited: "border-border-strong text-muted-foreground",
  activated: "border-primary/40 text-primary",
  habitual: "border-positive/40 text-positive",
  at_risk: "border-negative/40 text-negative",
  expiring: "border-gold/45 text-gold-strong",
  renewed: "border-positive/40 text-positive",
  expired: "border-warning/40 text-warning",
};

/** A customer's state of the day (plan UX, B11) with, below it, why. Nothing before the first calculation. */
export function LifecycleBadge({
  state,
  reasons,
}: {
  state: LifecycleState | null;
  reasons: readonly string[];
}) {
  if (!state) return <span className="text-caption text-subtle-foreground">—</span>;
  const why = lifecycleReasons(reasons);
  return (
    <span
      className="inline-flex flex-col items-start gap-0.5"
      data-testid="lifecycle-badge"
      data-state={state}
    >
      <span
        className={cn(
          "inline-flex rounded-full border px-1.5 py-0.5 text-[0.65rem] font-semibold",
          LIFECYCLE_TONE[state],
        )}
      >
        {t(`admin.customers.lifecycle.state.${state}`)}
      </span>
      {why.length > 0 ? (
        <span className="text-caption text-muted-foreground">{why.join(" · ")}</span>
      ) : null}
    </span>
  );
}
