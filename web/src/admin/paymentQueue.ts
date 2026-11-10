/** The owner's queue of payment notices (UX-092): the flags that make him look twice and the checks before a decision. */
import type { AdminPaymentRequest } from "@/lib/api/v1/types_payment_requests";

export type Flag = "amount" | "duplicate" | "overdue";

/** What deserves a second look before approving: a different amount, the same reference on other notices, a late check. */
export function flagsOf(
  r: Pick<AdminPaymentRequest, "amount_matches" | "same_reference" | "overdue" | "status">,
): Flag[] {
  if (r.status !== "submitted") return [];
  const found: Flag[] = [];
  if (!r.amount_matches) found.push("amount");
  if (r.same_reference > 0) found.push("duplicate");
  if (r.overdue) found.push("overdue");
  return found;
}

export const NOTE_MIN = 3;
export const NOTE_MAX = 200;

export function noteOk(text: string): boolean {
  const n = text.trim().length;
  return n >= NOTE_MIN && n <= NOTE_MAX;
}

/** A money amount the owner typed: digits with an optional decimal part, never zero. Thousands separators are refused so a
 * «1.500» is not read as one and a half. */
export function amountOk(text: string): boolean {
  const s = text.trim();
  return /^\d{1,9}(\.\d{1,2})?$/.test(s) && Number(s) > 0;
}

/** The body of an approval: the received amount only when it differs from the declared one, and the months paid. */
export function approveBody(
  declared: string,
  received: string,
  months: number,
): { received_amount?: string; months: number } {
  const typed = received.trim();
  const same = Number(typed) === Number(declared);
  return same ? { months } : { received_amount: typed, months };
}

/** A decision needs the owner's explicit tick when the money, the reference or the date look wrong. */
export function needsTick(flags: readonly Flag[]): boolean {
  return flags.includes("amount") || flags.includes("duplicate");
}

export function who(
  r: Pick<AdminPaymentRequest, "first_name" | "last_name" | "display_name" | "email">,
): string {
  const full = [r.first_name, r.last_name].filter(Boolean).join(" ").trim();
  return full || r.display_name || r.email;
}
