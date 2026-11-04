/** Small pieces shared by the customers' list and the customer's card (plan UX, B10). */
import type { MembershipSummary } from "@/lib/api/v1/types_membership";
import { t } from "@/lib/i18n";
import { formatDateYear } from "@/lib/time";
import { cn } from "@/lib/utils";

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
