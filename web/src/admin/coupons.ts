/** The coupons of the membership in the owner's console (UX-005): pure, so it is tested without a page. */
import type { AdminCoupon } from "@/lib/api/v1/types_membership";

export type CouponState = "active" | "disabled" | "expired" | "full";

/** What a coupon is at ``now``: off (the owner turned it off), past its last day, out of places, or live. The server says
 * ``active``; this says which of the other three, in that order of weight. */
export function couponState(c: AdminCoupon, now: number = Date.now()): CouponState {
  if (c.disabled_at) return "disabled";
  if (c.valid_until && Date.parse(c.valid_until) <= now) return "expired";
  if (c.max_redemptions !== null && c.redemptions >= c.max_redemptions) return "full";
  return "active";
}

/** The last moment a reader may save a coupon, from a date input ("2026-12-31"): the end of that day in the owner's time
 * zone, as an ISO instant; null for an empty field or one that is not a date. */
export function lastMomentOf(day: string): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day.trim());
  if (!m) return null;
  const date = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), 23, 59, 59);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}
