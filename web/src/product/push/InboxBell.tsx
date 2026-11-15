/**
 * The bell of «Avisos» in the top bar (plan maestro UX/UI 2026, decision 1): the way to the inbox, with how many notices
 * are unread. Nothing is drawn while the inbox is off (FBI_INBOX).
 */
import { Link } from "@tanstack/react-router";
import { Bell } from "lucide-react";
import { t } from "@/lib/i18n";
import { bellFigure, useInboxUnread } from "./inbox";

export function InboxBell() {
  const { open, unread } = useInboxUnread();
  if (!open) return null;
  const figure = bellFigure(unread);
  return (
    <Link
      to="/inbox"
      aria-label={unread > 0 ? t("push.inbox.bellUnread", { count: unread }) : t("push.inbox.bell")}
      data-testid="inbox-bell"
      data-unread={unread}
      className="relative flex h-11 w-11 items-center justify-center rounded-field text-foreground-soft transition-colors hover:bg-elevated hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <Bell aria-hidden className="h-5 w-5" />
      {figure ? (
        <span
          aria-hidden
          className="numeric absolute right-1 top-1 flex h-[1.125rem] min-w-[1.125rem] items-center justify-center rounded-full bg-gold px-1 text-[0.6875rem] font-extrabold leading-none text-gold-foreground"
        >
          {figure}
        </span>
      ) : null}
    </Link>
  );
}
