/**
 * How the Matches page narrows a day's rows with the reader's filters (plan Partidos, P2 and P3). Pure: no React here.
 *
 * - The pickers offer what plays that day: the countries, the categories (within the country) and the competitions
 *   (within both).
 * - A country, a category or a competition that does not play that day - saved on another day, or in a link - is
 *   ignored: the list shows them all and its picker says «Todos», instead of an empty list under a picker that looks
 *   unset (P2).
 * - The state chips count what each state would show with every other filter on: country, category, competition and
 *   the search (P3).
 */
import { CATEGORIES, categoriesOf, countryKey, countryOptions, inFacets, playing } from "./facets";
import type { Category, CountryOption } from "./facets";
import {
  competitionOptions,
  inStatus,
  statusCounts,
  type CompetitionOption,
  type MatchItem,
  type StatusFilter,
} from "./model";

export interface DayFilters {
  status: StatusFilter;
  country: string | null;
  category: Category | null;
  competition: number | null;
  query: string;
}

export interface CategoryOption {
  key: Category;
  label: string;
  count: number;
}

export interface NarrowedDay {
  countries: CountryOption[];
  categories: CategoryOption[];
  options: CompetitionOption[];
  /** The filters that play that day (the others are null, or "" for the search). */
  country: string | null;
  category: Category | null;
  competition: number | null;
  query: string;
  /** Every filter but the state. */
  narrowed: readonly MatchItem[];
  counts: Record<StatusFilter, number>;
  /** Every filter, the state too: the rows of the list. */
  visible: MatchItem[];
}

export function narrowDay(
  items: readonly MatchItem[],
  f: DayFilters,
  locale: string,
  labels: { international: string; category: (key: Category) => string },
): NarrowedDay {
  const countries = countryOptions(
    items.map((i) => i.match),
    locale,
    labels.international,
  );
  const country = playing(f.country, countries);
  const inCountry =
    country === null ? items : items.filter((it) => countryKey(it.match.competition) === country);
  const categories = CATEGORIES.map((key) => ({
    key,
    label: labels.category(key),
    count: inCountry.filter((it) => categoriesOf(it.match.competition).includes(key)).length,
  })).filter((c) => c.count > 0);
  const category = playing(f.category, categories);
  const inScope =
    category === null
      ? inCountry
      : inCountry.filter((it) => categoriesOf(it.match.competition).includes(category));
  const options = competitionOptions(inScope, locale);
  const competition = playing(
    f.competition,
    options.map((o) => ({ key: o.id })),
  );
  const query = f.query.trim();
  const narrowed =
    competition === null && !query
      ? inScope
      : inScope.filter((it) =>
          inFacets(it.match, { country: null, category: null, competition, query }),
        );
  return {
    countries,
    categories,
    options,
    country,
    category,
    competition,
    query,
    narrowed,
    counts: statusCounts(narrowed),
    visible: narrowed.filter((it) => inStatus(it.group, f.status)),
  };
}
