/**
 * One account's membership in the console (plan UX, A8; section 22): «Record payment and extend» first - amount,
 * currency, method, a reference in words, the months - in under a minute; then a courtesy, a trial for an account
 * that never had one, a suspension or its lifting and «will not renew», each with its reason; and the history of
 * periods, payments and notices. Every answer is the account's membership as the server computes it.
 */
import { useState, type FormEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarPlus, Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type { AdminMembership, PaymentMethod } from "@/lib/api/v1/types_membership";
import { PAYMENT_METHODS } from "@/lib/api/v1/types_membership";
import { t, translateOr } from "@/lib/i18n";
import { formatDateLong, formatDateTime, formatDateYear } from "@/lib/time";
import { cn } from "@/lib/utils";
import { errorMessage } from "@/product/shared/States";
import { membershipLine } from "@/product/membership/membership";

const field =
  "mt-1 h-10 w-full rounded-md border border-input bg-background px-3 text-base focus:border-primary focus:outline-none sm:text-sm";
const button =
  "tap-y relative inline-flex h-10 items-center gap-2 rounded-md px-4 text-sm font-semibold disabled:opacity-50";

function newKey(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID().replace(/-/g, "")
    : `${Date.now()}${Math.random().toString(36).slice(2)}`;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2 border-t border-border pt-3">
      <h3 className="text-sm font-semibold">{title}</h3>
      {children}
    </section>
  );
}

function PayForm({
  userId,
  view,
  onDone,
}: {
  userId: number;
  view: AdminMembership;
  onDone: (view: AdminMembership, notice: string) => void;
}) {
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState(view.currency);
  const [method, setMethod] = useState<PaymentMethod>("transfer");
  const [reference, setReference] = useState("");
  const [months, setMonths] = useState(1);
  const [key, setKey] = useState(newKey);
  const [error, setError] = useState<string | null>(null);
  const pay = useMutation({
    mutationFn: () =>
      v1.recordPayment(userId, {
        amount: amount.trim().replace(",", "."),
        currency: currency.trim().toUpperCase(),
        method,
        reference: reference.trim(),
        months,
        idempotency_key: key,
      }),
    onSuccess: (r) => {
      setError(null);
      setKey(newKey());
      setAmount("");
      setReference("");
      const m = r.membership.membership;
      const notice = r.created
        ? t("admin.membership.paid", {
            state: m ? t(`profile.membership.state.${m.state}`) : "",
            date: m?.ends_at ? formatDateLong(m.ends_at) : "",
          })
        : t("admin.membership.paidAgain");
      onDone(r.membership, notice);
    },
    onError: (e) => setError(errorMessage(e)),
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    if (!amount.trim() || pay.isPending) return;
    pay.mutate();
  }
  return (
    <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2" data-testid="membership-pay-form">
      <label className="block">
        <span className="text-xs text-muted-foreground">{t("admin.membership.amount")}</span>
        <input
          inputMode="decimal"
          autoComplete="off"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          className={cn(field, "numeric")}
          data-testid="pay-amount"
        />
      </label>
      <label className="block">
        <span className="text-xs text-muted-foreground">{t("admin.membership.currency")}</span>
        <input
          maxLength={3}
          value={currency}
          onChange={(e) => setCurrency(e.target.value.toUpperCase())}
          className={cn(field, "uppercase")}
          data-testid="pay-currency"
        />
      </label>
      <label className="block">
        <span className="text-xs text-muted-foreground">{t("admin.membership.method")}</span>
        <select
          value={method}
          onChange={(e) => setMethod(e.target.value as PaymentMethod)}
          className={field}
          data-testid="pay-method"
        >
          {PAYMENT_METHODS.map((m) => (
            <option key={m} value={m}>
              {t(`admin.membership.methods.${m}`)}
            </option>
          ))}
        </select>
      </label>
      <label className="block">
        <span className="text-xs text-muted-foreground">{t("admin.membership.months")}</span>
        <select
          value={months}
          onChange={(e) => setMonths(Number(e.target.value))}
          className={field}
          data-testid="pay-months"
        >
          {[1, 2, 3, 6, 12].map((n) => (
            <option key={n} value={n}>
              {t("admin.membership.monthsOption", { count: n })}
            </option>
          ))}
        </select>
      </label>
      <label className="block sm:col-span-2">
        <span className="text-xs text-muted-foreground">{t("admin.membership.reference")}</span>
        <input
          maxLength={120}
          autoComplete="off"
          value={reference}
          onChange={(e) => setReference(e.target.value)}
          className={field}
          data-testid="pay-reference"
        />
        <span className="mt-1 block text-caption text-subtle-foreground">
          {t("admin.membership.referenceHint")}
        </span>
      </label>
      <p className="text-caption text-subtle-foreground sm:col-span-2">
        {t("admin.membership.payNote")}
      </p>
      {error ? (
        <p role="alert" className="text-xs text-negative sm:col-span-2">
          {error}
        </p>
      ) : null}
      <div className="sm:col-span-2">
        <button
          type="submit"
          disabled={!amount.trim() || pay.isPending}
          className={cn(button, "bg-primary text-primary-foreground")}
          data-testid="pay-submit"
        >
          {pay.isPending ? (
            <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
          ) : (
            <CalendarPlus aria-hidden className="h-4 w-4" />
          )}
          {t("admin.membership.paySubmit")}
        </button>
      </div>
    </form>
  );
}

/** A small form with a reason (and maybe a number): courtesy, trial, suspension, lifting, «will not renew». */
function ReasonAction({
  testId,
  submit,
  days,
  reasonRequired = true,
  danger = false,
  label,
  run,
}: {
  testId: string;
  submit: string;
  days?: { label: string; min: number; max: number; initial: number } | undefined;
  reasonRequired?: boolean;
  danger?: boolean;
  label?: string | undefined;
  run: (input: { reason: string; days: number }) => Promise<AdminMembership>;
}) {
  const [reason, setReason] = useState("");
  const [count, setCount] = useState(days?.initial ?? 0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function go(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await run({ reason: reason.trim(), days: count });
      setReason("");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form
      onSubmit={(e) => void go(e)}
      className="flex flex-wrap items-end gap-2"
      data-testid={testId}
    >
      {days ? (
        <label className="block w-24">
          <span className="text-xs text-muted-foreground">{days.label}</span>
          <input
            type="number"
            min={days.min}
            max={days.max}
            value={count}
            onChange={(e) => setCount(Number(e.target.value))}
            className={cn(field, "numeric")}
            data-testid={`${testId}-days`}
          />
        </label>
      ) : null}
      {label !== undefined || reasonRequired ? (
        <label className="block min-w-48 flex-1">
          <span className="text-xs text-muted-foreground">
            {label ?? t("admin.membership.reason")}
          </span>
          <input
            maxLength={200}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className={field}
            data-testid={`${testId}-reason`}
          />
        </label>
      ) : null}
      <button
        type="submit"
        disabled={busy || (reasonRequired && reason.trim().length < 3)}
        className={cn(
          button,
          danger
            ? "border border-negative/50 text-negative hover:bg-negative-soft"
            : "border border-border-strong hover:bg-elevated",
        )}
        data-testid={`${testId}-submit`}
      >
        {busy ? <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> : null}
        {submit}
      </button>
      {error ? (
        <p role="alert" className="w-full text-xs text-negative">
          {error}
        </p>
      ) : null}
    </form>
  );
}

function History({ view }: { view: AdminMembership }) {
  return (
    <div className="space-y-3 text-xs" data-testid="membership-history">
      <ul className="space-y-1">
        {view.periods.map((p) => (
          <li key={p.id} className="flex flex-wrap gap-x-2">
            <span className="font-medium">{t(`profile.membership.period.${p.kind}`)}</span>
            <span className="numeric text-muted-foreground">
              {t("profile.membership.range", {
                from: formatDateYear(p.starts_at),
                to: formatDateYear(p.ends_at),
              })}
            </span>
            {p.amount ? (
              <span className="numeric text-muted-foreground">
                · {p.amount} {p.currency}
                {p.method ? ` · ${t(`admin.membership.methods.${p.method}`)}` : ""}
                {p.reference ? ` · ${p.reference}` : ""}
              </span>
            ) : null}
            {p.reason ? <span className="text-muted-foreground">· {p.reason}</span> : null}
          </li>
        ))}
      </ul>
      <ul className="space-y-1 border-t border-border/60 pt-2">
        {view.events.map((e, i) => (
          <li key={`${e.at}-${i}`} className="flex flex-wrap gap-x-2 text-muted-foreground">
            <span className="numeric">{formatDateTime(e.at)}</span>
            <span className="font-medium text-foreground">
              {translateOr(`admin.membership.events.${e.kind}`, e.kind)}
            </span>
            {e.milestone ? (
              <span>· {translateOr(`admin.membership.milestone.${e.milestone}`, e.milestone)}</span>
            ) : null}
            {e.reason ? <span>· {e.reason}</span> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function MembershipDialog({
  userId,
  email,
  open,
  onOpenChange,
}: {
  userId: number;
  email: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["v1", "admin", "membership", userId],
    queryFn: () => v1.adminMembership(userId),
    enabled: open,
  });
  const [notice, setNotice] = useState<string | null>(null);
  const changed = (view: AdminMembership, message?: string) => {
    qc.setQueryData(["v1", "admin", "membership", userId], view);
    void qc.invalidateQueries({ queryKey: live.users.queryKey });
    setNotice(message ?? null);
  };
  const view = q.data;
  const m = view?.membership ?? null;
  const hadTrial = view?.periods.some((p) => p.kind === "trial") ?? true;
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setNotice(null);
        onOpenChange(next);
      }}
    >
      <DialogContent
        className="max-h-[90vh] w-[calc(100%-2rem)] max-w-2xl overflow-y-auto rounded-xl border-border bg-card"
        data-testid={`membership-dialog-${userId}`}
      >
        <DialogHeader>
          <DialogTitle className="break-all font-display">
            {t("admin.membership.title", { email })}
          </DialogTitle>
          <DialogDescription data-testid="membership-dialog-line">
            {m ? membershipLine(m) : ""}
          </DialogDescription>
        </DialogHeader>
        {q.isPending ? (
          <Loader2 aria-hidden className="h-5 w-5 animate-spin text-muted-foreground" />
        ) : q.isError || !view ? (
          <p role="alert" className="text-sm text-negative">
            {errorMessage(q.error)}
          </p>
        ) : (
          <div className="space-y-4">
            {!view.enforced ? (
              <p className="text-xs text-muted-foreground">{t("admin.membership.notEnforced")}</p>
            ) : null}
            {view.suspended_reason ? (
              <p className="text-xs font-medium text-gold-strong">
                {t("admin.membership.suspendedBecause", { reason: view.suspended_reason })}
              </p>
            ) : null}
            {notice ? (
              <p
                role="status"
                className="rounded-md border border-positive/40 bg-positive/10 px-3 py-2 text-sm text-positive"
                data-testid="membership-notice"
              >
                {notice}
              </p>
            ) : null}
            <Section title={t("admin.membership.pay")}>
              <PayForm userId={userId} view={view} onDone={changed} />
            </Section>
            <Section title={t("admin.membership.courtesy")}>
              <ReasonAction
                testId="membership-courtesy"
                submit={t("admin.membership.courtesySubmit")}
                days={{ label: t("admin.membership.days"), min: 1, max: 90, initial: 7 }}
                run={async ({ reason, days }) => {
                  const next = await v1.grantCourtesy(userId, days, reason);
                  changed(next);
                  return next;
                }}
              />
            </Section>
            {!hadTrial ? (
              <Section title={t("admin.membership.trial")}>
                <ReasonAction
                  testId="membership-trial"
                  submit={t("admin.membership.trialSubmit")}
                  reasonRequired={false}
                  days={{
                    label: t("admin.membership.trialDays"),
                    min: 7,
                    max: 14,
                    initial: view.trial_days,
                  }}
                  run={async ({ days }) => {
                    const next = await v1.startTrial(userId, days);
                    changed(next);
                    return next;
                  }}
                />
              </Section>
            ) : null}
            <Section
              title={
                view.suspended_reason ? t("admin.membership.lift") : t("admin.membership.suspend")
              }
            >
              {view.suspended_reason ? (
                <ReasonAction
                  testId="membership-lift"
                  submit={t("admin.membership.liftSubmit")}
                  run={async ({ reason }) => {
                    const next = await v1.liftMembership(userId, reason);
                    changed(next);
                    return next;
                  }}
                />
              ) : (
                <ReasonAction
                  testId="membership-suspend"
                  submit={t("admin.membership.suspendSubmit")}
                  danger
                  run={async ({ reason }) => {
                    const next = await v1.suspendMembership(userId, reason);
                    changed(next);
                    return next;
                  }}
                />
              )}
            </Section>
            <Section title={t("admin.membership.willNotRenewSet")}>
              {m?.will_not_renew ? (
                <ReasonAction
                  testId="membership-will-renew"
                  submit={t("admin.membership.willRenewSubmit")}
                  reasonRequired={false}
                  run={async () => {
                    const next = await v1.renewalIntent(userId, true);
                    changed(next);
                    return next;
                  }}
                />
              ) : (
                <ReasonAction
                  testId="membership-will-not-renew"
                  submit={t("admin.membership.willNotRenewSubmit")}
                  run={async ({ reason }) => {
                    const next = await v1.renewalIntent(userId, false, reason);
                    changed(next);
                    return next;
                  }}
                />
              )}
            </Section>
            <Section title={t("admin.membership.history")}>
              <History view={view} />
            </Section>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
