/** Membership (plan UX, A8): the reader's own and what the owner records (backend fbi/api/contracts/membership.py). */
import type { Iso } from "./types";

export type MembershipState =
  "trial" | "active" | "expiring" | "grace" | "expired" | "renewed" | "suspended" | "none";
export type PeriodKind = "trial" | "paid" | "courtesy";
export type PaymentMethod =
  "transfer" | "nequi" | "daviplata" | "cash" | "card" | "paypal" | "other";

export const PAYMENT_METHODS: readonly PaymentMethod[] = [
  "transfer",
  "nequi",
  "daviplata",
  "cash",
  "card",
  "paypal",
  "other",
];

/** The state now, computed from dates on the server. ``none``: no period yet (full access). */
export interface MembershipSummary {
  state: MembershipState;
  /** When the cover ends: the last period's end. */
  ends_at: Iso | null;
  /** The end plus the 3 days of grace with full access. */
  grace_until: Iso | null;
  kind: PeriodKind | null;
  /** Whole days until the end, rounded up; 0 once it has ended. */
  days_left: number | null;
  /** Whether the account reads only what a limited one reads, right now (false while the switch is off). */
  limited: boolean;
  will_not_renew: boolean;
}

export interface RenewContact {
  /** The WhatsApp Business number, digits with the country code (P7 of the plan); null until the owner gives it. */
  whatsapp: string | null;
  /** The address a reader's answer reaches. */
  email: string | null;
}

export interface MyPeriod {
  kind: PeriodKind;
  starts_at: Iso;
  ends_at: Iso;
  amount: string | null;
  currency: string | null;
  method: PaymentMethod | null;
}

/** The monthly price in one currency (COP or USD), as a decimal string. */
export interface PlanPrice {
  currency: string;
  amount: string;
}

/** The one plan as the reader's block shows it (UX-004): the trial and the monthly price per currency. */
export interface MembershipPlan {
  trial_days: number;
  /** Empty while the owner has not set a price (FBI_MEMBERSHIP_PRICE_COP / _USD). */
  prices: PlanPrice[];
}

export interface MyMembership {
  /** Null for the owner's accounts: no membership. */
  membership: MembershipSummary | null;
  enforced: boolean;
  periods: MyPeriod[];
  renew: RenewContact;
  plan: MembershipPlan;
}

export interface AdminPeriod {
  id: number;
  kind: PeriodKind;
  starts_at: Iso;
  ends_at: Iso;
  reason: string | null;
  created_at: Iso;
  amount: string | null;
  currency: string | null;
  method: PaymentMethod | null;
  reference: string | null;
  provider: string | null;
}

export interface AdminMembershipEvent {
  kind: string;
  at: Iso;
  reason: string | null;
  milestone: string | null;
  detail: Record<string, unknown>;
}

export interface AdminMembership {
  membership: MembershipSummary | null;
  suspended_reason: string | null;
  periods: AdminPeriod[];
  events: AdminMembershipEvent[];
  /** The currency the payment form proposes (FBI_MEMBERSHIP_CURRENCY). */
  currency: string;
  trial_days: number;
  /** FBI_MEMBERSHIP_ENFORCE: whether an ended membership limits anything. */
  enforced: boolean;
}

export interface PaymentIn {
  amount: string;
  currency: string;
  method: PaymentMethod;
  reference: string;
  months: number;
  /** One per payment the owner records: a repeated click records one. */
  idempotency_key: string;
}

export interface PaymentRecorded {
  created: boolean;
  membership: AdminMembership;
}
