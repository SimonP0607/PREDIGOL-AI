/**
 * How the Matches and En vivo pages narrow a day (REVIEW PREDIGOL, points 3 and 11): by country, by category
 * (league, cup, continental, national teams - and women's or youth football, told by the competition's name),
 * by gender, by a team's name (En vivo) or by a team or a competition (Partidos). Pure: no React here.
 */
import type { CompetitionRef, MatchSummary } from "@/lib/api/v1/types";
import { countryLabel } from "./country";

export type Category = "league" | "cup" | "continental" | "international" | "women" | "youth";
export const CATEGORIES: readonly Category[] = [
  "league",
  "cup",
  "continental",
  "international",
  "women",
  "youth",
];
export type Gender = "men" | "women";

const WOMEN =
  /\b(women|womens|woman|femenin[oa]|feminin[oa]?|féminine|frauen|damallsvenskan|wsl|nwsl|liga f|w-league|kvinner|vrouwen)\b|\(w\)/i;
const YOUTH =
  /\b(u-?1[5-9]|u-?2[0-3]|sub-?1[5-9]|sub-?2[0-3]|youth|juvenil|primavera|reserves?|junior|jugend)\b/i;

export function genderOf(c: Pick<CompetitionRef, "name">): Gender {
  return WOMEN.test(c.name) ? "women" : "men";
}

/** Every category a competition is in: its type, plus women's or youth football when its name says so. */
export function categoriesOf(c: Pick<CompetitionRef, "name" | "competition_type">): Category[] {
  const out: Category[] = [];
  if (c.competition_type === "domestic_league") out.push("league");
  else if (c.competition_type === "domestic_cup") out.push("cup");
  else if (c.competition_type === "continental") out.push("continental");
  else if (c.competition_type === "international") out.push("international");
  if (genderOf(c) === "women") out.push("women");
  if (YOUTH.test(c.name)) out.push("youth");
  return out;
}

/** "World" competitions (friendlies, Nations League...) have no country: they are filed as international. */
export const WORLD = "world";

export function countryKey(c: Pick<CompetitionRef, "country" | "country_code">): string {
  const name = (c.country ?? "").trim();
  if (!name || name.toLowerCase() === "world") return WORLD;
  return (c.country_code ?? "").trim().toUpperCase() || name.toLowerCase();
}

export interface CountryOption {
  key: string;
  label: string;
  count: number;
}

/** The countries of a day's matches, by name in the reader's language; international last. */
export function countryOptions(
  matches: readonly Pick<MatchSummary, "competition">[],
  locale: string,
  worldLabel: string,
): CountryOption[] {
  const byKey = new Map<string, CountryOption>();
  for (const { competition: c } of matches) {
    const key = countryKey(c);
    const known = byKey.get(key);
    if (known) known.count += 1;
    else
      byKey.set(key, {
        key,
        label:
          key === WORLD
            ? worldLabel
            : (countryLabel(c.country, c.country_code) ?? c.country ?? key),
        count: 1,
      });
  }
  return [...byKey.values()].sort(
    (a, b) =>
      Number(a.key === WORLD) - Number(b.key === WORLD) || a.label.localeCompare(b.label, locale),
  );
}

function fold(s: string): string {
  return s
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase();
}

/** A team's name, any of the two, every word: "real ma" finds Real Madrid; accents do not matter. */
export function matchesTeam(
  m: { home: { name: string }; away: { name: string } },
  query: string,
): boolean {
  const q = fold(query.trim());
  if (!q) return true;
  const hay = fold(`${m.home.name} ${m.away.name}`);
  return q.split(/\s+/).every((w) => hay.includes(w));
}

/**
 * The one search box of Partidos (plan Partidos, P6): a team, or a competition by its name or its country - in the
 * reader's language or as stored. Every word must be found somewhere in them: "real ma" finds Real Madrid, "laliga"
 * LaLiga, "españa" every Spanish competition, "liga barcelona" Barcelona's league matches.
 */
export function matchesTeamOrCompetition(
  m: Pick<MatchSummary, "competition" | "home" | "away">,
  query: string,
): boolean {
  const q = fold(query.trim());
  if (!q) return true;
  const c = m.competition;
  const hay = fold(
    [
      m.home.name,
      m.away.name,
      c.name,
      c.country ?? "",
      countryLabel(c.country, c.country_code) ?? "",
    ].join(" "),
  );
  return q.split(/\s+/).every((w) => hay.includes(w));
}

/**
 * A facet saved or linked on another day may not play on this one (plan Partidos, P2): it is then ignored - the list
 * shows them all and the picker says «Todos» - instead of an empty list under a picker that looks unset.
 */
export function playing<T>(value: T | null, options: readonly { key: T }[]): T | null {
  return value !== null && options.some((o) => o.key === value) ? value : null;
}

export interface Facets {
  country: string | null;
  category: Category | null;
  /** A competition's id. */
  competition: number | null;
  /** A team or a competition (matchesTeamOrCompetition). */
  query: string;
}

export function inFacets(
  m: Pick<MatchSummary, "competition" | "home" | "away">,
  f: Facets,
): boolean {
  return (
    (f.country === null || countryKey(m.competition) === f.country) &&
    (f.category === null || categoriesOf(m.competition).includes(f.category)) &&
    (f.competition === null || m.competition.id === f.competition) &&
    matchesTeamOrCompetition(m, f.query)
  );
}
