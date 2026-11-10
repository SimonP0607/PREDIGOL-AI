/** The reader's «ya pagué» (UX-091): what the form sends and what the page says; pure, so it is tested without a browser. */
import type {
  MyPaymentRequests,
  PaymentRequestIn,
  PaymentRequestView,
  RequestMethod,
} from "@/lib/api/v1/types_payment_requests";
import { t } from "@/lib/i18n";
import { formatDateYear } from "@/lib/time";
import { priceText } from "./membership";

/** The days back a payment may be declared: the server refuses an older one. */
export const PAID_ON_WINDOW_DAYS = 30;

const BOGOTA = "America/Bogota";

/** A calendar day (YYYY-MM-DD) in Bogotá, the day the server counts in. */
export function bogotaDay(at: Date = new Date(), backDays = 0): string {
  const moved = new Date(at.getTime() - backDays * 86_400_000);
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: BOGOTA,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(moved);
}

export interface PayForm {
  amount: string;
  paidOn: string;
  method: RequestMethod;
  reference: string;
  payerName: string;
  note: string;
  acceptTerms: boolean;
}

export function emptyForm(data: MyPaymentRequests, at: Date = new Date()): PayForm {
  return {
    amount: data.price?.expected ?? "",
    paidOn: bogotaDay(at),
    method: data.pay?.has_qr && !data.pay.breb_key ? "nequi" : "transfer",
    reference: "",
    payerName: "",
    note: "",
    acceptTerms: false,
  };
}

/** The amount as typed ("150.000", "150000", "150000,50") to the decimal string the server reads, or null. */
export function amountOf(raw: string): string | null {
  const text = raw.trim().replace(/\s/g, "").replace(/\$/g, "");
  if (!text) return null;
  let normal = text;
  if (/^\d{1,3}(\.\d{3})+(,\d{1,2})?$/.test(text))
    normal = text.replace(/\./g, "").replace(",", ".");
  else if (/^\d{1,3}(,\d{3})+(\.\d{1,2})?$/.test(text)) normal = text.replace(/,/g, "");
  else if (/^\d+,\d{1,2}$/.test(text)) normal = text.replace(",", ".");
  if (!/^\d+(\.\d{1,2})?$/.test(normal)) return null;
  return Number(normal) > 0 ? normal : null;
}

export type FormProblem = "amount" | "paidOn" | "terms";

export function problems(form: PayForm, at: Date = new Date()): FormProblem[] {
  const found: FormProblem[] = [];
  if (amountOf(form.amount) === null) found.push("amount");
  if (
    !/^\d{4}-\d{2}-\d{2}$/.test(form.paidOn) ||
    form.paidOn > bogotaDay(at) ||
    form.paidOn < bogotaDay(at, PAID_ON_WINDOW_DAYS)
  )
    found.push("paidOn");
  if (!form.acceptTerms) found.push("terms");
  return found;
}

export function toBody(
  form: PayForm,
  termsVersion: string,
  at: Date = new Date(),
): PaymentRequestIn | null {
  const amount = amountOf(form.amount);
  if (amount === null || problems(form, at).length) return null;
  const clean = (s: string) => s.trim().replace(/\s+/g, " ");
  return {
    amount,
    paid_on: form.paidOn,
    method: form.method,
    reference: clean(form.reference) || null,
    payer_name: clean(form.payerName) || null,
    note: clean(form.note) || null,
    accept_terms: true,
    terms_version: termsVersion,
  };
}

/** An amount of pesos as the reader reads it: «150.000 COP». */
export function moneyText(amount: string, currency: string): string {
  return priceText({ currency, amount });
}

/** The day the owner promises to have checked by, as the reader reads it. */
export function dueText(r: Pick<PaymentRequestView, "due_on">): string {
  return formatDateYear(`${r.due_on}T12:00:00-05:00`);
}

/** What the reader is told about their latest notice when nothing waits: refused, or an approval that was annulled. */
export function lastOutcome(
  requests: readonly PaymentRequestView[],
): "rejected" | "annulled" | null {
  const last = requests[0];
  if (!last) return null;
  if (last.status === "rejected") return "rejected";
  if (last.status === "approved" && last.annulled) return "annulled";
  return null;
}

/** The states in which asking for access or renewing makes sense: no cover, or the cover ending or ended. */
export function mayPay(state: string): boolean {
  return ["none", "expiring", "grace", "expired"].includes(state);
}

export function reasonText(code: string | null): string {
  return code ? t(`profile.membership.pay.reason.${code}`) : "";
}
