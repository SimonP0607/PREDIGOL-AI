/**
 * The day and filters the reader picked, kept for this browser tab only - so going into a
 * match and back lands on the same list. A view saved on another calendar day is dropped:
 * "today" has moved on.
 */
import { todayKey } from "@/lib/time";
import { STATUS_FILTERS, type StatusFilter } from "./model";

export interface MatchesView {
  day: string;
  status: StatusFilter;
  competition: number | null;
  query: string;
}

const KEY = "predigol.matches.view";
const DAY = /^\d{4}-\d{2}-\d{2}$/;

export function defaultView(): MatchesView {
  return { day: todayKey(), status: "all", competition: null, query: "" };
}

export function readView(): MatchesView {
  const fallback = defaultView();
  try {
    const raw = window.sessionStorage.getItem(KEY);
    if (!raw) return fallback;
    const saved = JSON.parse(raw) as Partial<MatchesView> & { savedOn?: string };
    if (saved.savedOn !== fallback.day) return fallback;
    return {
      day: typeof saved.day === "string" && DAY.test(saved.day) ? saved.day : fallback.day,
      status: STATUS_FILTERS.includes(saved.status as StatusFilter)
        ? (saved.status as StatusFilter)
        : "all",
      competition:
        typeof saved.competition === "number" && Number.isFinite(saved.competition)
          ? saved.competition
          : null,
      query: typeof saved.query === "string" ? saved.query.slice(0, 80) : "",
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
