/**
 * The reads of the news as stories (C-06; FBI_NEWS_FEED and FBI_NEWS_V2, 404 while either is off). They live with the news pages,
 * not in the API client every first visit downloads: the budget of the start's JS has no room for a screen's own calls.
 */
import { getJson } from "@/lib/api/v1/client";
import type { Envelope } from "@/lib/api/v1/types";
import type { StoriesNews, StoriesQuery } from "@/lib/api/v1/types_stories";

export const stories = {
  /** The front page, or - with a text or any filter - the search with its facets. PrediGol's own words only. */
  news: (q: StoriesQuery = {}) =>
    getJson<Envelope<StoriesNews | null>>("/news/v2", {
      ...(q.q ? { q: q.q } : {}),
      ...(q.country ? { country: q.country } : {}),
      ...(q.competition ? { competition: String(q.competition) } : {}),
      ...(q.team ? { team: String(q.team) } : {}),
      ...(q.player ? { player: String(q.player) } : {}),
      ...(q.since ? { from: q.since } : {}),
      ...(q.until ? { to: q.until } : {}),
      ...(q.category ? { category: q.category } : {}),
      ...(q.level ? { level: q.level } : {}),
      ...(q.mine ? { mine: "true" } : {}),
      ...(q.sort ? { sort: q.sort } : {}),
      ...(q.limit ? { limit: String(q.limit) } : {}),
      ...(q.offset ? { offset: String(q.offset) } : {}),
    }),
  /** One story by its key (`st-...`): `retirado_por_derechos` and `pendiente_derechos` come as a `Missing`, never as text. */
  story: (key: string) => getJson<Envelope<StoriesNews | null>>(`/news/${encodeURIComponent(key)}`),
  /** The stories of a match, inside its window (the previous match of either team, or 14 days before). */
  match: (id: string | number) => getJson<Envelope<StoriesNews | null>>(`/matches/${id}/news/v2`),
};
