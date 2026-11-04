/**
 * The reader's notifications, in their profile (plan UX, A5; F12): which e-mails PrediGol sends them, by category -
 * the account, its security, their privacy requests and the legal changes always; membership reminders and support
 * answers as they choose - and, when their address bounced or they marked a message as spam, why nothing arrives.
 * Then the weekly summary by e-mail, asked for apart (plan UX, B8: DigestSection), while it can reach the reader; below,
 * the notices on their devices (plan UX, B7: PushSection), once the owner made them available.
 */
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Loader2, Mail } from "lucide-react";
import { v1 } from "@/lib/api/v1/client";
import type {
  EmailCategory,
  MessageCategory,
  NotificationPreferences,
} from "@/lib/api/v1/types_messaging";
import { t } from "@/lib/i18n";
import { track } from "@/lib/track";
import { formatDateTime } from "@/lib/time";
import { cn } from "@/lib/utils";
import { ErrorState, errorMessage } from "@/product/shared/States";
import { DigestSection } from "./DigestSection";
import { PushSection } from "./PushSection";

export const PREFERENCES_KEY = ["me", "notification-preferences"] as const;

function CategoryRow({
  item,
  busy,
  onToggle,
}: {
  item: EmailCategory;
  busy: boolean;
  onToggle: (item: EmailCategory) => void;
}) {
  const label = t(`profile.notifications.category.${item.category}`);
  const help = t(`profile.notifications.categoryHelp.${item.category}`);
  if (item.locked) {
    return (
      <li
        className="flex min-h-11 items-center justify-between gap-3 py-2"
        data-testid={`notify-${item.category}`}
      >
        <span className="min-w-0">
          <span className="block text-sm font-medium">{label}</span>
          <span className="block text-xs text-muted-foreground">{help}</span>
        </span>
        <span className="shrink-0 rounded-full border border-border-strong px-2 py-0.5 text-xs text-muted-foreground">
          {t("profile.notifications.always")}
        </span>
      </li>
    );
  }
  return (
    <li data-testid={`notify-${item.category}`}>
      <button
        type="button"
        role="switch"
        aria-checked={item.on}
        disabled={busy}
        onClick={() => onToggle(item)}
        className="flex min-h-11 w-full items-center justify-between gap-3 rounded-md py-2 text-left hover:bg-elevated/60 disabled:opacity-60"
      >
        <span className="min-w-0">
          <span className="block text-sm font-medium">{label}</span>
          <span className="block text-xs text-muted-foreground">{help}</span>
        </span>
        <span className="flex shrink-0 items-center gap-2">
          {busy ? <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> : null}
          <span className="sr-only">
            {item.on ? t("profile.notifications.on") : t("profile.notifications.off")}
          </span>
          <span
            aria-hidden
            className={cn(
              "relative inline-flex h-6 w-11 items-center rounded-full border-2 border-transparent transition-colors",
              item.on ? "bg-primary" : "bg-input",
            )}
          >
            <span
              className={cn(
                "block h-5 w-5 rounded-full bg-background shadow transition-transform",
                item.on ? "translate-x-5" : "translate-x-0",
              )}
            />
          </span>
        </span>
      </button>
    </li>
  );
}

/** The block as it reads: what is on, what is always sent, and the address's state. */
export function NotificationsView({
  prefs,
  busy,
  failure,
  onToggle,
}: {
  prefs: NotificationPreferences;
  busy: MessageCategory | null;
  failure: string | null;
  onToggle: (item: EmailCategory) => void;
}) {
  return (
    <div className="space-y-3" data-testid="notifications">
      <p className="text-xs text-muted-foreground">{t("profile.notifications.help")}</p>
      {prefs.email_status !== "ok" ? (
        <div
          role="status"
          className="flex gap-2 rounded-md border border-warning/40 bg-warning-soft p-3 text-xs"
          data-testid="notify-email-status"
        >
          <AlertTriangle aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
          <span>
            {t(`profile.notifications.status.${prefs.email_status}`)}
            {prefs.email_status_at ? (
              <span className="block text-muted-foreground">
                {t("profile.notifications.statusSince", {
                  date: formatDateTime(prefs.email_status_at),
                })}
              </span>
            ) : null}
          </span>
        </div>
      ) : null}
      <h3 className="flex items-center gap-2 text-sm font-semibold">
        <Mail aria-hidden className="h-4 w-4 text-primary" />
        {t("profile.notifications.email")}
      </h3>
      <ul className="divide-y divide-border">
        {prefs.email.map((item) => (
          <CategoryRow
            key={item.category}
            item={item}
            busy={busy === item.category}
            onToggle={onToggle}
          />
        ))}
      </ul>
      {failure ? (
        <p role="alert" className="text-xs text-negative">
          {failure}
        </p>
      ) : null}
    </div>
  );
}

export function NotificationsPanel() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: PREFERENCES_KEY, queryFn: v1.myNotificationPreferences });
  const [busy, setBusy] = useState<MessageCategory | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  async function toggle(item: EmailCategory) {
    setBusy(item.category);
    setFailure(null);
    try {
      const next = await v1.updateNotificationPreferences({ email: { [item.category]: !item.on } });
      qc.setQueryData(PREFERENCES_KEY, next);
      track(item.on ? "notification_disabled" : "notification_enabled", {
        channel: "email",
        category: item.category,
      });
    } catch (err) {
      setFailure(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  if (q.isPending) return <Loader2 aria-hidden className="h-4 w-4 animate-spin" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  return (
    <div className="space-y-4">
      <NotificationsView
        prefs={q.data}
        busy={busy}
        failure={failure}
        onToggle={(item) => void toggle(item)}
      />
      <DigestSection />
      <PushSection />
    </div>
  );
}
