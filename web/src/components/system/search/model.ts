/**
 * The readers' global search (plan maestro unificado, UX-153; maqueta 14), pure: what a hit is called, where it leads, how
 * the hits are grouped, and the recent searches kept on this device only (never sent anywhere).
 *
 * AP-B07: the readers' search reads `GET /search/v2` (C-10: teams, national teams, players, competitions and matches, with
 * accents, words and typos understood) and falls back to `GET /search` (the same three groups as before) if v2 does not
 * answer. Coaches, referees and stadiums are in the contract, but no page of the reader's opens one: they are not drawn.
 */
import type { SearchHit } from "@/lib/api/v1/types";
import type { SearchV2 } from "@/lib/api/v1/types_search";

export type SearchGroup = SearchHit["type"] | "national_team" | "player";

/** An entry of the answer, whichever search it came from. */
export interface Entry {
  type: SearchGroup;
  id: number;
  label: string;
  sublabel: string;
}

/** The maqueta's order: who first (clubs, then national teams, then players), then where they play, then the matches. */
export const GROUP_ORDER: readonly SearchGroup[] = [
  "team",
  "national_team",
  "player",
  "competition",
  "fixture",
];

/** At least two characters, as the API asks; at most 60. */
export const MIN_QUERY = 2;
export const MAX_QUERY = 60;

export function cleanQuery(raw: string): string {
  return raw.replace(/\s+/g, " ").trim().slice(0, MAX_QUERY);
}

export function groupHits<H extends { type: SearchGroup }>(
  hits: readonly H[],
): { group: SearchGroup; hits: H[] }[] {
  return GROUP_ORDER.map((group) => ({ group, hits: hits.filter((h) => h.type === group) })).filter(
    (g) => g.hits.length > 0,
  );
}

/** What of the profiles the reader has open: a club's, a national team's and a player's (FBI_PROFILES), a competition's page. */
export interface Opened {
  profiles: boolean;
  competitionPage?: boolean;
}

/**
 * The entries of a v2 answer, in the maqueta's order. A player is listed only with the profiles open (it has no other page to
 * lead to); coaches, referees, stadiums and news are not listed. A match carries its kick-off in the form the list always read.
 */
export function entriesOfV2(answer: SearchV2, opened: Opened): Entry[] {
  const g = answer.groups;
  const of = (type: SearchGroup, hits: SearchV2["groups"]["teams"]["items"]): Entry[] =>
    hits.map((h) => ({ type, id: h.id, label: h.label, sublabel: h.sublabel }));
  return [
    ...of("team", g.teams.items),
    ...of("national_team", g.national_teams.items),
    ...(opened.profiles ? of("player", g.players.items) : []),
    ...of("competition", g.competitions.items),
    ...g.fixtures.items.map((f): Entry => ({
      type: "fixture",
      id: f.id,
      label: f.label,
      sublabel: f.kickoff_at.replace("T", " ").slice(0, 16) + " UTC",
    })),
  ];
}

/** «¿Quisiste decir…?»: the close names of an answer with no hits, at most three. */
export function suggestionsOfV2(answer: SearchV2 | undefined): string[] {
  return (answer?.did_you_mean.items ?? []).map((s) => s.text).slice(0, 3);
}

/**
 * The kick-off of a match hit: the API writes it as "YYYY-MM-DD HH:MM UTC"; read as an instant, so the reader sees it in
 * their own zone and language. Anything else: null (the row then shows no time rather than a wrong one).
 */
export function hitKickoff(sublabel: string): string | null {
  const m = /^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}) UTC$/.exec(sublabel.trim());
  return m ? `${m[1]}T${m[2]}:00Z` : null;
}

/**
 * Where a hit leads a reader. With the profiles open (FBI_PROFILES, UX-154) a team opens its profile; without them, its
 * matches. A competition opens its day.
 */
export type HitLink =
  | { to: "/matches/$fixtureId"; params: { fixtureId: string } }
  | { to: "/teams/$teamId"; params: { teamId: string } }
  | { to: "/nations/$teamId"; params: { teamId: string } }
  | { to: "/players/$playerId"; params: { playerId: string } }
  | { to: "/competitions/$competitionId"; params: { competitionId: string } }
  | { to: "/matches"; search: { q?: string; competition?: number } };

export function hitLink(
  hit: Pick<Entry, "type" | "id" | "label">,
  profiles = false,
  competitionPage = false,
): HitLink {
  const id = String(hit.id);
  if (hit.type === "fixture") return { to: "/matches/$fixtureId", params: { fixtureId: id } };
  if (hit.type === "team" && profiles) return { to: "/teams/$teamId", params: { teamId: id } };
  if (hit.type === "national_team" && profiles)
    return { to: "/nations/$teamId", params: { teamId: id } };
  if (hit.type === "player" && profiles)
    return { to: "/players/$playerId", params: { playerId: id } };
  if (hit.type === "competition")
    return competitionPage
      ? { to: "/competitions/$competitionId", params: { competitionId: id } }
      : { to: "/matches", search: { competition: hit.id } };
  return { to: "/matches", search: { q: hit.label.slice(0, MAX_QUERY) } };
}

// ---- recent searches: on this device only -----------------------------------------------------------------------

export const RECENT_KEY = "predigol.search.recent";
export const MAX_RECENT = 6;

export type RecentHit = Entry;

type Store = Pick<Storage, "getItem" | "setItem" | "removeItem">;

function isRecent(v: unknown): v is RecentHit {
  if (!v || typeof v !== "object") return false;
  const r = v as Record<string, unknown>;
  return (
    typeof r["type"] === "string" &&
    (GROUP_ORDER as readonly string[]).includes(r["type"]) &&
    typeof r["id"] === "number" &&
    Number.isInteger(r["id"]) &&
    typeof r["label"] === "string" &&
    typeof r["sublabel"] === "string"
  );
}

/** What this device remembers; a missing, blocked or damaged store is an empty list, never an error. */
export function readRecent(store: Store | null | undefined): RecentHit[] {
  try {
    const raw = store?.getItem(RECENT_KEY);
    if (!raw) return [];
    const list: unknown = JSON.parse(raw);
    return Array.isArray(list) ? list.filter(isRecent).slice(0, MAX_RECENT) : [];
  } catch {
    return [];
  }
}

/** The hit first, without repeating it, at most six. */
export function pushRecent(list: readonly RecentHit[], hit: RecentHit): RecentHit[] {
  const one: RecentHit = { type: hit.type, id: hit.id, label: hit.label, sublabel: hit.sublabel };
  return [one, ...list.filter((r) => !(r.type === hit.type && r.id === hit.id))].slice(
    0,
    MAX_RECENT,
  );
}

export function writeRecent(store: Store | null | undefined, list: readonly RecentHit[]): void {
  try {
    if (list.length) store?.setItem(RECENT_KEY, JSON.stringify(list));
    else store?.removeItem(RECENT_KEY);
  } catch {
    // a private window or a full store: the search still works, it just forgets
  }
}

export function deviceStore(): Store | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

/** The keys that open the search: «/» outside a field, and Ctrl/⌘ K anywhere. */
export function opensSearch(
  e: Pick<KeyboardEvent, "key" | "metaKey" | "ctrlKey" | "altKey">,
  typing: boolean,
): boolean {
  if (e.altKey) return false;
  if (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey)) return true;
  return e.key === "/" && !e.metaKey && !e.ctrlKey && !typing;
}

export function isTyping(target: EventTarget | null): boolean {
  if (!target || typeof (target as HTMLElement).tagName !== "string") return false;
  const el = target as HTMLElement;
  const tag = el.tagName.toLowerCase();
  return tag === "input" || tag === "textarea" || tag === "select" || el.isContentEditable === true;
}
