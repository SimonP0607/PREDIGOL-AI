/**
 * Where the reader's view of Partidos lives (plan Partidos, P4).
 *
 * - The day, the state, the country, the category, the competition and the search are in the URL
 *   (`/matches?day=2026-11-08&status=live&country=ES&category=league&competition=7&q=betis`): a copied link reproduces
 *   the view, and going into a match and back lands on the same list. Each parameter is validated: one it cannot read
 *   is dropped, never an error. What equals its default (today, every state, nothing chosen) is left out.
 * - The same view is kept for this browser tab (sessionStorage) as a fallback: a bare `/matches` - the menu's link -
 *   opens on it. The URL wins whenever it says anything. A view saved on another calendar day is dropped: "today" has
 *   moved on. The scope (Tus ligas / Todos) is kept there only.
 * - The folded competitions are kept for this tab too.
 */
import { todayKey } from "@/lib/time";
import type { Scope } from "@/product/favorites/follow";
import { CATEGORIES, type Category } from "./facets";
import { STATUS_FILTERS, type StatusFilter } from "./model";

export interface MatchesView {
  day: string;
  status: StatusFilter;
  competition: number | null;
  /** A team, or a competition by its name or country (plan Partidos, P6). */
  query: string;
  country: string | null;
  category: Category | null;
  /**
   * The reader's own leagues and teams (plan UX, B2), or every match; null until the reader chooses: their own once they
   * have chosen favourites, every match while they are the suggested ones.
   */
  scope: Scope | null;
}

/** The view as the URL carries it: only what differs from the default. */
export interface MatchesSearch {
  day?: string | undefined;
  status?: Exclude<StatusFilter, "all"> | undefined;
  country?: string | undefined;
  category?: Category | undefined;
  competition?: number | undefined;
  q?: string | undefined;
}

const KEY = "predigol.matches.view";
const FOLDED = "predigol.matches.collapsed";
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const MAX_QUERY = 80;
const MAX_COUNTRY = 40;

export function defaultView(): MatchesView {
  return {
    day: todayKey(),
    status: "all",
    competition: null,
    query: "",
    country: null,
    category: null,
    scope: null,
  };
}

/** A calendar day that exists: "2026-02-30" is not one. */
export function isDay(value: unknown): value is string {
  if (typeof value !== "string" || !DAY.test(value)) return false;
  const [y, m, d] = value.split("-").map(Number) as [number, number, number];
  const date = new Date(Date.UTC(y, m - 1, d));
  return date.getUTCFullYear() === y && date.getUTCMonth() === m - 1 && date.getUTCDate() === d;
}

/** The router parses `?q=123` as a number and `?q=true` as a boolean: a text field takes them back as text. */
function text(value: unknown, max: number): string | undefined {
  const s =
    typeof value === "string"
      ? value
      : typeof value === "number" && Number.isFinite(value)
        ? String(value)
        : typeof value === "boolean"
          ? String(value)
          : "";
  const out = s.trim().slice(0, max);
  return out ? out : undefined;
}

function competitionId(value: unknown): number | undefined {
  const n = typeof value === "number" ? value : typeof value === "string" ? Number(value) : NaN;
  return Number.isSafeInteger(n) && n > 0 ? n : undefined;
}

/** `validateSearch` of /matches: what it cannot read it drops. */
export function parseMatchesSearch(raw: Record<string, unknown>): MatchesSearch {
  const status = raw["status"];
  const category = raw["category"];
  const out: MatchesSearch = {};
  if (isDay(raw["day"])) out.day = raw["day"];
  if (status !== "all" && STATUS_FILTERS.includes(status as StatusFilter)) {
    out.status = status as Exclude<StatusFilter, "all">;
  }
  const country = text(raw["country"], MAX_COUNTRY);
  if (country) out.country = country;
  if (CATEGORIES.includes(category as Category)) out.category = category as Category;
  const competition = competitionId(raw["competition"]);
  if (competition !== undefined) out.competition = competition;
  const q = text(raw["q"], MAX_QUERY);
  if (q) out.q = q;
  return out;
}

/** Whether the URL says anything about the view. */
export function hasFilters(search: MatchesSearch): boolean {
  return Object.values(search).some((v) => v !== undefined);
}

/** The URL's view; what it leaves out is the default. The scope is not in the URL. */
export function viewOf(search: MatchesSearch, today: string, scope: Scope | null): MatchesView {
  return {
    day: search.day ?? today,
    status: search.status ?? "all",
    competition: search.competition ?? null,
    query: search.q ?? "",
    country: search.country ?? null,
    category: search.category ?? null,
    scope,
  };
}

/** The view as the URL writes it: nothing that equals its default. */
export function searchOf(view: MatchesView, today: string): MatchesSearch {
  const out: MatchesSearch = {};
  if (view.day !== today && isDay(view.day)) out.day = view.day;
  if (view.status !== "all") out.status = view.status;
  if (view.country !== null) out.country = view.country;
  if (view.category !== null) out.category = view.category;
  if (view.competition !== null) out.competition = view.competition;
  const q = view.query.trim();
  if (q) out.q = q.slice(0, MAX_QUERY);
  return out;
}

export function readView(): MatchesView {
  const fallback = defaultView();
  try {
    const raw = window.sessionStorage.getItem(KEY);
    if (!raw) return fallback;
    const saved = JSON.parse(raw) as Partial<MatchesView> & { savedOn?: string };
    if (saved.savedOn !== fallback.day) return fallback;
    return {
      day: isDay(saved.day) ? saved.day : fallback.day,
      status: STATUS_FILTERS.includes(saved.status as StatusFilter)
        ? (saved.status as StatusFilter)
        : "all",
      competition:
        typeof saved.competition === "number" && Number.isFinite(saved.competition)
          ? saved.competition
          : null,
      query: typeof saved.query === "string" ? saved.query.slice(0, MAX_QUERY) : "",
      country: typeof saved.country === "string" ? saved.country.slice(0, MAX_COUNTRY) : null,
      category: CATEGORIES.includes(saved.category as Category)
        ? (saved.category as Category)
        : null,
      scope: saved.scope === "all" || saved.scope === "mine" ? saved.scope : null,
    };
  } catch {
    return fallback;
  }
}

export function writeView(view: MatchesView): void {
  try {
    window.sessionStorage.setItem(KEY, JSON.stringify({ ...view, savedOn: todayKey() }));
  } catch {
    /* storage unavailable: the view lasts for this visit only */
  }
}

/** The competitions the reader folded away in this tab (by id). */
export function readCollapsed(): Set<number> {
  try {
    const raw = window.sessionStorage.getItem(FOLDED);
    if (!raw) return new Set();
    const ids: unknown = JSON.parse(raw);
    if (!Array.isArray(ids)) return new Set();
    return new Set(ids.filter((id): id is number => Number.isSafeInteger(id)).slice(0, 500));
  } catch {
    return new Set();
  }
}

export function writeCollapsed(ids: ReadonlySet<number>): void {
  try {
    if (ids.size === 0) window.sessionStorage.removeItem(FOLDED);
    else window.sessionStorage.setItem(FOLDED, JSON.stringify([...ids]));
  } catch {
    /* storage unavailable: the folds last for this visit only */
  }
}
