/**
 * The owner's queue of payment notices, «ya pagué» (UX-092; the notices are UX-090/091). Each notice is checked against
 * the money that reached his account and decided once: approve (what he received and the months it covers: the payment and
 * the period are created together), reject (a reason the reader sees) or, for an approval made by mistake, annul it. The
 * oddities that ask for a second look - a different amount, the same reference on other notices, a late check - are
 * flagged and need his tick. A decision cannot be sent twice: its buttons wait while the answer is on the way, and the
 * server decides each notice only once anyway.
 */
import { useRef, useState } from "react";
import { Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Banknote, Check, Loader2, Undo2, X } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { v1 } from "@/lib/api/v1/client";
import type { AdminPaymentRequest, DecisionCode } from "@/lib/api/v1/types_payment_requests";
import { DECISION_CODES } from "@/lib/api/v1/types_payment_requests";
import { t } from "@/lib/i18n";
import { formatDateTime, formatDateYear } from "@/lib/time";
import { cn } from "@/lib/utils";
import { priceText } from "@/product/membership/membership";
import { Card, EmptyState, ErrorState, SkeletonCards, errorMessage } from "@/product/shared/States";
import {
  NOTE_MAX,
  amountOk,
  approveBody,
  flagsOf,
  needsTick,
  noteOk,
  who,
  type Flag,
} from "./paymentQueue";

type Scope = "submitted" | "all";
type Panel = "approve" | "reject" | "annul";

const KEY = ["admin", "payment-requests"] as const;
const FIELD = "w-full rounded-md border border-border-strong bg-background px-3 py-2 text-sm";
const BUTTON =
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-border-strong px-3 text-sm font-medium hover:bg-elevated disabled:opacity-50";
const PRIMARY =
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-50";

function money(amount: string, currency: string): string {
  return priceText({ amount, currency });
}

function dueText(r: AdminPaymentRequest): string {
  return formatDateYear(`${r.due_on}T12:00:00-05:00`);
}

function FlagList({ flags }: { flags: readonly Flag[] }) {
  if (!flags.length) return null;
  return (
    <ul className="space-y-1" data-testid="payment-flags">
      {flags.map((f) => (
        <li
          key={f}
          data-flag={f}
          className="flex items-start gap-2 rounded-md border border-gold/40 bg-gold/10 px-2 py-1.5 text-xs"
        >
          <AlertTriangle aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0 text-gold" />
          {t(`admin.payments.flag.${f}`)}
        </li>
      ))}
    </ul>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="break-words text-sm font-medium">{value}</dd>
    </div>
  );
}

function Approve({
  r,
  flags,
  busy,
  onDecide,
  onClose,
}: {
  r: AdminPaymentRequest;
  flags: readonly Flag[];
  busy: boolean;
  onDecide: (body: ReturnType<typeof approveBody>) => void;
  onClose: () => void;
}) {
  const [received, setReceived] = useState(String(Number(r.declared_amount)));
  const [months, setMonths] = useState(1);
  const [ticked, setTicked] = useState(false);
  const ok = amountOk(received) && (!needsTick(flags) || ticked);
  return (
    <form
      className="space-y-3 rounded-md border border-border p-3"
      data-testid="payment-approve"
      onSubmit={(e) => {
        e.preventDefault();
        if (ok && !busy) onDecide(approveBody(r.declared_amount, received, months));
      }}
    >
      <label className="block space-y-1 text-sm">
        <span className="font-medium">
          {t("admin.payments.approve.received", { currency: r.currency })}
        </span>
        <input
          data-testid="payment-received"
          inputMode="decimal"
          className={FIELD}
          value={received}
          onChange={(e) => setReceived(e.target.value)}
          aria-invalid={!amountOk(received)}
        />
        <span className="text-xs text-muted-foreground">
          {t("admin.payments.approve.receivedHelp")}
        </span>
      </label>
      <label className="block space-y-1 text-sm">
        <span className="font-medium">{t("admin.payments.approve.months")}</span>
        <select
          data-testid="payment-months"
          className={FIELD}
          value={months}
          onChange={(e) => setMonths(Number(e.target.value))}
        >
          {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
            <option key={m} value={m}>
              {t("admin.payments.approve.monthsOption", { count: m })}
            </option>
          ))}
        </select>
      </label>
      {needsTick(flags) ? (
        <label className="flex min-h-11 items-start gap-2 text-sm">
          <input
            type="checkbox"
            data-testid="payment-tick"
            checked={ticked}
            onChange={(e) => setTicked(e.target.checked)}
            className="mt-1 h-4 w-4"
          />
          {t("admin.payments.approve.tick")}
        </label>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <button
          type="submit"
          className={PRIMARY}
          disabled={!ok || busy}
          data-testid="payment-approve-confirm"
        >
          {busy ? (
            <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
          ) : (
            <Check aria-hidden className="h-4 w-4" />
          )}
          {t("admin.payments.approve.confirm")}
        </button>
        <button type="button" className={BUTTON} onClick={onClose} disabled={busy}>
          {t("admin.payments.back")}
        </button>
      </div>
    </form>
  );
}

function Reject({
  busy,
  onDecide,
  onClose,
}: {
  busy: boolean;
  onDecide: (v: { code: DecisionCode; note: string }) => void;
  onClose: () => void;
}) {
  const [code, setCode] = useState<DecisionCode>("not_received");
  const [note, setNote] = useState("");
  const ok = noteOk(note);
  return (
    <form
      className="space-y-3 rounded-md border border-border p-3"
      data-testid="payment-reject"
      onSubmit={(e) => {
        e.preventDefault();
        if (ok && !busy) onDecide({ code, note: note.trim() });
      }}
    >
      <label className="block space-y-1 text-sm">
        <span className="font-medium">{t("admin.payments.reject.code")}</span>
        <select
          data-testid="payment-reject-code"
          className={FIELD}
          value={code}
          onChange={(e) => setCode(e.target.value as DecisionCode)}
        >
          {DECISION_CODES.map((c) => (
            <option key={c} value={c}>
              {t(`admin.payments.reject.codes.${c}`)}
            </option>
          ))}
        </select>
      </label>
      <label className="block space-y-1 text-sm">
        <span className="font-medium">{t("admin.payments.reject.note")}</span>
        <textarea
          data-testid="payment-reject-note"
          className={FIELD}
          rows={3}
          maxLength={NOTE_MAX}
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        <span className="text-xs text-muted-foreground">{t("admin.payments.reject.noteHelp")}</span>
      </label>
      <div className="flex flex-wrap gap-2">
        <button
          type="submit"
          className={PRIMARY}
          disabled={!ok || busy}
          data-testid="payment-reject-confirm"
        >
          {busy ? (
            <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
          ) : (
            <X aria-hidden className="h-4 w-4" />
          )}
          {t("admin.payments.reject.confirm")}
        </button>
        <button type="button" className={BUTTON} onClick={onClose} disabled={busy}>
          {t("admin.payments.back")}
        </button>
      </div>
    </form>
  );
}

function Annul({
  busy,
  onDecide,
  onClose,
}: {
  busy: boolean;
  onDecide: (reason: string) => void;
  onClose: () => void;
}) {
  const [reason, setReason] = useState("");
  const ok = noteOk(reason);
  return (
    <form
      className="space-y-3 rounded-md border border-negative/40 p-3"
      data-testid="payment-annul"
      onSubmit={(e) => {
        e.preventDefault();
        if (ok && !busy) onDecide(reason.trim());
      }}
    >
      <p className="text-sm">{t("admin.payments.annul.warning")}</p>
      <label className="block space-y-1 text-sm">
        <span className="font-medium">{t("admin.payments.annul.reason")}</span>
        <textarea
          data-testid="payment-annul-reason"
          className={FIELD}
          rows={3}
          maxLength={NOTE_MAX}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </label>
      <div className="flex flex-wrap gap-2">
        <button
          type="submit"
          className={PRIMARY}
          disabled={!ok || busy}
          data-testid="payment-annul-confirm"
        >
          {busy ? (
            <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
          ) : (
            <Undo2 aria-hidden className="h-4 w-4" />
          )}
          {t("admin.payments.annul.confirm")}
        </button>
        <button type="button" className={BUTTON} onClick={onClose} disabled={busy}>
          {t("admin.payments.back")}
        </button>
      </div>
    </form>
  );
}

function Row({ r }: { r: AdminPaymentRequest }) {
  const qc = useQueryClient();
  const [panel, setPanel] = useState<Panel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const flags = flagsOf(r);
  // a double click reaches the handler twice before the screen repaints: this lock closes that gap at once
  const locked = useRef(false);
  const once =
    <A,>(send: (arg: A) => void) =>
    (arg: A) => {
      if (locked.current) return;
      locked.current = true;
      send(arg);
    };
  const done = () => {
    setPanel(null);
    setError(null);
    void qc.invalidateQueries({ queryKey: KEY });
  };
  const failed = (e: unknown) => {
    setError(errorMessage(e));
    void qc.invalidateQueries({ queryKey: KEY });
  };
  const approve = useMutation({
    onSettled: () => {
      locked.current = false;
    },
    mutationFn: (body: ReturnType<typeof approveBody>) => v1.approvePaymentRequest(r.id, body),
    onSuccess: done,
    onError: failed,
  });
  const reject = useMutation({
    onSettled: () => {
      locked.current = false;
    },
    mutationFn: (v: { code: DecisionCode; note: string }) => v1.rejectPaymentRequest(r.id, v),
    onSuccess: done,
    onError: failed,
  });
  const annul = useMutation({
    onSettled: () => {
      locked.current = false;
    },
    mutationFn: (reason: string) => v1.annulPaymentRequest(r.id, reason),
    onSuccess: done,
    onError: failed,
  });
  const busy = approve.isPending || reject.isPending || annul.isPending;
  const open = r.status === "submitted";
  const canAnnul = r.status === "approved" && !r.annulled;
  const state = r.annulled ? "annulled" : r.status;
  return (
    <Card className="space-y-3 p-4" data-testid={`payment-request-${r.id}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <Link
            to="/admin/customers/$userId"
            params={{ userId: String(r.user_id) }}
            className="break-words font-display text-base font-semibold hover:underline"
          >
            {who(r)}
          </Link>
          <p className="break-all text-xs text-muted-foreground">{r.email}</p>
          {r.phone ? (
            <p className="break-all text-xs text-muted-foreground" data-testid="payment-phone">
              {r.phone}
            </p>
          ) : null}
        </div>
        <span
          data-testid="payment-status"
          data-state={state}
          className={cn(
            "rounded-full border px-2 py-0.5 text-xs font-medium",
            open ? "border-gold/50 text-gold" : "border-border text-muted-foreground",
          )}
        >
          {t(`admin.payments.status.${state}`)}
        </span>
      </div>
      <FlagList flags={flags} />
      <dl className="grid grid-cols-2 gap-3">
        <Fact
          label={t("admin.payments.fact.declared")}
          value={money(r.declared_amount, r.currency)}
        />
        <Fact
          label={t("admin.payments.fact.expected")}
          value={money(r.expected_amount, r.currency)}
        />
        <Fact
          label={t("admin.payments.fact.paidOn")}
          value={formatDateYear(`${r.declared_paid_on}T12:00:00-05:00`)}
        />
        <Fact
          label={t("admin.payments.fact.method")}
          value={t(`profile.membership.pay.methods.${r.method}`)}
        />
        <Fact
          label={t("admin.payments.fact.reference")}
          value={r.reference_last4 ? `…${r.reference_last4}` : t("admin.payments.fact.none")}
        />
        <Fact
          label={t("admin.payments.fact.payer")}
          value={r.payer_name ?? t("admin.payments.fact.none")}
        />
        <Fact label={t("admin.payments.fact.sent")} value={formatDateTime(r.created_at)} />
        <Fact label={t("admin.payments.fact.due")} value={dueText(r)} />
        {r.discount_percent ? (
          <Fact
            label={t("admin.payments.fact.discount")}
            value={t("admin.payments.fact.discountValue", {
              percent: r.discount_percent,
              coupon: r.coupon_code ?? "",
            })}
          />
        ) : null}
        <Fact label={t("admin.payments.fact.terms")} value={r.terms_version} />
      </dl>
      {r.note ? (
        <p className="rounded-md bg-elevated px-3 py-2 text-sm" data-testid="payment-note">
          {r.note}
        </p>
      ) : null}
      {!open && r.decided_at ? (
        <p className="text-xs text-muted-foreground" data-testid="payment-decision">
          {t("admin.payments.decided", {
            when: formatDateTime(r.decided_at),
            reason: r.decision_code ? t(`admin.payments.reject.codes.${r.decision_code}`) : "",
            note: r.decision_note ?? "",
          })}
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-negative" data-testid="payment-error">
          {error}
        </p>
      ) : null}
      {panel === "approve" ? (
        <Approve
          r={r}
          flags={flags}
          busy={busy}
          onDecide={once((b: ReturnType<typeof approveBody>) => approve.mutate(b))}
          onClose={() => setPanel(null)}
        />
      ) : null}
      {panel === "reject" ? (
        <Reject
          busy={busy}
          onDecide={once((v: { code: DecisionCode; note: string }) => reject.mutate(v))}
          onClose={() => setPanel(null)}
        />
      ) : null}
      {panel === "annul" ? (
        <Annul
          busy={busy}
          onDecide={once((reason: string) => annul.mutate(reason))}
          onClose={() => setPanel(null)}
        />
      ) : null}
      {panel === null && (open || canAnnul) ? (
        <div className="flex flex-wrap gap-2">
          {open ? (
            <>
              <button
                type="button"
                className={PRIMARY}
                onClick={() => setPanel("approve")}
                data-testid="payment-approve-open"
              >
                <Check aria-hidden className="h-4 w-4" />
                {t("admin.payments.approve.open")}
              </button>
              <button
                type="button"
                className={BUTTON}
                onClick={() => setPanel("reject")}
                data-testid="payment-reject-open"
              >
                <X aria-hidden className="h-4 w-4" />
                {t("admin.payments.reject.open")}
              </button>
            </>
          ) : null}
          {canAnnul ? (
            <button
              type="button"
              className={BUTTON}
              onClick={() => setPanel("annul")}
              data-testid="payment-annul-open"
            >
              <Undo2 aria-hidden className="h-4 w-4" />
              {t("admin.payments.annul.open")}
            </button>
          ) : null}
        </div>
      ) : null}
    </Card>
  );
}

export function PaymentQueuePage() {
  const [scope, setScope] = useState<Scope>("submitted");
  const q = useQuery({
    queryKey: [...KEY, scope],
    queryFn: () => v1.adminPaymentRequests(scope),
    staleTime: 0,
    refetchInterval: 60_000,
  });
  return (
    <div className="space-y-4" data-testid="payment-queue">
      <PageHeader
        title={t("admin.payments.title")}
        description={t("admin.payments.description")}
        actions={<Banknote aria-hidden className="h-5 w-5 text-gold" />}
      />
      <div role="tablist" className="flex gap-2">
        {(["submitted", "all"] as const).map((s) => (
          <button
            key={s}
            role="tab"
            type="button"
            aria-selected={scope === s}
            data-testid={`payment-scope-${s}`}
            onClick={() => setScope(s)}
            className={cn(BUTTON, scope === s && "border-primary bg-elevated")}
          >
            {s === "submitted"
              ? t("admin.payments.scope.waiting", { count: q.data?.waiting ?? 0 })
              : t("admin.payments.scope.all")}
          </button>
        ))}
      </div>
      {q.isPending ? <SkeletonCards count={2} /> : null}
      {q.isError ? <ErrorState error={q.error} onRetry={() => void q.refetch()} /> : null}
      {q.data && !q.data.requests.length ? (
        <EmptyState
          title={t(
            scope === "submitted" ? "admin.payments.emptyWaiting" : "admin.payments.emptyAll",
          )}
        />
      ) : null}
      {q.data?.requests.map((r) => (
        <Row key={r.id} r={r} />
      ))}
    </div>
  );
}
