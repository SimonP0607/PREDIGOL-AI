/**
 * Novedades (plan UX, B6; section 40): what changed in PrediGol, newest first - the answer to what readers tell us. The
 * entries live here and their words in the catalogues (support.updates.items.<key>.title / .body, ES and EN); an entry
 * says it came from the readers' comments only when it did (``fromReaders``). Each id is its date and a slug, the form
 * the server accepts for «seen» (fbi.customer.feedback.UPDATE_ID), and «Más» marks Novedades while the newest id is not
 * the one the reader saw last.
 *
 * An entry tells what a reader can see today: a change still switched off for readers waits to be written here.
 *
 * The server keeps a copy with the titles (backend/src/fbi/customer/updates.json): the weekly summary by e-mail names the
 * week's entries from it (plan UX, B8). An entry is added in both in the same change; a test checks they are the same.
 */

/** What an entry is (plan maestro UX/UI 2026, decision 9): the page filters by it. A communiqué of the owner is a notice. */
export const UPDATE_KINDS = ["new", "improvement", "fix", "notice"] as const;
export type UpdateKind = (typeof UPDATE_KINDS)[number];

/** The filters of the page, in the sheet's order (T04): everything, then by kind. */
export const UPDATE_FILTERS = ["all", "new", "improvement", "fix"] as const;
export type UpdateFilter = (typeof UPDATE_FILTERS)[number];

export interface UpdateEntry {
  /** YYYY-MM-DD-slug: the day readers could see it, and a name. */
  id: string;
  /** The catalogue key of its words. */
  key: string;
  kind: UpdateKind;
  /** Where to see it, with the label key of support.updates.go. */
  to?: string;
  go?: string;
  /** It came from what readers told PrediGol (a suggestion, a survey's comment). */
  fromReaders?: boolean;
}

/** Newest first. */
export const UPDATES: readonly UpdateEntry[] = [
  { id: "2026-11-06-inicio-para-ti", key: "forYou", kind: "improvement", to: "/home", go: "home" },
  {
    id: "2026-11-06-resumen-para-entender",
    key: "summary",
    kind: "improvement",
    to: "/matches",
    go: "matches",
  },
  {
    id: "2026-11-06-picks-en-una-linea",
    key: "compactWhy",
    kind: "improvement",
    to: "/picks",
    go: "picks",
  },
  {
    id: "2026-11-06-mas-competiciones",
    key: "competitions",
    kind: "improvement",
    to: "/matches",
    go: "matches",
  },
  {
    id: "2026-11-05-seguir-jugadores-y-mercados",
    key: "followMore",
    kind: "new",
    to: "/profile#football",
    go: "profile",
  },
  { id: "2026-11-05-puntos-clave", key: "keyPoints", kind: "new", to: "/matches", go: "matches" },
  {
    id: "2026-11-05-como-funciona",
    key: "howItWorks",
    kind: "new",
    to: "/help/how-it-works",
    go: "howItWorks",
  },
  { id: "2026-11-04-explicame", key: "explain", kind: "new", to: "/matches", go: "matches" },
  { id: "2026-10-27-tu-opinion", key: "feedback", kind: "new" },
  {
    id: "2026-10-27-mis-picks",
    key: "myPicks",
    kind: "improvement",
    to: "/my-picks",
    go: "myPicks",
  },
  { id: "2026-10-27-postpartido", key: "postmatch", kind: "new", to: "/matches", go: "matches" },
  { id: "2026-10-27-por-que-este-pick", key: "whyPick", kind: "new", to: "/picks", go: "picks" },
  {
    id: "2026-10-27-tu-futbol",
    key: "football",
    kind: "new",
    to: "/profile#football",
    go: "profile",
  },
  {
    id: "2026-10-27-centro-de-partido",
    key: "matchCentre",
    kind: "improvement",
    to: "/matches",
    go: "matches",
  },
  { id: "2026-10-27-ayuda-y-app", key: "help", kind: "new", to: "/help", go: "help" },
];

/** fbi.customer.feedback.UPDATE_ID. */
export const UPDATE_ID = /^\d{4}-\d{2}-\d{2}-[a-z0-9-]{1,40}$/;

export const LATEST_UPDATE: string | null = UPDATES[0]?.id ?? null;

/** The day of an entry (its id's date), as an ISO date at noon UTC: the same calendar day in every time zone of the Americas. */
export function updateDay(id: string): string {
  return `${id.slice(0, 10)}T12:00:00Z`;
}

/** Whether «Más» marks Novedades: there is an entry the reader has not seen - the newest is not the last one they saw. */
export function hasUnread(
  lastSeen: string | null | undefined,
  latest: string | null = LATEST_UPDATE,
): boolean {
  if (!latest) return false;
  return lastSeen !== latest;
}

/** How many entries each filter shows: the figures on the filters themselves. */
export function countByFilter(
  entries: readonly { kind: UpdateKind }[],
): Record<UpdateFilter, number> {
  const count = (kind: UpdateKind) => entries.filter((e) => e.kind === kind).length;
  return {
    all: entries.length,
    new: count("new"),
    improvement: count("improvement"),
    fix: count("fix"),
  };
}

export function matchesFilter(kind: UpdateKind, filter: UpdateFilter): boolean {
  return filter === "all" || kind === filter;
}
