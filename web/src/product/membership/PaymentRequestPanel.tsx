/**
 * «Solicitar acceso» / «Ya pagué» (UX-091): how to pay (the owner's QR or key), the notice of a payment already made, and
 * the wait while the owner verifies it. There is no payment gateway: the reader pays outside PrediGol and tells us; only
 * the owner's approval opens the access. The owner's data are shown only while the server says the notices are open, and
 * nothing here invents a holder, a key or a price. «Pago en verificación» is the open notice, not a state of the membership.
 */
import { useState, type FormEvent } from "react";
import { Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Clock, Copy, Download, Loader2 } from "lucide-react";
import { v1 } from "@/lib/api/v1/client";
import type { MembershipState } from "@/lib/api/v1/types_membership";
import type { MyPaymentRequests, RequestMethod } from "@/lib/api/v1/types_payment_requests";
import { REQUEST_METHODS } from "@/lib/api/v1/types_payment_requests";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { errorMessage } from "@/product/shared/States";
import { WhatsappLink } from "@/product/support/WhatsappLink";
import {
  bogotaDay,
  dueText,
  emptyForm,
  lastOutcome,
  mayPay,
  moneyText,
  PAID_ON_WINDOW_DAYS,
  problems,
  reasonText,
  toBody,
  type FormProblem,
  type PayForm,
} from "./paymentRequest";
import { fieldVariants } from "@/components/ui/field";

const field = fieldVariants();
const button =
  "tap-y relative inline-flex min-h-11 items-center justify-center gap-2 rounded-md px-4 text-sm font-semibold disabled:opacity-50";
const secondary = `${button} border border-border-strong hover:bg-elevated`;
const primary = `${button} bg-primary text-primary-foreground hover:opacity-90`;
const QR_URL = "/api/v1/me/payment-request/qr";

function Contact({ whatsapp }: { whatsapp: string | null }) {
  if (!whatsapp) return null;
  return (
    <WhatsappLink
      digits={whatsapp}
      text={t("profile.membership.pay.whatsappText")}
      className={secondary}
      testId="pay-whatsapp"
    >
      {t("profile.membership.pay.whatsapp")}
    </WhatsappLink>
  );
}

function HowToPay({ data }: { data: MyPaymentRequests }) {
  const [copied, setCopied] = useState(false);
  const { pay, price } = data;
  if (!pay) return null;
  return (
    <section className="space-y-3 rounded-md border border-border p-3" data-testid="pay-how">
      <h4 className="text-sm font-semibold">{t("profile.membership.pay.howTitle")}</h4>
      {price ? (
        <p className="text-sm" data-testid="pay-price">
          {t("profile.membership.pay.amountToPay")}{" "}
          <span className="numeric font-semibold">{moneyText(price.expected, price.currency)}</span>
          {price.discount_percent ? (
            <span className="ml-2 text-xs text-positive">
              {t("profile.membership.pay.withDiscount", { percent: price.discount_percent })}
            </span>
          ) : null}
        </p>
      ) : null}
      <p className="text-xs text-muted-foreground">
        {t("profile.membership.pay.holder")}{" "}
        <span className="font-medium text-foreground" data-testid="pay-holder">
          {pay.holder}
        </span>
      </p>
      {pay.breb_key ? (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground">{t("profile.membership.pay.key")}</span>
          <code
            className="numeric rounded border border-border px-2 py-1 text-sm"
            data-testid="pay-key"
          >
            {pay.breb_key}
          </code>
          <button
            type="button"
            className={secondary}
            data-testid="pay-copy"
            onClick={() => {
              void navigator.clipboard?.writeText(pay.breb_key ?? "").then(() => setCopied(true));
            }}
          >
            {copied ? (
              <Check aria-hidden className="h-4 w-4" />
            ) : (
              <Copy aria-hidden className="h-4 w-4" />
            )}
            {copied ? t("profile.membership.pay.copied") : t("profile.membership.pay.copy")}
          </button>
        </div>
      ) : null}
      {pay.has_qr ? (
        <div className="space-y-2">
          <img
            src={QR_URL}
            alt={t("profile.membership.pay.qrAlt")}
            width={240}
            height={240}
            className="mx-auto h-auto w-60 max-w-full rounded-md border border-border bg-white p-2"
            data-testid="pay-qr"
          />
          <div className="flex justify-center">
            <a
              href={QR_URL}
              download="qr-nequi-predigol"
              className={secondary}
              data-testid="pay-qr-save"
            >
              <Download aria-hidden className="h-4 w-4" />
              {t("profile.membership.pay.saveQr")}
            </a>
          </div>
        </div>
      ) : null}
      <p className="text-xs text-muted-foreground">{t("profile.membership.pay.afterPaying")}</p>
    </section>
  );
}

const METHOD_LABEL: Record<RequestMethod, string> = {
  nequi: "profile.membership.pay.methods.nequi",
  transfer: "profile.membership.pay.methods.transfer",
  other: "profile.membership.pay.methods.other",
};

export function PayForm({
  data,
  busy,
  error,
  onSend,
}: {
  data: MyPaymentRequests;
  busy: boolean;
  error: string | null;
  onSend: (body: NonNullable<ReturnType<typeof toBody>>) => void;
}) {
  const [form, setForm] = useState<PayForm>(() => emptyForm(data));
  const [shown, setShown] = useState<FormProblem[]>([]);
  const set = <K extends keyof PayForm>(key: K, value: PayForm[K]) =>
    setForm((f) => ({ ...f, [key]: value }));
  function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    const found = problems(form);
    setShown(found);
    const body = toBody(form, data.terms.version);
    if (body) onSend(body);
  }
  const bad = (p: FormProblem) => shown.includes(p);
  return (
    <form onSubmit={submit} className="space-y-3" noValidate data-testid="pay-form">
      <h4 className="text-sm font-semibold">{t("profile.membership.pay.formTitle")}</h4>
      <div className="space-y-1">
        <label htmlFor="pay-amount" className="block text-xs font-medium">
          {t("profile.membership.pay.fieldAmount")}
        </label>
        <input
          id="pay-amount"
          inputMode="decimal"
          autoComplete="off"
          value={form.amount}
          onChange={(e) => set("amount", e.target.value)}
          aria-invalid={bad("amount")}
          className={cn(field, "numeric")}
          data-testid="pay-amount"
        />
        {bad("amount") ? (
          <p role="alert" className="text-xs text-negative">
            {t("profile.membership.pay.problem.amount")}
          </p>
        ) : null}
      </div>
      <div className="space-y-1">
        <label htmlFor="pay-date" className="block text-xs font-medium">
          {t("profile.membership.pay.fieldDate")}
        </label>
        <input
          id="pay-date"
          type="date"
          value={form.paidOn}
          min={bogotaDay(new Date(), PAID_ON_WINDOW_DAYS)}
          max={bogotaDay()}
          onChange={(e) => set("paidOn", e.target.value)}
          aria-invalid={bad("paidOn")}
          className={field}
          data-testid="pay-date"
        />
        {bad("paidOn") ? (
          <p role="alert" className="text-xs text-negative">
            {t("profile.membership.pay.problem.paidOn", { days: PAID_ON_WINDOW_DAYS })}
          </p>
        ) : null}
      </div>
      <fieldset className="space-y-1">
        <legend className="text-xs font-medium">{t("profile.membership.pay.fieldMethod")}</legend>
        <div className="grid gap-2 sm:grid-cols-3">
          {REQUEST_METHODS.map((m) => (
            <label
              key={m}
              className={cn(
                "tap-y relative flex min-h-11 cursor-pointer items-center gap-2 rounded-md border px-3 text-sm",
                form.method === m ? "border-primary bg-elevated" : "border-border",
              )}
            >
              <input
                type="radio"
                name="pay-method"
                value={m}
                checked={form.method === m}
                onChange={() => set("method", m)}
                data-testid={`pay-method-${m}`}
              />
              {t(METHOD_LABEL[m])}
            </label>
          ))}
        </div>
      </fieldset>
      <div className="space-y-1">
        <label htmlFor="pay-reference" className="block text-xs font-medium">
          {t("profile.membership.pay.fieldReference")}
        </label>
        <input
          id="pay-reference"
          maxLength={60}
          autoComplete="off"
          value={form.reference}
          onChange={(e) => set("reference", e.target.value)}
          className={field}
          data-testid="pay-reference"
        />
        <p className="text-caption text-subtle-foreground">
          {t("profile.membership.pay.referenceHelp")}
        </p>
      </div>
      <div className="space-y-1">
        <label htmlFor="pay-payer" className="block text-xs font-medium">
          {t("profile.membership.pay.fieldPayer")}
        </label>
        <input
          id="pay-payer"
          maxLength={100}
          autoComplete="off"
          value={form.payerName}
          onChange={(e) => set("payerName", e.target.value)}
          className={field}
          data-testid="pay-payer"
        />
      </div>
      <div className="space-y-1">
        <label htmlFor="pay-note" className="block text-xs font-medium">
          {t("profile.membership.pay.fieldNote")}
        </label>
        <input
          id="pay-note"
          maxLength={300}
          autoComplete="off"
          value={form.note}
          onChange={(e) => set("note", e.target.value)}
          className={field}
          data-testid="pay-note"
        />
      </div>
      <div className="space-y-1">
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            checked={form.acceptTerms}
            onChange={(e) => set("acceptTerms", e.target.checked)}
            aria-invalid={bad("terms")}
            className="mt-1 h-4 w-4"
            data-testid="pay-terms"
          />
          <span>
            {t("profile.membership.pay.acceptTerms")}{" "}
            <Link
              to="/legal/$doc"
              params={{ doc: "terms" }}
              className="underline"
              data-testid="pay-terms-link"
            >
              {t("profile.membership.pay.termsLink", { version: data.terms.version })}
            </Link>
          </span>
        </label>
        {bad("terms") ? (
          <p role="alert" className="text-xs text-negative">
            {t("profile.membership.pay.problem.terms")}
          </p>
        ) : null}
      </div>
      {error ? (
        <p role="alert" className="text-xs text-negative" data-testid="pay-error">
          {error}
        </p>
      ) : null}
      <button
        type="submit"
        disabled={busy}
        className={cn(primary, "w-full sm:w-auto")}
        data-testid="pay-submit"
      >
        {busy ? <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> : null}
        {t("profile.membership.pay.submit")}
      </button>
      <p className="text-caption text-subtle-foreground">{t("profile.membership.pay.noCharge")}</p>
    </form>
  );
}

function Waiting({
  data,
  busy,
  error,
  onCancel,
}: {
  data: MyPaymentRequests;
  busy: boolean;
  error: string | null;
  onCancel: (id: number) => void;
}) {
  const [asking, setAsking] = useState(false);
  const open = data.open;
  if (!open) return null;
  return (
    <section
      className="space-y-3 rounded-md border border-gold/45 bg-gold-soft p-3"
      data-testid="pay-waiting"
      role="status"
    >
      <h4 className="flex items-center gap-2 text-sm font-semibold text-gold-strong">
        <Clock aria-hidden className="h-4 w-4" />
        {t("profile.membership.pay.waitingTitle")}
      </h4>
      <p className="text-sm">{t("profile.membership.pay.waitingBody", { date: dueText(open) })}</p>
      <dl className="grid gap-x-3 gap-y-1 text-xs sm:grid-cols-2">
        <div>
          <dt className="text-muted-foreground">{t("profile.membership.pay.sentAmount")}</dt>
          <dd className="numeric font-medium">{moneyText(open.declared_amount, open.currency)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("profile.membership.pay.sentDate")}</dt>
          <dd className="numeric font-medium">{open.declared_paid_on}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("profile.membership.pay.sentMethod")}</dt>
          <dd className="font-medium">{t(METHOD_LABEL[open.method])}</dd>
        </div>
        {open.reference_last4 ? (
          <div>
            <dt className="text-muted-foreground">{t("profile.membership.pay.sentReference")}</dt>
            <dd className="numeric font-medium">…{open.reference_last4}</dd>
          </div>
        ) : null}
      </dl>
      <p className="text-xs text-muted-foreground">{t("profile.membership.pay.waitingNoRepay")}</p>
      {error ? (
        <p role="alert" className="text-xs text-negative">
          {error}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        {asking ? (
          <>
            <button
              type="button"
              className={secondary}
              disabled={busy}
              onClick={() => onCancel(open.id)}
              data-testid="pay-cancel-confirm"
            >
              {busy ? <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> : null}
              {t("profile.membership.pay.cancelConfirm")}
            </button>
            <button type="button" className={secondary} onClick={() => setAsking(false)}>
              {t("profile.membership.pay.cancelKeep")}
            </button>
          </>
        ) : (
          <button
            type="button"
            className={secondary}
            onClick={() => setAsking(true)}
            data-testid="pay-cancel"
          >
            {t("profile.membership.pay.cancel")}
          </button>
        )}
        <Contact whatsapp={data.whatsapp} />
      </div>
    </section>
  );
}

function Outcome({ data }: { data: MyPaymentRequests }) {
  const kind = lastOutcome(data.requests);
  const last = data.requests[0];
  if (!kind || !last) return null;
  return (
    <p
      role="status"
      className="rounded-md border border-negative/40 p-3 text-sm"
      data-testid="pay-outcome"
      data-kind={kind}
    >
      {kind === "rejected"
        ? t("profile.membership.pay.rejected", { reason: reasonText(last.decision_code) })
        : t("profile.membership.pay.annulled")}
    </p>
  );
}

/** What the page shows, given the server's answer: pure of hooks except the form's own state (tested with static markup). */
export function PaymentRequestBody({
  data,
  state,
  busy = false,
  error = null,
  onSend = () => undefined,
  onCancel = () => undefined,
}: {
  data: MyPaymentRequests;
  state: MembershipState;
  busy?: boolean;
  error?: string | null;
  onSend?: (body: NonNullable<ReturnType<typeof toBody>>) => void;
  onCancel?: (id: number) => void;
}) {
  if (data.open) return <Waiting data={data} busy={busy} error={error} onCancel={onCancel} />;
  if (!mayPay(state)) return null;
  if (!data.available) {
    return (
      <section className="space-y-2 rounded-md border border-border p-3" data-testid="pay-closed">
        <h4 className="text-sm font-semibold">{t("profile.membership.pay.closedTitle")}</h4>
        <p className="text-xs text-muted-foreground">{t("profile.membership.pay.closedBody")}</p>
        <Contact whatsapp={data.whatsapp} />
      </section>
    );
  }
  return (
    <div className="space-y-3" data-testid="pay-open">
      <Outcome data={data} />
      <HowToPay data={data} />
      <PayForm data={data} busy={busy} error={error} onSend={onSend} />
    </div>
  );
}

export const PAYMENT_REQUEST_KEY = ["v1", "me", "payment-request"] as const;

export function PaymentRequestPanel({ state }: { state: MembershipState }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: PAYMENT_REQUEST_KEY, queryFn: v1.myPaymentRequests });
  const [error, setError] = useState<string | null>(null);
  const done = () => {
    setError(null);
    void qc.invalidateQueries({ queryKey: PAYMENT_REQUEST_KEY });
    void qc.invalidateQueries({ queryKey: ["v1", "me", "membership"] });
  };
  const send = useMutation({
    mutationFn: v1.sendPaymentRequest,
    onSuccess: done,
    onError: (e) => {
      setError(errorMessage(e));
      void qc.invalidateQueries({ queryKey: PAYMENT_REQUEST_KEY });
    },
  });
  const cancel = useMutation({
    mutationFn: v1.cancelPaymentRequest,
    onSuccess: done,
    onError: (e) => setError(errorMessage(e)),
  });
  if (!q.data) return null; // a failed read shows nothing here: the membership block says the rest
  return (
    <PaymentRequestBody
      data={q.data}
      state={state}
      busy={send.isPending || cancel.isPending}
      error={error}
      onSend={(body) => send.mutate(body)}
      onCancel={(id) => cancel.mutate(id)}
    />
  );
}
