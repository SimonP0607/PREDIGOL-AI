/**
 * The queue of messages to readers (plan UX, A5): whether sending is on, how many left today, the last seven days by
 * status and the latest messages - the recipient, the template, the fate and the provider's short error code, never
 * the body. A message's preview renders it as it would leave now (subject, text and the button's address).
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Eye, Loader2, Mail, RefreshCw } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { v1 } from "@/lib/api/v1/client";
import type { MessageStatus, OutboxMessage, OutboxSummary } from "@/lib/api/v1/types_messaging";
import { t } from "@/lib/i18n";
import { formatDateTime } from "@/lib/time";
import { cn } from "@/lib/utils";
import { Card, ErrorState } from "@/product/shared/States";
import { STATUSES, templateName } from "./messages";

const TONE: Readonly<Record<MessageStatus, string>> = {
  queued: "border-border-strong text-muted-foreground",
  sent: "border-positive/40 bg-positive-soft text-positive",
  failed: "border-negative/40 bg-negative-soft text-negative",
  bounced: "border-negative/40 bg-negative-soft text-negative",
  complained: "border-warning/40 bg-warning-soft text-warning",
  suppressed: "border-border-strong text-muted-foreground",
};

function StatusBadge({ status }: { status: MessageStatus }) {
  return (
    <span className={cn("rounded-full border px-2 py-0.5 text-xs font-medium", TONE[status])}>
      {t(`admin.messages.status.${status}`)}
    </span>
  );
}

function Preview({ id }: { id: number }) {
  const q = useQuery({
    queryKey: ["admin", "messages", "preview", id],
    queryFn: () => v1.messagePreview(id),
  });
  if (q.isPending) return <Loader2 aria-hidden className="h-4 w-4 animate-spin" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  return (
    <div className="space-y-2 rounded-md bg-elevated/60 p-3" data-testid={`message-preview-${id}`}>
      <p className="text-sm font-semibold">{q.data.subject}</p>
      <pre className="whitespace-pre-wrap break-words font-sans text-xs">{q.data.text}</pre>
      {q.data.link ? (
        <p className="text-xs">
          {t("admin.messages.link")}:{" "}
          <a
            href={q.data.link}
            className="break-all font-medium text-primary underline-offset-4 hover:underline"
            data-testid="message-preview-link"
          >
            {q.data.link}
          </a>
        </p>
      ) : null}
    </div>
  );
}

function MessageRow({ message }: { message: OutboxMessage }) {
  const [open, setOpen] = useState(false);
  return (
    <li
      className="space-y-2 rounded-md border border-border p-3"
      data-testid={`message-${message.id}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-0.5">
          <p className="text-sm font-medium" data-testid="message-template">
            {templateName(message.template)}
          </p>
          <p className="break-all text-xs text-muted-foreground">
            {message.user_email} · {message.locale.toUpperCase()} ·{" "}
            {formatDateTime(message.created_at)}
          </p>
          <p className="text-xs text-muted-foreground">
            {t("admin.messages.attempts", { n: message.attempts })}
            {message.sent_at
              ? ` · ${t("admin.messages.sentAt", { date: formatDateTime(message.sent_at) })}`
              : ""}
            {message.next_attempt_at
              ? ` · ${t("admin.messages.nextAt", { date: formatDateTime(message.next_attempt_at) })}`
              : ""}
          </p>
          {message.last_error ? (
            <p className="text-xs text-negative">{message.last_error}</p>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={message.status} />
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            data-testid="message-preview-toggle"
            className="tap-y relative inline-flex h-8 items-center gap-1 rounded-md border border-border-strong px-2 text-xs hover:bg-elevated pointer-coarse:h-11"
          >
            <Eye aria-hidden className="h-3.5 w-3.5" />
            {open ? t("admin.messages.hide") : t("admin.messages.preview")}
          </button>
        </div>
      </div>
      {open ? <Preview id={message.id} /> : null}
    </li>
  );
}

export function QueueState({ summary }: { summary: OutboxSummary }) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs" data-testid="messages-state">
      <span
        className={cn(
          "rounded-full border px-2 py-0.5 font-semibold",
          summary.sending
            ? "border-positive/40 bg-positive-soft text-positive"
            : "border-warning/40 bg-warning-soft text-warning",
        )}
      >
        {summary.sending ? t("admin.messages.sendingOn") : t("admin.messages.sendingOff")}
      </span>
      {!summary.provider ? (
        <span className="text-muted-foreground">{t("admin.messages.providerMissing")}</span>
      ) : null}
      <span className="text-muted-foreground">
        {t("admin.messages.today", { sent: summary.sent_today, cap: summary.daily_cap })}
      </span>
    </div>
  );
}

export function MessagesPage() {
  const [status, setStatus] = useState<MessageStatus | undefined>(undefined);
  const q = useQuery({
    queryKey: ["admin", "messages", status ?? "all"],
    queryFn: () => v1.messageQueue(status),
  });
  return (
    <div className="space-y-5">
      <PageHeader
        title={t("admin.pages.messages.title")}
        description={t("admin.pages.messages.description")}
        actions={
          <button
            type="button"
            onClick={() => void q.refetch()}
            aria-label={t("common.retry")}
            className="tap relative rounded-md border border-border-strong p-2 hover:bg-elevated"
          >
            <RefreshCw aria-hidden className={cn("h-4 w-4", q.isFetching && "animate-spin")} />
          </button>
        }
      />
      <Card className="space-y-4 p-4">
        {q.isPending ? (
          <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
        ) : q.isError ? (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        ) : (
          <>
            <QueueState summary={q.data} />
            <div
              className="flex flex-wrap gap-2"
              role="group"
              aria-label={t("admin.messages.filter")}
            >
              <button
                type="button"
                aria-pressed={status === undefined}
                onClick={() => setStatus(undefined)}
                className={cn(
                  "tap-y relative rounded-md border px-2 py-1 text-xs",
                  status === undefined
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border-strong",
                )}
              >
                {t("admin.messages.all")}
              </button>
              {STATUSES.map((s) => (
                <button
                  key={s}
                  type="button"
                  aria-pressed={status === s}
                  onClick={() => setStatus(s)}
                  data-testid={`messages-filter-${s}`}
                  className={cn(
                    "tap-y relative rounded-md border px-2 py-1 text-xs",
                    status === s
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border-strong",
                  )}
                >
                  {t(`admin.messages.status.${s}`)} · {q.data.counts[s] ?? 0}
                </button>
              ))}
            </div>
            <p className="text-caption text-muted-foreground">{t("admin.messages.countsHelp")}</p>
            {q.data.messages.length === 0 ? (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <Mail aria-hidden className="h-4 w-4" />
                {t("admin.messages.empty")}
              </p>
            ) : (
              <ul className="space-y-3" data-testid="messages-list">
                {q.data.messages.map((m) => (
                  <MessageRow key={m.id} message={m} />
                ))}
              </ul>
            )}
          </>
        )}
      </Card>
    </div>
  );
}
