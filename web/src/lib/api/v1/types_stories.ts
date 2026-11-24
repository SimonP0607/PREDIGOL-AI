/**
 * C-06, the news as stories (plan de correcciones UX, AP-N01 to AP-N06): the stories of `news.stories` with their articles and who
 * they name, in four views - the front page, one story, the search and a match's stories. Mirrors
 * `backend/src/fbi/api/contracts/intelligence/stories.py`; behind FBI_NEWS_FEED and FBI_NEWS_V2 (404 while either is off).
 *
 * What NEVER travels: an article's text, title or picture, its author, a link to a selection. The web paints PrediGol's own words
 * and the source's name, time and link - nothing else - and no image of a third party (the picture is a monogram).
 */
import type { ItemList, Maybe } from "./types_intelligence";

export type StoryCategory =
  | "fichajes"
  | "bajas_y_sanciones"
  | "declaraciones"
  | "resultados_y_proximos"
  | "selecciones"
  | "colombia"
  | "internacional"
  | "competiciones"
  // C-06 1.1: the general news
  | "premios"
  | "ceremonias"
  | "polemicas"
  | "actualidad";

/** How confirmed a story is. Syndication does not raise it. */
export type StoryLevel = "oficial" | "dos_origenes" | "declaracion" | "un_medio" | "rumor";
export type StoryWarning = "contradiccion" | "desactualizada";
export type EntityKind =
  "team" | "player" | "coach" | "referee" | "competition" | "fixture" | "venue";
export type EntityRole = "protagonista" | "mencionado";
export type StoryView = "portada" | "noticia" | "busqueda" | "partido";
export type StorySort = "reciente" | "relevante";

export interface StorySource {
  name: string;
  /** Always a `Missing` (`pendiente_derechos`) until the lawyer answers. */
  author: Maybe<string>;
  published_at: Maybe<string>;
  published_day_only: boolean;
  /** When PrediGol first saw it. */
  known_at: string;
  url: string;
}

export interface StoryEntity {
  type: EntityKind;
  id: number;
  name: Maybe<string>;
  role: EntityRole;
  method: "plantilla" | "alias" | "proveedor" | "manual";
  confidence: number;
}

export interface StoryCard {
  /** The story's key: what GET /news/{item_id} takes. */
  id: string;
  headline_es: Maybe<string>;
  summary_es: Maybe<string>;
  /** C-06 1.1: PrediGol's own text in English, under the same rights; absent from an older API. */
  headline_en?: Maybe<string>;
  summary_en?: Maybe<string>;
  category: Maybe<StoryCategory>;
  level: Maybe<StoryLevel>;
  warnings: StoryWarning[];
  sources_count: number;
  latest_at: string;
  /** Newest first. */
  sources: StorySource[];
  entities: StoryEntity[];
  image: { kind: "monograma" | "grafico_propio" };
}

export interface CategoryCount {
  category: StoryCategory;
  n: number;
}

export interface StoryFront {
  lead_story: Maybe<StoryCard>;
  breaking: ItemList<StoryCard>;
  mine: ItemList<StoryCard>;
  featured: ItemList<StoryCard>;
  counts: CategoryCount[];
  window_hours: number;
  order_version: string;
}

export interface StoryTimelineEntry {
  known_at: string;
  level: Maybe<StoryLevel>;
  source: string;
}

export interface StoryRelated {
  id: string;
  headline_es: Maybe<string>;
  /** C-06 1.1; absent from an older API. */
  headline_en?: Maybe<string>;
  level: Maybe<StoryLevel>;
}

export interface MatchImpact {
  fixture_id: number;
  kickoff_at: string;
  aspect_es: string;
  analysis_published: boolean;
}

export interface StoryDetail extends StoryCard {
  essentials_es: Maybe<string>;
  /** C-06 1.1; absent from an older API. */
  essentials_en?: Maybe<string>;
  level_explanation_es: string;
  match_impact: Maybe<MatchImpact>;
  timeline: StoryTimelineEntry[];
  related: ItemList<StoryRelated>;
  rights_notice_es: string;
}

export interface FacetCount {
  code: string;
  n: number;
}

export interface SearchHit {
  story_id: string;
  headline_es: Maybe<string>;
  /** C-06 1.1; absent from an older API. */
  headline_en?: Maybe<string>;
  level: Maybe<StoryLevel>;
  category: Maybe<StoryCategory>;
  sources_count: number;
  latest_at: string;
}

export interface StorySearch {
  query: string;
  normalized: string;
  sort: StorySort;
  filters_applied: { name: string; value: string }[];
  facets: { category: FacetCount[]; level: FacetCount[] };
  results: ItemList<SearchHit>;
  total: number;
  next_offset?: number;
}

export interface MatchStories {
  fixture_id: number;
  kickoff_at: string;
  window_from: string;
  stories: ItemList<StoryCard>;
  /** C-06 1.1 (AP-P11): the newest search of the web for the match; `sin_datos` if never searched; absent when unknown. */
  searched_at?: Maybe<string>;
  /** C-06 1.1: pages read for the match (0 if never searched); `sin_datos` when not counted; absent when unknown. */
  sources_checked?: Maybe<number>;
}

/** C-06, public projection: the body `view` names, and no other. */
export interface StoriesNews {
  view: StoryView;
  front?: StoryFront;
  /** A `Missing` (`retirado_por_derechos` or `pendiente_derechos`) when the story may not be shown. */
  story?: Maybe<StoryDetail>;
  search?: StorySearch;
  match?: MatchStories;
}

/** The search's own parameters; the front page is the answer to none of them. */
export interface StoriesQuery {
  q?: string | undefined;
  country?: string | undefined;
  competition?: number | undefined;
  team?: number | undefined;
  player?: number | undefined;
  since?: string | undefined;
  until?: string | undefined;
  category?: StoryCategory | undefined;
  level?: StoryLevel | undefined;
  mine?: boolean | undefined;
  sort?: StorySort | undefined;
  limit?: number | undefined;
  offset?: number | undefined;
}
