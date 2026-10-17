/**
 * En vivo, narrowed and ordered (REVIEW PREDIGOL, point 11): a team search, country, league and gender
 * filters, and by default the matches PrediGol has picks on first - what we want to stand out. Pure.
 */
import type { LiveMatch } from "@/lib/api/v1/types_center";
import { genderOf, matchesTeam, type Gender } from "@/product/matches/facets";

export interface LiveFilters {
  team: string;
  country: string | null;
  competition: string | null;
  gender: Gender | null;
  /** Only the matches PrediGol has picks on. */
  picksOnly: boolean;
}

export const NO_FILTERS: LiveFilters = {
  team: "",
  country: null,
  competition: null,
  gender: null,
  picksOnly: false,
};

/** A league's key on the live board: its id when known, else its name and country. */
export function competitionKey(
  m: Pick<LiveMatch, "competition_id" | "competition" | "country">,
): string {
  return m.competition_id ? String(m.competition_id) : `${m.competition}|${m.country ?? ""}`;
}

export function countryOf(m: Pick<LiveMatch, "country">): string {
  const c = (m.country ?? "").trim();
  return c && c.toLowerCase() !== "world" ? c : "World";
}

export function inLiveFilters(
  m: LiveMatch,
  f: LiveFilters,
  picks: ReadonlyMap<number, number>,
): boolean {
  return (
    (!f.picksOnly || (picks.get(m.fixture_id) ?? 0) > 0) &&
    (f.country === null || countryOf(m) === f.country) &&
    (f.competition === null || competitionKey(m) === f.competition) &&
    (f.gender === null || genderOf({ name: m.competition }) === f.gender) &&
    matchesTeam(m, f.team)
  );
}

/** The matches with PrediGol picks first, each group in the board's own order (richest first). */
export function picksFirst(
  matches: readonly LiveMatch[],
  picks: ReadonlyMap<number, number>,
): LiveMatch[] {
  const withPicks = matches.filter((m) => (picks.get(m.fixture_id) ?? 0) > 0);
  const rest = matches.filter((m) => (picks.get(m.fixture_id) ?? 0) === 0);
  return [...withPicks, ...rest];
}
