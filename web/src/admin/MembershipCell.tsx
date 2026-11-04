/** An account's membership in the console's list (plan UX, A8): its state and date, and the button to manage it. */
import { useState } from "react";
import { CalendarClock } from "lucide-react";
import type { AdminUser } from "@/lib/api/v1/types_auth";
import { t } from "@/lib/i18n";
import { formatDateYear } from "@/lib/time";
import { cn } from "@/lib/utils";
import { MembershipDialog } from "./MembershipDialog";

export function MembershipCell({ user }: { user: AdminUser }) {
  const [open, setOpen] = useState(false);
  const m = user.membership;
  // The owner's accounts have none; an invited account gets its trial when activated; a deleted one changes no more.
  if (!m || user.status === "invited" || user.status === "deleted") {
    return <span className="text-caption text-subtle-foreground">—</span>;
  }
  const ended = ["expiring", "grace", "expired", "suspended"].includes(m.state);
  const date = m.state === "grace" ? m.grace_until : m.ends_at;
  return (
    <div
      className="flex flex-col items-start gap-1"
      data-testid={`membership-${user.id}`}
      data-state={m.state}
    >
      <span
        className={cn(
          "inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[0.65rem] font-semibold",
          ended
            ? "border-gold/45 text-gold-strong"
            : m.state === "none"
              ? "border-border-strong text-muted-foreground"
              : "border-positive/40 text-positive",
        )}
      >
        {m.state === "none"
          ? t("admin.membership.noPeriod")
          : t(`profile.membership.state.${m.state}`)}
      </span>
      {date && m.state !== "expired" && m.state !== "none" ? (
        <span className="numeric text-caption text-muted-foreground">
          {m.state === "grace"
            ? t("admin.membership.graceUntil", { date: formatDateYear(date) })
            : t("admin.membership.until", { date: formatDateYear(date) })}
        </span>
      ) : null}
      {m.will_not_renew ? (
        <span className="text-caption text-muted-foreground">
          {t("admin.membership.willNotRenew")}
        </span>
      ) : null}
      <button
        type="button"
        onClick={() => setOpen(true)}
        data-testid={`membership-manage-${user.id}`}
        className="tap-y relative inline-flex items-center gap-1 rounded-md border border-border-strong px-2 py-1 text-xs font-medium hover:bg-elevated pointer-coarse:px-2.5 pointer-coarse:py-2"
      >
        <CalendarClock aria-hidden className="h-3 w-3" />
        {t("admin.membership.manage")}
      </button>
      {open ? (
        <MembershipDialog userId={user.id} email={user.email} open={open} onOpenChange={setOpen} />
      ) : null}
    </div>
  );
}
