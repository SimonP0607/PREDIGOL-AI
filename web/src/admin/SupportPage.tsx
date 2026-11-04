/**
 * Soporte (/admin/support, plan UX, A14; section 32): the readers' messages and their privacy requests in one inbox -
 * what waits for an answer first, by priority (urgent, high, medium, low), the oldest first - with the counts of the
 * header (waiting, past their target, urgent, open), filters by status, category and priority, and each message's
 * context (the screen, the error's reference, the version, the device, the installed app, the match). A support message
 * is answered here - the reader is told by e-mail - or noted from a talk on WhatsApp or an e-mail (no e-mail then); a
 * privacy request keeps its legal rules (the deadline, the one extension, the deletion after the answer). Every answer
 * is an audited admin write.
 */
import { useId, useState, type FormEvent, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ChevronDown, LifeBuoy, Loader2 } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { v1 } from "@/lib/api/v1/client";
import type {
  AdminTicket,
  InboxStatus,
  SupportChannel,
  SupportPriority,
  SupportStatus,
  TicketCategory,
} from "@/lib/api/v1/types_support";
import { t } from "@/lib/i18n";
import { formatDateTime } from "@/lib/time";
import { cn } from "@/lib/utils";
import { dayOf } from "@/product/legal/links";
import { Card, ErrorState, errorMessage } from "@/product/shared/States";
import { DeletionStep, PrivacyAnswer } from "./PrivacyRequests";
import { isAnonymised } from "./anonymised";

const STATUSES: readonly InboxStatus[] = ["open", "waiting", "answered", "closed", "all"];
const CATEGORIES: readonly TicketCategory[] = [
  "access",
  "account",
  "technical",
  "wrong_data",
  "suggestion",
  "complaint",
  "privacy",
];
const PRIORITIES: readonly SupportPriority[] = ["urgent", "high", "medium", "low"];
const CHANNELS: readonly SupportChannel[] = ["web", "whatsapp", "email"];
const ANSWER_STATUSES: readonly SupportStatus[] = ["answered", "open", "closed"];

const PRIORITY_TONE: Readonly<Record<SupportPriority, string>> = {
  urgent: "border-negative/40 bg-negative-soft text-negative",
  high: "border-warning/40 bg-warning-soft text-warning",
  medium: "border-border-strong text-foreground",
  low: "border-border text-muted-foreground",
};

const selectClass =
  "h-9 rounded-md border border-input bg-background px-2 text-sm pointer-coarse:h-11";

function Count({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: string | undefined;
}) {
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2">
      <div className="text-caption text-muted-foreground">{label}</div>
      <div className={cn("numeric font-display text-xl font-semibold", tone)}>{value}</div>
    </div>
  );
}

export function SupportPage() {
  const [status, setStatus] = useState<InboxStatus>("open");
  const [category, setCategory] = useState<TicketCategory | "">("");
  const [priority, setPriority] = useState<SupportPriority | "">("");
  const q = useQuery({
    queryKey: ["admin", "support", status, category, priority],
    queryFn: () =>
      v1.supportInbox({
        status,
        category: category || undefined,
        priority: priority || undefined,
      }),
  });
  return (
    <div className="space-y-5" data-testid="admin-support">
      <PageHeader title={t("support.admin.title")} description={t("support.admin.subtitle")} />
      {q.data ? (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4" data-testid="support-counts">
          <Count label={t("support.admin.counts.waiting")} value={q.data.counts.waiting} />
          <Count
            label={t("support.admin.counts.late")}
            value={q.data.counts.late}
            tone={q.data.counts.late ? "text-negative" : undefined}
          />
          <Count
            label={t("support.admin.counts.urgent")}
            value={q.data.counts.urgent}
            tone={q.data.counts.urgent ? "text-negative" : undefined}
          />
          <Count label={t("support.admin.counts.open")} value={q.data.counts.open} />
        </div>
      ) : null}
      <Card className="p-3">
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-caption">
            {t("support.admin.filters.status")}
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value as InboxStatus)}
              className={selectClass}
              data-testid="support-filter-status"
            >
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {t(`support.admin.filters.statusValue.${s}`)}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-caption">
            {t("support.admin.filters.category")}
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value as TicketCategory | "")}
              className={selectClass}
              data-testid="support-filter-category"
            >
              <option value="">{t("support.admin.filters.all")}</option>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {t(`support.admin.category.${c}`)}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-caption">
            {t("support.admin.filters.priority")}
            <select
              value={priority}
              onChange={(e) => setPriority(e.target.value as SupportPriority | "")}
              className={selectClass}
              data-testid="support-filter-priority"
            >
              <option value="">{t("support.admin.filters.all")}</option>
              {PRIORITIES.map((p) => (
                <option key={p} value={p}>
                  {t(`support.admin.priority.${p}`)}
                </option>
              ))}
            </select>
          </label>
        </div>
      </Card>
      {q.isPending ? (
        <Loader2 aria-hidden className="h-5 w-5 animate-spin" />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : q.data.tickets.length === 0 ? (
        <p className="text-sm text-muted-foreground" data-testid="support-empty">
          {t("support.admin.empty")}
        </p>
      ) : (
        <ul className="space-y-2">
          {q.data.tickets.map((ticket) => (
            <TicketRow key={ticket.id} ticket={ticket} />
          ))}
        </ul>
      )}
    </div>
  );
}

function TicketRow({ ticket }: { ticket: AdminTicket }) {
  const [open, setOpen] = useState(ticket.waiting && ticket.priority === "urgent");
  const panelId = useId();
  const last = ticket.messages[ticket.messages.length - 1];
  return (
    <li
      className={cn(
        "rounded-lg border bg-card",
        ticket.late ? "border-negative/50" : "border-border",
      )}
      data-testid={`support-ticket-${ticket.id}`}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={panelId}
        className="flex w-full items-start justify-between gap-3 p-3 text-left"
      >
        <span className="min-w-0 space-y-1">
          <span className="flex flex-wrap items-center gap-1.5">
            <span
              className={cn(
                "rounded-full border px-2 py-0.5 text-caption font-medium",
                PRIORITY_TONE[ticket.priority],
              )}
            >
              {t(`support.admin.priority.${ticket.priority}`)}
            </span>
            <span className="text-sm font-semibold">
              {t(`support.admin.category.${ticket.category}`)}
            </span>
            <span className="text-caption text-muted-foreground">#{ticket.id}</span>
            <span className="text-caption text-muted-foreground">
              · {t(`support.admin.status.${ticket.status}`)}
            </span>
            {ticket.late ? (
              <span className="text-caption font-semibold text-negative">
                · {t("support.admin.late")}
              </span>
            ) : null}
            {ticket.at_risk ? (
              <span
                className="rounded-full border border-negative/40 px-1.5 py-0.5 text-[0.65rem] font-semibold text-negative"
                data-testid={`ticket-at-risk-${ticket.id}`}
                title={t("support.admin.atRiskHint")}
              >
                {t("support.admin.atRisk")}
              </span>
            ) : null}
          </span>
          <span className="block break-all text-caption text-muted-foreground">
            {ticket.display_name} · {ticket.email}
            {ticket.account_status === "deleted" ? ` · ${t("support.admin.deleted")}` : null}
          </span>
          {last ? (
            <span className="line-clamp-2 block text-sm text-foreground/90">{last.body}</span>
          ) : null}
          <span className="block text-caption text-muted-foreground">
            {t("support.admin.opened", { date: formatDateTime(ticket.opened_at) })}
            {ticket.status !== "closed" && ticket.respond_by && !ticket.first_answer_at
              ? ` · ${t("support.admin.respondBy", { date: formatDateTime(ticket.respond_by) })}`
              : null}
            {ticket.deadline && ticket.status !== "closed"
              ? ` · ${t("support.admin.deadline", { date: dayOf(ticket.deadline) })}${
                  ticket.extended ? ` (${t("support.admin.extended")})` : ""
                }`
              : null}
          </span>
        </span>
        <ChevronDown
          aria-hidden
          className={cn("mt-1 h-4 w-4 shrink-0 transition-transform", open && "rotate-180")}
        />
      </button>
      {open ? (
        <div id={panelId} className="space-y-3 border-t border-border p-3">
          {ticket.kind === "support" ? <ContextBlock ticket={ticket} /> : null}
          <ol className="space-y-2 border-l border-border pl-3">
            {ticket.messages.map((m, i) => (
              <li key={`${m.at}-${i}`} className="text-xs">
                <span className="font-semibold">{t(`support.ticket.author.${m.author}`)}</span>
                {m.channel !== "web" ? (
                  <span className="text-muted-foreground">
                    {" "}
                    · {t(`support.ticket.channel.${m.channel}`)}
                  </span>
                ) : null}
                <span className="text-muted-foreground"> · {formatDateTime(m.at)}</span>
                <p className="whitespace-pre-line break-words text-sm">{m.body}</p>
              </li>
            ))}
          </ol>
          {ticket.first_answer_at ? (
            <p className="text-caption text-muted-foreground">
              {t("support.admin.firstAnswer", { date: formatDateTime(ticket.first_answer_at) })}
            </p>
          ) : null}
          {ticket.effort !== null ? (
            <p className="text-caption text-muted-foreground">
              {t("support.admin.effort", { value: ticket.effort })}
            </p>
          ) : null}
          {ticket.kind === "support" ? (
            ticket.status !== "closed" ? (
              <SupportAnswer ticket={ticket} />
            ) : null
          ) : (
            <PrivacyBlock ticket={ticket} />
          )}
        </div>
      ) : null}
    </li>
  );
}

function ContextBlock({ ticket }: { ticket: AdminTicket }) {
  const c = ticket.context;
  if (!c) {
    return <p className="text-caption text-muted-foreground">{t("support.admin.context.none")}</p>;
  }
  const rows: Array<[string, ReactNode]> = [];
  if (c.route) rows.push([t("support.admin.context.route"), <code key="r">{c.route}</code>]);
  if (c.request_id)
    rows.push([t("support.admin.context.request"), <code key="q">{c.request_id}</code>]);
  if (c.web_version) rows.push([t("support.admin.context.version"), c.web_version]);
  if (c.device)
    rows.push([t("support.admin.context.device"), t(`support.admin.context.devices.${c.device}`)]);
  if (c.pwa !== undefined && c.pwa !== null) {
    rows.push([
      t("support.admin.context.pwa"),
      c.pwa ? t("support.admin.context.yes") : t("support.admin.context.no"),
    ]);
  }
  if (c.match_id) {
    rows.push([
      t("support.admin.context.match"),
      <Link
        key="m"
        to="/matches/$fixtureId"
        params={{ fixtureId: String(c.match_id) }}
        className="font-medium text-primary underline-offset-4 hover:underline"
      >
        #{c.match_id}
      </Link>,
    ]);
  }
  return (
    <div className="rounded-md bg-elevated/60 p-2" data-testid={`support-context-${ticket.id}`}>
      <p className="mb-1 text-caption font-semibold">{t("support.admin.context.title")}</p>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-caption">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="break-all">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function SupportAnswer({ ticket }: { ticket: AdminTicket }) {
  const qc = useQueryClient();
  const [body, setBody] = useState("");
  const [channel, setChannel] = useState<SupportChannel>("web");
  const [status, setStatus] = useState<SupportStatus>("answered");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [notice, setNotice] = useState(false);
  const textId = useId();

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setFailure(null);
    try {
      await v1.answerTicket(ticket.id, { body: body.trim(), status, channel });
      setBody("");
      setNotice(true);
      await qc.invalidateQueries({ queryKey: ["admin", "support"] });
    } catch (err) {
      setFailure(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={(e) => void submit(e)}
      className="space-y-2"
      data-testid={`support-answer-${ticket.id}`}
    >
      <label htmlFor={textId} className="text-xs font-semibold">
        {t("support.admin.answer.label")}
      </label>
      <textarea
        id={textId}
        value={body}
        rows={4}
        maxLength={4000}
        placeholder={t("support.admin.answer.placeholder")}
        onChange={(e) => setBody(e.target.value)}
        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:border-primary focus:outline-none"
      />
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-caption">
          {t("support.admin.answer.channel")}
          <select
            value={channel}
            onChange={(e) => setChannel(e.target.value as SupportChannel)}
            className={selectClass}
            data-testid={`support-answer-channel-${ticket.id}`}
          >
            {CHANNELS.map((c) => (
              <option key={c} value={c}>
                {t(`support.admin.answer.channels.${c}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-caption">
          {t("support.admin.answer.status")}
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as SupportStatus)}
            className={selectClass}
            data-testid={`support-answer-status-${ticket.id}`}
          >
            {ANSWER_STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`support.admin.answer.statuses.${s}`)}
              </option>
            ))}
          </select>
        </label>
        <button
          type="submit"
          disabled={busy || !body.trim()}
          data-testid={`support-answer-send-${ticket.id}`}
          className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-semibold text-primary-foreground disabled:opacity-50 pointer-coarse:h-11"
        >
          {busy ? (
            <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
          ) : (
            <LifeBuoy aria-hidden className="h-4 w-4" />
          )}
          {t("support.admin.answer.send")}
        </button>
      </div>
      {failure ? (
        <p role="alert" className="text-xs text-negative">
          {failure}
        </p>
      ) : null}
      {notice && !failure ? (
        <p role="status" className="text-xs text-positive">
          {t("support.admin.notice")}
        </p>
      ) : null}
    </form>
  );
}

function PrivacyBlock({ ticket }: { ticket: AdminTicket }) {
  const qc = useQueryClient();
  const [notice, setNotice] = useState<string | null>(null);
  const refresh = () => void qc.invalidateQueries({ queryKey: ["admin", "support"] });
  return (
    <div className="space-y-2">
      <p className="text-caption text-muted-foreground">{t("support.admin.privacyNote")}</p>
      {notice ? (
        <p role="status" className="text-xs text-positive">
          {notice}
        </p>
      ) : null}
      {ticket.status !== "closed" ? (
        <PrivacyAnswer id={ticket.id} canExtend={!ticket.extended} onDone={refresh} />
      ) : null}
      {ticket.kind === "privacy_deletion" && !isAnonymised(ticket.email) ? (
        <DeletionStep
          request={ticket}
          onDone={(n) => {
            setNotice(n);
            refresh();
          }}
        />
      ) : null}
    </div>
  );
}
