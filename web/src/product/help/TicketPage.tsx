/**
 * One of the reader's messages (/help/messages/$ticketId, plan UX, A14): the thread with PrediGol's answers - the ones
 * noted from WhatsApp or an e-mail say so -, its state and, while nobody has answered, when it will be. While it is open
 * the reader adds to it or closes it («Ya está resuelto»); once closed, the optional question on how easy it was, asked
 * once. Another reader's message, or one that does not exist, reads the same: not found. The e-mail's button leads here.
 */
import { useId, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowLeft, CheckCircle2, Loader2 } from "lucide-react";
import { v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type { SupportState, SupportTicket } from "@/lib/api/v1/types_support";
import { t } from "@/lib/i18n";
import { formatDateTime } from "@/lib/time";
import { cn } from "@/lib/utils";
import { Card, EmptyState, ErrorState, SkeletonCards, errorMessage } from "@/product/shared/States";
import { MAX_TEXT } from "@/product/support/report";
import { ReportButton } from "./HelpPage";

const EFFORT = [1, 2, 3, 4, 5] as const;

function useSaved() {
  const qc = useQueryClient();
  return (ticket: SupportTicket) => {
    qc.setQueryData<SupportState>(["me", "support"], (old) =>
      old ? { ...old, tickets: old.tickets.map((x) => (x.id === ticket.id ? ticket : x)) } : old,
    );
  };
}

export function TicketPage({ ticketId }: { ticketId: number }) {
  const q = useQuery(live.support);
  const back = (
    <Link
      to="/help"
      className="tap-y relative inline-flex min-h-11 items-center gap-1.5 self-start text-sm font-medium text-primary"
      data-testid="ticket-back"
    >
      <ArrowLeft aria-hidden className="h-4 w-4" />
      {t("support.ticket.back")}
    </Link>
  );
  if (q.isPending) {
    return (
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-4">
        {back}
        <SkeletonCards count={2} />
      </div>
    );
  }
  if (q.isError) {
    return (
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-4">
        {back}
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      </div>
    );
  }
  const ticket = q.data.tickets.find((x) => x.id === ticketId);
  if (!ticket) {
    return (
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-4" data-testid="ticket-missing">
        {back}
        <EmptyState title={t("support.ticket.notFound")} />
      </div>
    );
  }
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-4" data-testid="ticket-page">
      {back}
      <Thread ticket={ticket} enabled={q.data.enabled} />
    </div>
  );
}

function Thread({ ticket, enabled }: { ticket: SupportTicket; enabled: boolean }) {
  const closed = ticket.status === "closed";
  return (
    <>
      <header className="flex flex-col gap-1">
        <h1 className="font-display text-2xl font-bold tracking-tight">
          {t("support.ticket.title", { id: ticket.id })}
        </h1>
        <p className="text-sm text-muted-foreground">
          {t("support.ticket.about", {
            category: t(`support.report.category.${ticket.category}.label`).toLowerCase(),
          })}{" "}
          · {t("support.ticket.opened", { date: formatDateTime(ticket.opened_at) })}
        </p>
        <p
          className={cn(
            "mt-1 self-start rounded-full px-2.5 py-0.5 text-caption font-semibold",
            ticket.status === "answered"
              ? "bg-primary/15 text-primary"
              : ticket.status === "open"
                ? "bg-warning/15 text-warning"
                : "bg-muted text-muted-foreground",
          )}
          data-testid="ticket-status"
        >
          {t(`support.ticket.status.${ticket.status}`)}
        </p>
        {ticket.respond_by ? (
          <p className="text-sm" data-testid="ticket-respond-by">
            {t("support.ticket.respondBy", { date: formatDateTime(ticket.respond_by) })}
          </p>
        ) : null}
      </header>
      <ol className="flex flex-col gap-3" data-testid="ticket-thread">
        {ticket.messages.map((m, i) => {
          const mine = m.author === "customer";
          return (
            <li
              key={`${m.at}-${i}`}
              className={cn(
                "max-w-[92%] rounded-xl border p-3",
                mine
                  ? "self-end border-primary/30 bg-primary/5"
                  : "self-start border-border bg-card",
              )}
              data-author={m.author}
            >
              <p className="text-caption text-muted-foreground">
                <span className="font-semibold text-foreground">
                  {t(`support.ticket.author.${m.author}`)}
                </span>
                {m.channel !== "web" ? ` · ${t(`support.ticket.channel.${m.channel}`)}` : null} ·{" "}
                {formatDateTime(m.at)}
              </p>
              <p className="mt-1 whitespace-pre-line break-words text-sm">{m.body}</p>
            </li>
          );
        })}
      </ol>
      {closed ? (
        <Closed ticket={ticket} enabled={enabled} />
      ) : enabled ? (
        <Reply ticket={ticket} />
      ) : (
        <p className="text-sm text-muted-foreground">{t("support.ticket.readOnly")}</p>
      )}
    </>
  );
}

function Reply({ ticket }: { ticket: SupportTicket }) {
  const saved = useSaved();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState<"reply" | "close" | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const id = useId();

  async function run(kind: "reply" | "close") {
    setBusy(kind);
    setFailure(null);
    try {
      saved(
        kind === "reply"
          ? await v1.replyTicket(ticket.id, text.trim())
          : await v1.closeTicket(ticket.id),
      );
      if (kind === "reply") setText("");
    } catch (err) {
      setFailure(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card className="p-4">
      <form
        className="flex flex-col gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) void run("reply");
        }}
      >
        <label htmlFor={id} className="text-sm font-semibold">
          {t("support.ticket.replyLabel")}
        </label>
        <textarea
          id={id}
          value={text}
          rows={3}
          maxLength={MAX_TEXT}
          onChange={(e) => setText(e.target.value)}
          data-testid="ticket-reply-text"
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-base focus:border-primary focus:outline-none sm:text-sm"
        />
        {failure ? (
          <p role="alert" className="text-sm text-negative">
            {failure}
          </p>
        ) : null}
        <div className="flex flex-wrap justify-between gap-2">
          <button
            type="button"
            onClick={() => void run("close")}
            disabled={busy !== null}
            data-testid="ticket-resolved"
            className="inline-flex min-h-11 items-center gap-2 rounded-md border border-border-strong px-4 text-sm font-medium hover:bg-elevated disabled:opacity-50"
          >
            {busy === "close" ? (
              <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
            ) : (
              <CheckCircle2 aria-hidden className="h-4 w-4" />
            )}
            {t("support.ticket.resolved")}
          </button>
          <button
            type="submit"
            disabled={busy !== null || !text.trim()}
            data-testid="ticket-reply"
            className="inline-flex min-h-11 items-center gap-2 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-50"
          >
            {busy === "reply" ? <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> : null}
            {t("support.ticket.reply")}
          </button>
        </div>
      </form>
    </Card>
  );
}

function Closed({ ticket, enabled }: { ticket: SupportTicket; enabled: boolean }) {
  const saved = useSaved();
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [thanked, setThanked] = useState(false);

  async function rate(effort: number) {
    setBusy(true);
    setFailure(null);
    try {
      saved(await v1.rateTicket(ticket.id, effort));
      setThanked(true);
    } catch (err) {
      setFailure(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      {ticket.effort === null ? (
        <Card className="p-4">
          <fieldset className="flex flex-col gap-2" data-testid="ticket-effort" disabled={busy}>
            <legend className="text-sm font-semibold">{t("support.ticket.effort.question")}</legend>
            <p className="text-caption text-muted-foreground">
              {t("support.ticket.effort.optional")}
            </p>
            <div className="flex flex-wrap gap-2">
              {EFFORT.map((n) => (
                <button
                  key={n}
                  type="button"
                  onClick={() => void rate(n)}
                  data-testid={`ticket-effort-${n}`}
                  className="inline-flex min-h-11 items-center rounded-md border border-border-strong px-3 text-sm hover:bg-elevated"
                >
                  {t(`support.ticket.effort.scale.${n}`)}
                </button>
              ))}
            </div>
            {failure ? (
              <p role="alert" className="text-sm text-negative">
                {failure}
              </p>
            ) : null}
          </fieldset>
        </Card>
      ) : (
        <p className="text-sm text-muted-foreground" data-testid="ticket-effort-done" role="status">
          {thanked ? `${t("support.ticket.effort.thanks")} ` : null}
          {t("support.ticket.effort.yours", {
            answer: t(`support.ticket.effort.scale.${ticket.effort}`),
          })}
        </p>
      )}
      <p className="text-sm text-muted-foreground">{t("support.ticket.closedNote")}</p>
      {enabled ? <ReportButton className="self-start" /> : null}
    </div>
  );
}
