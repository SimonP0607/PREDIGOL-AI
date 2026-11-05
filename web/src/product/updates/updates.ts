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

export interface UpdateEntry {
  /** YYYY-MM-DD-slug: the day readers could see it, and a name. */
  id: string;
  /** The catalogue key of its words. */
  key: string;
  /** Where to see it, with the label key of support.updates.go. */
  to?: string;
  go?: string;
  /** It came from what readers told PrediGol (a suggestion, a survey's comment). */
  fromReaders?: boolean;
}

/** Newest first. */
export const UPDATES: readonly UpdateEntry[] = [
  { id: "2026-11-04-explicame", key: "explain", to: "/matches", go: "matches" },
  { id: "2026-10-27-tu-opinion", key: "feedback" },
  { id: "2026-10-27-mis-picks", key: "myPicks", to: "/my-picks", go: "myPicks" },
  { id: "2026-10-27-postpartido", key: "postmatch", to: "/matches", go: "matches" },
  { id: "2026-10-27-por-que-este-pick", key: "whyPick", to: "/picks", go: "picks" },
  { id: "2026-10-27-tu-futbol", key: "football", to: "/profile#football", go: "profile" },
  { id: "2026-10-27-centro-de-partido", key: "matchCentre", to: "/matches", go: "matches" },
  { id: "2026-10-27-ayuda-y-app", key: "help", to: "/help", go: "help" },
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
