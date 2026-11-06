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
  /** The discount that payment carried (UX-005); null when it had none. */
  discount_percent: number | null;
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

export type DiscountKind = "coupon" | "loyalty";

/** The discount a reader's next payment gets (UX-005): the larger of the loyalty one and the best coupon held. */
export interface DiscountOffer {
  kind: DiscountKind;
  /** 1 to 100. */
  percent: number;
  /** The coupon's code; null for the loyalty discount. */
  code: string | null;
  /** The monthly price with the discount taken off, per currency. */
  prices: PlanPrice[];
}

export interface HeldCoupon {
  code: string;
  percent: number;
}

/** The loyalty discount and where the reader stands in it; null while the owner has it off. */
export interface LoyaltyRule {
  percent: number;
  /** The months paid from which it applies (2 by default). */
  after_months: number;
  /** The months of the payments the owner recorded: a trial or a courtesy is not one. */
  paid_months: number;
  active: boolean;
}

export interface MyDiscounts {
  offer: DiscountOffer | null;
  /** The coupons held and not used yet, best first. */
  coupons: HeldCoupon[];
  loyalty: LoyaltyRule | null;
}

export interface MyMembership {
  /** Null for the owner's accounts: no membership. */
  membership: MembershipSummary | null;
  enforced: boolean;
  periods: MyPeriod[];
  renew: RenewContact;
  plan: MembershipPlan;
  discounts: MyDiscounts;
}

export interface CouponRedeemed {
  code: string;
  percent: number;
  discounts: MyDiscounts;
}

/** A coupon in the owner's console (UX-005). */
export interface AdminCoupon {
  id: number;
  code: string;
  percent: number;
  note: string | null;
  valid_until: Iso | null;
  max_redemptions: number | null;
  created_at: Iso;
  disabled_at: Iso | null;
  /** Readers holding it. */
  redemptions: number;
  /** Payments that carried it. */
  used: number;
  /** Can still be redeemed: not disabled, not past its last day, not at its ceiling. */
  active: boolean;
}

export interface AdminCoupons {
  coupons: AdminCoupon[];
}

export interface CouponCreateIn {
  code: string;
  percent: number;
  note?: string | null;
  /** The last moment a reader may redeem it. */
  valid_until?: Iso | null;
  max_redemptions?: number | null;
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
  discount_percent: number | null;
  discount_kind: DiscountKind | null;
  coupon_code: string | null;
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
  /** The monthly price per currency, for the payment form to propose. */
  prices: PlanPrice[];
  /** The discount this account's next payment gets, or null. */
  discount: DiscountOffer | null;
}

export interface PaymentIn {
  amount: string;
  currency: string;
  method: PaymentMethod;
  reference: string;
  months: number;
  /** One per payment the owner records: a repeated click records one. */
  idempotency_key: string;
  /** Record the discount the account's next payment is offered; a coupon is then used. */
  apply_discount?: boolean;
}

export interface PaymentRecorded {
  created: boolean;
  membership: AdminMembership;
}
