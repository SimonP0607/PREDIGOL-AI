/**
 * The membership's notice at the top of the reader's pages (plan UX, A8): from 7 days before the end (3 in a trial),
 * the day before, during the 3 days of grace (fixed) and - on the pages a limited account still opens - the limit.
 * One line and a link to the profile's membership; it never covers the tab bar (it sits under the header, in the
 * page's flow).
 */
import { Link } from "@tanstack/react-router";
import { CalendarClock } from "lucide-react";
import { useAuth } from "@/lib/auth/AuthProvider";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { bannerText } from "./membership";

export function MembershipBanner() {
  const auth = useAuth();
  const m = auth.user?.membership;
  const text = m ? bannerText(m) : null;
  if (!m || !text) return null;
  const firm = m.state === "grace" || m.limited;
  return (
    <div
      role="status"
      data-testid="membership-banner"
      data-state={m.state}
      className={cn(
        "px-safe mx-auto mt-3 flex w-full max-w-6xl flex-wrap items-center gap-x-3 gap-y-1 rounded-md border px-3 py-2 text-xs",
        firm
          ? "border-gold/45 bg-gold-soft text-foreground"
          : "border-border bg-elevated/40 text-muted-foreground",
      )}
    >
      <CalendarClock aria-hidden className="h-4 w-4 shrink-0 text-gold-strong" />
      <span className="min-w-0 flex-1">{text}</span>
      <Link
        to="/profile"
        hash="membership"
        data-testid="membership-banner-action"
        className="tap-y relative font-medium text-primary underline-offset-2 hover:underline"
      >
        {t("profile.membership.banner.action")}
      </Link>
    </div>
  );
}
