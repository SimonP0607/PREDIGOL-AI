/**
 * The membership in the reader's words (plan UX, A8; section 22): pure, so it is tested without a page. The state
 * comes from the server, computed from dates; this only says it - with the date in the reader's time zone - and
 * decides which pages a limited account still opens.
 */
import type { DiscountOffer, MembershipSummary, PlanPrice } from "@/lib/api/v1/types_membership";
import { t } from "@/lib/i18n";
import { localDecimalText, localInt } from "@/lib/i18n/format";
import { formatDateLong } from "@/lib/time";

/** What a limited account still opens: its profile (with its membership and its data), its saved picks, the help and
 * the legal texts. The server refuses the rest of the product (403 membership_expired / membership_suspended / membership_required). */
export function isLimitedPath(path: string): boolean {
  const p = path.replace(/\/+$/, "") || "/";
  return (
    p === "/profile" ||
    p === "/my-picks" ||
    p === "/help" ||
    p.startsWith("/help/") ||
    p.startsWith("/legal/")
  );
}

function day(iso: string | null): string {
  return iso ? formatDateLong(iso) : "";
}

/** The card's sentence for the state now. */
export function membershipLine(m: MembershipSummary): string {
  switch (m.state) {
    case "trial":
      return t("profile.membership.line.trial", { date: day(m.ends_at) });
    case "active":
      return t("profile.membership.line.active", { date: day(m.ends_at) });
    case "renewed":
      return t("profile.membership.line.renewed", { date: day(m.ends_at) });
    case "expiring":
      return m.kind === "trial"
        ? t("profile.membership.line.expiringTrial", { date: day(m.ends_at) })
        : t("profile.membership.line.expiring", { date: day(m.ends_at) });
    case "grace":
      return t("profile.membership.line.grace", { date: day(m.grace_until) });
    case "expired":
      return t("profile.membership.line.expired");
    case "suspended":
      return t("profile.membership.line.suspended");
    case "none":
      return t("profile.membership.line.none");
  }
}

/**
 * The quiet notice at the top of every page, or null: from 7 days before the end (3 in a trial), the day before, the
 * grace (fixed), and - on the pages a limited account still opens - the limit itself. No countdown, no offer, no
 * alarm colours: a notice of the service the reader has.
 */
export function bannerText(m: MembershipSummary): string | null {
  switch (m.state) {
    case "expiring": {
      const eve = (m.days_left ?? 99) <= 1;
      if (m.kind === "trial") {
        return eve
          ? t("profile.membership.banner.eveTrial")
          : t("profile.membership.banner.expiringTrial", { date: day(m.ends_at) });
      }
      return eve
        ? t("profile.membership.banner.eve")
        : t("profile.membership.banner.expiring", { date: day(m.ends_at) });
    }
    case "grace":
      return t("profile.membership.banner.grace", { date: day(m.grace_until) });
    case "expired":
      return m.limited
        ? t("profile.membership.banner.expired")
        : t("profile.membership.line.expired");
    case "suspended":
      return t("profile.membership.banner.suspended");
    case "none":
      // A registered account has no trial: while the membership is enforced it waits for its first period.
      return m.limited ? t("profile.membership.banner.none") : null;
    default:
      return null;
  }
}

/** A WhatsApp chat with the business number and a first line already written. */
export function whatsappLink(digits: string, text: string): string {
  return `https://wa.me/${digits.replace(/\D/g, "")}?text=${encodeURIComponent(text)}`;
}

/** Days left are said while the cover runs. */
export function showsDaysLeft(m: MembershipSummary): boolean {
  return (
    m.days_left !== null &&
    ["trial", "active", "expiring", "renewed"].includes(m.state) &&
    m.ends_at !== null
  );
}

/** One price as the reader reads it: "150.000 COP" in Spanish, "150,000 COP" in English; cents only when there are. */
export function priceText(p: PlanPrice): string {
  const value = Number(p.amount);
  const number =
    Number.isFinite(value) && Number.isInteger(value)
      ? localInt(value)
      : localDecimalText(p.amount);
  return `${number} ${p.currency}`;
}

/** "150.000 COP o 50 USD al mes", or null while the owner has set no price - a price is never guessed. */
export function priceLine(prices: readonly PlanPrice[]): string | null {
  if (!prices.length) return null;
  return t("profile.membership.plan.price", {
    prices: prices.map(priceText).join(` ${t("profile.membership.plan.or")} `),
  });
}

/** Where a discount comes from, in words: "el cupón BIENVENIDA" or "la fidelidad" (UX-005). */
export function offerSource(offer: Pick<DiscountOffer, "kind" | "code">): string {
  return offer.kind === "coupon"
    ? t("profile.membership.discount.sourceCoupon", { code: offer.code ?? "" })
    : t("profile.membership.discount.sourceLoyalty");
}

/**
 * What ``months`` months come to at the monthly prices, in one currency, as the decimal string the payment form takes:
 * "300000", or "85.00" with cents. Null when the owner offers no price in that currency - an amount is never guessed.
 */
export function suggestedAmount(
  prices: readonly PlanPrice[],
  currency: string,
  months: number,
): string | null {
  const price = prices.find((p) => p.currency === currency.trim().toUpperCase());
  if (!price) return null;
  const total = Math.round(Number(price.amount) * months * 100) / 100;
  if (!Number.isFinite(total) || total <= 0) return null;
  return Number.isInteger(total) ? String(total) : total.toFixed(2);
}
