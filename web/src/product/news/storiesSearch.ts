/**
 * What the news page holds in its address (plan de correcciones UX, AP-N03): the search and every filter, so a search can be
 * shared, reloaded and gone back to. Pure: it reads and writes the address' fields and builds the API's query.
 */
import type {
  StoriesQuery,
  StoryCategory,
  StoryLevel,
  StorySort,
} from "@/lib/api/v1/types_stories";
import { CATEGORY_ORDER } from "./storyKinds";

export interface StoriesSearchParams {
  q?: string;
  country?: string;
  competition?: number;
  team?: number;
  player?: number;
  since?: string;
  until?: string;
  category?: StoryCategory;
  level?: StoryLevel;
  mine?: true;
  sort?: StorySort;
}

export const LEVELS: readonly StoryLevel[] = [
  "oficial",
  "dos_origenes",
  "declaracion",
  "un_medio",
  "rumor",
];

const DAY = /^\d{4}-\d{2}-\d{2}$/;
const positive = (v: unknown): number | undefined => {
  const n = typeof v === "number" ? v : typeof v === "string" && /^\d+$/.test(v) ? Number(v) : NaN;
  return Number.isSafeInteger(n) && n > 0 ? n : undefined;
};

/** The address' fields, keeping only what is valid: anything else is dropped, never sent to the API. */
export function parseStoriesSearch(raw: Record<string, unknown>): StoriesSearchParams {
  const out: StoriesSearchParams = {};
  const q = typeof raw["q"] === "string" ? raw["q"].trim().slice(0, 120) : "";
  if (q) out.q = q;
  const country = typeof raw["country"] === "string" ? raw["country"].trim().toUpperCase() : "";
  if (/^[A-Z]{2,3}$/.test(country)) out.country = country;
  for (const key of ["competition", "team", "player"] as const) {
    const n = positive(raw[key]);
    if (n) out[key] = n;
  }
  for (const key of ["since", "until"] as const) {
    const v = raw[key];
    if (typeof v === "string" && DAY.test(v)) out[key] = v;
  }
  if (CATEGORY_ORDER.includes(raw["category"] as StoryCategory)) {
    out.category = raw["category"] as StoryCategory;
  }
  if (LEVELS.includes(raw["level"] as StoryLevel)) out.level = raw["level"] as StoryLevel;
  if (raw["mine"] === true || raw["mine"] === "true") out.mine = true;
  if (raw["sort"] === "reciente" || raw["sort"] === "relevante") out.sort = raw["sort"];
  return out;
}

/** The front page answers no search and no filter: it is what the page shows with an empty address. */
export function isFront(s: StoriesSearchParams): boolean {
  return Object.keys(s).length === 0;
}

/** The API's query for a search (a date is the whole day: from its start to the end of the other). */
export function storiesQuery(s: StoriesSearchParams, offset = 0): StoriesQuery {
  return {
    ...s,
    ...(s.since ? { since: `${s.since}T00:00:00Z` } : {}),
    ...(s.until ? { until: `${s.until}T23:59:59Z` } : {}),
    limit: 20,
    ...(offset > 0 ? { offset } : {}),
  };
}

/** The same search without one field (the «quitar» of a filter chip). */
export function without(
  s: StoriesSearchParams,
  key: keyof StoriesSearchParams,
): StoriesSearchParams {
  const { [key]: _gone, ...rest } = s;
  void _gone;
  return rest;
}
