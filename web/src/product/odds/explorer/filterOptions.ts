/** The options the filters offer, and the words of the window and the orders. Pure. */
import { t } from "@/lib/i18n";
import { countryLabel } from "@/product/matches/country";
import type { BoardSort, CompetitionBadge } from "./model";
import type { ExplorerWindow } from "./state";

export interface FilterOptions {
  countries: ReadonlyArray<{ key: string; label: string }>;
  competitions: ReadonlyArray<{ key: string; label: string; country: string }>;
  bookmakers: ReadonlyArray<{ key: string; label: string }>;
  /** «Mis equipos y ligas» is offered (the reader's follow set is known). */
  follow: boolean;
}

const WORLD = "World";

/** The options of the pickers: the countries and competitions of the loaded pages, and their bookmakers. */
export function filterOptions(
  competitions: ReadonlyMap<number, CompetitionBadge>,
  bookmakers: ReadonlyMap<number, string>,
  follow: boolean,
): FilterOptions {
  const countries = new Map<string, string>();
  for (const c of competitions.values()) {
    const key = (c.country ?? "").trim() || WORLD;
    if (!countries.has(key)) {
      countries.set(key, countryLabel(key, null) ?? t("explorer.filters.international"));
    }
  }
  const byLabel = (a: { label: string }, b: { label: string }) => a.label.localeCompare(b.label);
  return {
    // International competitions last, as the Cuotas page has them.
    countries: [...countries]
      .map(([key, label]) => ({ key, label }))
      .sort((a, b) => Number(a.key === WORLD) - Number(b.key === WORLD) || byLabel(a, b)),
    competitions: [...competitions.values()]
      .map((c) => ({
        key: String(c.id),
        label: c.name,
        country: (c.country ?? "").trim() || WORLD,
      }))
      .sort(byLabel),
    bookmakers: [...bookmakers]
      .map(([id, name]) => ({ key: String(id), label: name }))
      .sort(byLabel),
    follow,
  };
}

export function windowLabel(w: ExplorerWindow): string {
  return w === "today" ? t("explorer.filters.today") : t("explorer.filters.hours", { count: w });
}

export function sortLabel(s: BoardSort): string {
  return t(`explorer.sort.${s}`);
}
