import type { DailyItem, PriceNow } from "@/lib/api/v1/types_records";

/**
 * Which price a pick of the day shows in big (plan AP-K05, decision D4): the best price available now, with its hour; the
 * one the pick was published at goes small beside it. Settlement and the history keep the price of publication - this only
 * decides what the card draws while the match is still to be played.
 *
 * An old price (stale) never passes as the current one: the card keeps the published price in big and says the price now is
 * old. «Ya no hay valor» is arithmetic on what the card already holds - PrediGol's probability times the price now - and is
 * said only when that product does not exceed 1, that is, when the expected value at this price is not positive; the server's
 * stricter gates still decide what is published.
 */
export interface PickPrice {
  /** The price in big. */
  shown: string;
  /** Whether `shown` is the price now (the card then also says the one of publication). */
  current: boolean;
  /** The price the pick was published at. */
  published: string;
  /** Price now minus price published, only when `current`; null otherwise. */
  delta: number | null;
  /** At this price the expected value is not positive. Only when `current`. */
  noValue: boolean;
  /** The price now, when it exists (also an old one: the card says it is old). */
  now: PriceNow | null;
}

export function pickPrice(item: Pick<DailyItem, "odds" | "p_model" | "price_now">): PickPrice {
  const now = item.price_now ?? null;
  const nowOdds = now ? Number(now.odds) : NaN;
  const published = Number(item.odds);
  const usable = now !== null && now.freshness !== "stale" && Number.isFinite(nowOdds);
  if (!usable) {
    return {
      shown: item.odds,
      current: false,
      published: item.odds,
      delta: null,
      noValue: false,
      now,
    };
  }
  const p = Number(item.p_model);
  return {
    shown: now.odds,
    current: true,
    published: item.odds,
    delta: Number.isFinite(published) ? Math.round((nowOdds - published) * 100) / 100 : null,
    noValue: Number.isFinite(p) && p * nowOdds <= 1,
    now,
  };
}
