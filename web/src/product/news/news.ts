/**
 * The words of a news card (plan UX, A10; section 27), apart from the page so they can be tested: the headline (what kind
 * of news and about whom), the status and the relevance with their explanations, the source's standing in words, the time
 * - relative, a day when the source gave only the day, or when PrediGol saw it -, PrediGol's own summary or, when it could
 * not be sent, a sentence written from the card's kind, player, team and source; and the groups of the order (confirmed and
 * probable, contradictions, rumours, the outdated).
 */
import { getLocale, t } from "@/lib/i18n";
import { formatDate, formatDateTime, formatRelative, getTimeZone, relativeDay } from "@/lib/time";
import type {
  NewsAssertion,
  NewsClaim,
  NewsItem,
  NewsKind,
  NewsSource,
  NewsStatus,
  TodayNewsItem,
} from "@/lib/api/v1/types_news";

/** The kinds whose label depends on what is asserted (an absence, a doubt, a return, a starter). */
const BY_ASSERTION: ReadonlySet<NewsKind> = new Set(["injury", "suspension", "doubtful", "lineup"]);

/** «Baja por lesión», «En duda», «Titular», «Entrenador»... */
export function kindLabel(kind: NewsKind, assertion: NewsAssertion): string {
  return BY_ASSERTION.has(kind)
    ? t(`match.news.kind.${kind}.${assertion}`)
    : t(`match.news.kind.${kind}.any`);
}

/** What a contradiction is about, without taking either side: «Sanción», «Alineación»... */
export function topicLabel(kind: NewsKind): string {
  return t(`match.news.topic.${kind}`);
}

/** Who the card is about: «Bruno Fernandes (Manchester United)», the team alone, or nobody. */
export function who(item: Pick<NewsItem, "player" | "team">): string | null {
  if (item.player && item.team) return `${item.player} (${item.team.name})`;
  return item.player ?? item.team?.name ?? null;
}

/** The headline: the kind and its protagonist - «Baja por lesión · Bruno Fernandes (Manchester United)». */
export function headline(item: NewsItem): string {
  const first = item.claims[0];
  const label =
    item.claims.length > 1 || !first
      ? topicLabel(item.kind)
      : kindLabel(item.kind, first.assertion);
  const about = who(item);
  return about ? `${label} · ${about}` : label;
}

export function statusLabel(status: NewsStatus): string {
  return t(`match.news.status.${status}.label`);
}

export function statusHelp(status: NewsStatus): string {
  return t(`match.news.status.${status}.help`);
}

/** «sport.es · medio de comunicación». */
export function sourceLine(source: NewsSource): string {
  return `${source.name} · ${t(`match.news.tier.${source.tier}`)}`;
}

/**
 * When it was published, in the reader's zone: «Publicada hace 3 h»; «Publicada el vie 24 oct» when the source gave only
 * the day (read in UTC, the day the source wrote - never the evening before in America); «Vista por PrediGol hace 2 h»
 * when the source said nothing.
 */
export function whenText(
  at: { published_at: string | null; published_day_only: boolean; seen_at?: string },
  now: number = Date.now(),
): string {
  if (at.published_at && at.published_day_only) {
    return t("match.news.time.day", { date: formatDate(at.published_at, "UTC") });
  }
  if (at.published_at)
    return t("match.news.time.published", { when: formatRelative(at.published_at, now) });
  return t("match.news.time.seen", { when: formatRelative(at.seen_at ?? null, now) });
}

/** The exact time behind «hace 3 h», for a pointer or a tap: «24 oct 13:04». */
export function whenTitle(at: {
  published_at: string | null;
  published_day_only: boolean;
  seen_at?: string;
}): string {
  if (at.published_at && at.published_day_only) return formatDate(at.published_at, "UTC");
  const iso = at.published_at ?? at.seen_at ?? null;
  return iso ? formatDateTime(iso, getTimeZone()) : "";
}

/**
 * PrediGol's own summary, or - when it could not be sent (it did not read as Spanish, or it repeated the source's title) - a
 * sentence from the card's facts: «Bruno Fernandes (Manchester United) no jugará, según as.com.» Never empty.
 */
export function summary(item: Pick<NewsItem, "player" | "team">, claim: NewsClaim): string {
  if (claim.text) return claim.text;
  const source = claim.sources[0]?.name ?? t("match.news.someSource");
  const person = item.player ? who(item) : null;
  if (person) return t(`match.news.fallback.${claim.assertion}.player`, { who: person, source });
  return t(`match.news.fallback.${claim.assertion}.team`, {
    team: item.team?.name ?? t("match.news.theTeam"),
    source,
  });
}

/** Whether the summary shown is the Spanish one on a page in another language: it is labelled «(in Spanish)». */
export function shownInSpanish(claim: NewsClaim): boolean {
  return claim.text !== null && getLocale() !== "es";
}

export type NewsGroup = "verified" | "contradictory" | "rumor" | "outdated";

const GROUP_OF: Readonly<Record<NewsStatus, NewsGroup>> = {
  CONFIRMED: "verified",
  PROBABLE: "verified",
  CONTRADICTORY: "contradictory",
  RUMOR: "rumor",
  OUTDATED: "outdated",
};

/** The cards in the API's order, cut into the groups the page names: the rumours and the outdated come last, labelled. */
export function groups(items: NewsItem[]): Array<{ group: NewsGroup; items: NewsItem[] }> {
  const out: Array<{ group: NewsGroup; items: NewsItem[] }> = [];
  for (const item of items) {
    const group = GROUP_OF[item.status];
    const last = out[out.length - 1];
    if (last && last.group === group) last.items.push(item);
    else out.push({ group, items: [item] });
  }
  return out;
}

/** The press's absences for Alineaciones: what is said about who will not play or is in doubt - never a rumour. */
const ABSENCE_KINDS: ReadonlySet<NewsKind> = new Set(["injury", "suspension", "doubtful"]);
const SAID: ReadonlySet<NewsStatus> = new Set(["CONFIRMED", "PROBABLE", "CONTRADICTORY"]);

export function pressAbsences(items: NewsItem[]): NewsItem[] {
  return items.filter(
    (i) =>
      ABSENCE_KINDS.has(i.kind) &&
      SAID.has(i.status) &&
      i.claims.some((c) => c.assertion === "out" || c.assertion === "doubtful"),
  );
}

/** Home's block 4: the news of the matches the reader has today (in play, or kicking off today in their zone). */
export function todayOnly<T extends { match: { kickoff_at: string; status_group: string } }>(
  items: T[],
  tz: string = getTimeZone(),
  now: number = Date.now(),
): T[] {
  return items.filter(
    (i) => i.match.status_group === "live" || relativeDay(i.match.kickoff_at, tz, now) === "today",
  );
}

export const HOME_NEWS = 4;

const STATUS_RANK: Readonly<Partial<Record<NewsStatus, number>>> = { CONFIRMED: 0, PROBABLE: 1 };
const RELEVANCE_RANK = { high: 0, medium: 1, low: 2 } as const;

/** Today's (in the reader's zone) or in play, confirmed first, the most relevant, then the newest: four at most. */
export function homeNews<T extends TodayNewsItem>(items: T[], tz: string, now: number): T[] {
  const when = (i: T) => Date.parse(i.item.published_at ?? i.item.seen_at);
  return todayOnly(items, tz, now)
    .slice()
    .sort(
      (a, b) =>
        (STATUS_RANK[a.item.status] ?? 9) - (STATUS_RANK[b.item.status] ?? 9) ||
        RELEVANCE_RANK[a.item.relevance] - RELEVANCE_RANK[b.item.relevance] ||
        when(b) - when(a),
    )
    .slice(0, HOME_NEWS);
}
