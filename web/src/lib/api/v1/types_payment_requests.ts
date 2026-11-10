/** The manual payment request, «ya pagué» (UX-087; backend fbi/api/contracts/payment_requests.py). */
import type { Iso } from "./types";

export type RequestStatus = "submitted" | "approved" | "rejected" | "cancelled";
export type RequestMethod = "nequi" | "transfer" | "other";
export type DecisionCode =
  "amount_mismatch" | "not_received" | "duplicate" | "unreadable" | "other";
export type PaymentLock =
  "payment_not_configured" | "price_not_set" | "terms_draft" | "key_unavailable";

export const REQUEST_METHODS: readonly RequestMethod[] = ["nequi", "transfer", "other"];
export const DECISION_CODES: readonly DecisionCode[] = [
  "amount_mismatch",
  "not_received",
  "duplicate",
  "unreadable",
  "other",
];

/** What the owner published to be paid - sent only while the notices are open. */
export interface PayDetails {
  holder: string;
  /** The Bre-B key to copy; null when the owner only gave the QR. */
  breb_key: string | null;
  /** Whether the Nequi QR can be fetched (GET /me/payment-request/qr). */
  has_qr: boolean;
}

export interface RequestPrice {
  currency: string;
  amount: string;
  /** What the reader pays: the price with their discount taken off. */
  expected: string;
  discount_percent: number | null;
}

export interface RequestTerms {
  version: string;
  sha256: string;
  draft: boolean;
}

export interface PaymentRequestView {
  id: number;
  status: RequestStatus;
  expected_amount: string;
  currency: string;
  discount_percent: number | null;
  declared_amount: string;
  declared_paid_on: string;
  method: RequestMethod;
  reference_last4: string | null;
  payer_name: string | null;
  note: string | null;
  terms_version: string;
  accepted_at: Iso;
  created_at: Iso;
  decided_at: Iso | null;
  decision_code: DecisionCode | null;
  decision_note: string | null;
  /** The business day by whose end the owner verifies (Colombia). */
  due_on: string;
  due_at: Iso;
  /** An approved notice whose period the owner annulled later. */
  annulled: boolean;
}

export interface MyPaymentRequests {
  /** False while the owner's details, the price or the final terms of purchase are missing (``locks``). */
  available: boolean;
  locks: PaymentLock[];
  pay: PayDetails | null;
  price: RequestPrice | null;
  terms: RequestTerms;
  whatsapp: string | null;
  /** The notice waiting to be verified, if any: «pago en verificación». */
  open: PaymentRequestView | null;
  requests: PaymentRequestView[];
}

export interface PaymentRequestIn {
  amount: string;
  paid_on: string;
  method: RequestMethod;
  reference?: string | null;
  payer_name?: string | null;
  note?: string | null;
  accept_terms: boolean;
  terms_version: string;
}

export interface AdminPaymentRequest extends PaymentRequestView {
  user_id: number;
  email: string;
  display_name: string;
  first_name: string | null;
  last_name: string | null;
  coupon_code: string | null;
  /** Other notices carrying the same reference. */
  same_reference: number;
  amount_matches: boolean;
  overdue: boolean;
}

export interface AdminPaymentRequests {
  waiting: number;
  requests: AdminPaymentRequest[];
}

export interface ApproveIn {
  received_amount?: string | null;
  months?: number;
}

export interface RejectIn {
  code: DecisionCode;
  note: string;
}
