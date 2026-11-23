/**
 * AP-K04 (FBI_DAY_HIGHLIGHTS): «Lo más interesante de hoy», for the days without picks - two or three matches of the day to read,
 * never to bet. The criterion is written here and is never the price: what the match plays for in the table or the tie (the
 * matches GET /home already lists as «Qué se juega», in the server's order - which already puts the priority competitions
 * first), with the reader's own matches (their favourites) before the rest. It does not look at odds, edge or value, and it
 * speaks of none: the block shows the forecast PrediGol already labels in GET /today, with its seal.
 */
import type { HomeAtStake } from "@/lib/api/v1/types_product";
import type { TodayForecast, TodayMatch } from "@/lib/api/v1/types_today";

export const HIGHLIGHTS_MAX = 3;

export interface Highlight {
  stake: HomeAtStake;
  /** PrediGol's forecast of the match with its seal, as /today has it; null: none yet. */
  forecast: TodayForecast | null;
  /** The match is the reader's (a favourite): shown before the rest. */
  followed: boolean;
}

export function chooseHighlights(
  stakes: readonly HomeAtStake[],
  today: readonly TodayMatch[],
  max: number = HIGHLIGHTS_MAX,
): Highlight[] {
  const byFixture = new Map(today.map((m) => [m.fixture_id, m] as const));
  return stakes
    .map((stake, order) => {
      const m = byFixture.get(stake.fixture_id);
      return {
        stake,
        forecast: m?.forecast ?? null,
        followed: !!m?.followed && m.followed !== null && !m.suggested,
        order,
      };
    })
    .sort((a, b) => Number(b.followed) - Number(a.followed) || a.order - b.order)
    .slice(0, max)
    .map(({ stake, forecast, followed }) => ({ stake, forecast, followed }));
}
