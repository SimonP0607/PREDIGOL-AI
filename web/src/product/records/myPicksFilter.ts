/**
 * The filter of «Picks guardados» in Mis picks (plan UX, B5, section 30): by result, kind of bet, league, odds range, who
 * chose it (PrediGol or the reader) and the days of the match, and a search of the teams and the league. The server
 * applies it (GET /me/picks, /me/picks/summary and the CSV take the same parameters), so the list, its totals, its
 * breakdown and the file always count the same records. Pure: no React here.
 */
import type { MyPicksFilter, OddsBand, PickOrigin, PickResult } from "@/lib/api/v1/types_mypicks";

export const RESULTS: readonly PickResult[] = ["pending", "won", "lost", "push", "void"];
export const ORIGINS: readonly PickOrigin[] = ["predigol", "mine"];

export interface PicksFilterState {
  result: PickResult | null;
  market: string | null;
  competition: number | null;
  origin: PickOrigin | null;
  band: OddsBand | null;
  since: string | null;
  until: string | null;
  q: string;
}

export const NO_FILTER: PicksFilterState = {
  result: null,
  market: null,
  competition: null,
  origin: null,
  band: null,
  since: null,
  until: null,
  q: "",
};

/** How many parts are set: the «Filtros» button says it. A search counts once it has a letter. */
export function activeCount(f: PicksFilterState): number {
  return (
    (f.result !== null ? 1 : 0) +
    (f.market !== null ? 1 : 0) +
    (f.competition !== null ? 1 : 0) +
    (f.origin !== null ? 1 : 0) +
    (f.band !== null ? 1 : 0) +
    (f.since !== null ? 1 : 0) +
    (f.until !== null ? 1 : 0) +
    (f.q.trim() ? 1 : 0)
  );
}

/** What the API is asked: a day range whose ends cross is put in order; a search is trimmed (60 characters at most). */
export function toApiFilter(f: PicksFilterState): MyPicksFilter {
  let since = f.since;
  let until = f.until;
  if (since && until && since > until) [since, until] = [until, since];
  const q = f.q.trim().slice(0, 60);
  return {
    result: f.result,
    market: f.market,
    competition: f.competition,
    origin: f.origin,
    band: f.band,
    since,
    until,
    q: q || null,
  };
}

/** A YYYY-MM-DD from a date field, or null for an empty or impossible one. */
export function dayOrNull(value: string): string | null {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(`${value}T12:00:00Z`))
    ? value
    : null;
}
