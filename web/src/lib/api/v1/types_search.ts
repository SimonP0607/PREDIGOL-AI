/**
 * GET /search/v2 (C-10, Intelligence; plan UX, AP-B07): the search in groups, as the public projection answers it. Mirrors
 * fbi.api.contracts.intelligence.search for the fields the readers' search reads. Coaches, referees, stadiums and news are
 * in the contract too; the page draws none of them until it has a page to open for each.
 */

export interface SearchEntityHitV2 {
  kind: "team" | "national_team" | "player" | "competition" | "coach" | "referee" | "venue";
  id: number;
  label: string;
  /** Country (team, competition), current team (player), city (stadium); may be empty. */
  sublabel: string;
  /** C-10 1.1: the name that matched what was typed (the Spanish one for «España»); absent in an answer of 1.0. */
  matched?: string;
  /** C-10 1.1: where that name comes from; `localized` is the name in the reader's language. */
  alias_type?: string;
}

export interface SearchFixtureHitV2 {
  id: number;
  /** «Home v Away». */
  label: string;
  /** The competition. */
  sublabel: string;
  kickoff_at: string;
}

/** A group: its hits, or why there are none (`sin_resultados`, `no_entregado`...). */
export interface SearchGroupV2<T> {
  items: T[];
  missing_reason?: string | null;
}

export interface SearchV2 {
  query: string;
  normalized: string;
  groups: {
    teams: SearchGroupV2<SearchEntityHitV2>;
    national_teams: SearchGroupV2<SearchEntityHitV2>;
    players: SearchGroupV2<SearchEntityHitV2>;
    competitions: SearchGroupV2<SearchEntityHitV2>;
    fixtures: SearchGroupV2<SearchFixtureHitV2>;
  };
  /** «¿Quisiste decir…?»: close names, only when no group has a hit. */
  did_you_mean: SearchGroupV2<{ text: string }>;
}
