/**
 * The news as stories, in what a reader sees (plan de correcciones UX, AP-N01 to AP-N06; C-06): PrediGol's own headline and
 * summary - never an article's text, title, author or picture -, the level of confirmation in words, the sources by name and time,
 * and a monogram where a picture would be (never a third party's). Pure: it reads a card and says it.
 */
import { getLocale } from "@/lib/i18n";
import { formatDate, formatRelative } from "@/lib/time";
import { present } from "@/lib/api/v1/types_intelligence";
import type {
  StoryCard,
  StoryCategory,
  StoryEntity,
  StoryLevel,
  StorySource,
} from "@/lib/api/v1/types_stories";
import { t } from "./storyText";

/** Whole keys, so a catalog key never goes unused or unseen. */
const LEVEL_WORD: Readonly<Record<StoryLevel | "none", string>> = {
  oficial: "stories.level.oficial",
  dos_origenes: "stories.level.dos_origenes",
  declaracion: "stories.level.declaracion",
  un_medio: "stories.level.un_medio",
  rumor: "stories.level.rumor",
  none: "stories.level.none",
};
const LEVEL_HELP: Readonly<Record<StoryLevel | "none", string>> = {
  oficial: "stories.levelHelp.oficial",
  dos_origenes: "stories.levelHelp.dos_origenes",
  declaracion: "stories.levelHelp.declaracion",
  un_medio: "stories.levelHelp.un_medio",
  rumor: "stories.levelHelp.rumor",
  none: "stories.levelHelp.none",
};
const CATEGORY_WORD: Readonly<Record<StoryCategory, string>> = {
  fichajes: "stories.category.fichajes",
  bajas_y_sanciones: "stories.category.bajas_y_sanciones",
  declaraciones: "stories.category.declaraciones",
  resultados_y_proximos: "stories.category.resultados_y_proximos",
  selecciones: "stories.category.selecciones",
  colombia: "stories.category.colombia",
  internacional: "stories.category.internacional",
  competiciones: "stories.category.competiciones",
};

/** The categories in the order the front page lists them (maqueta 08). */
export const CATEGORY_ORDER: readonly StoryCategory[] = [
  "colombia",
  "internacional",
  "selecciones",
  "fichajes",
  "bajas_y_sanciones",
  "declaraciones",
  "resultados_y_proximos",
  "competiciones",
];

export function levelWord(level: StoryLevel | null): string {
  return t(LEVEL_WORD[level ?? "none"]);
}

export function levelHelp(level: StoryLevel | null): string {
  return t(LEVEL_HELP[level ?? "none"]);
}

export function categoryWord(category: StoryCategory): string {
  return t(CATEGORY_WORD[category]);
}

export function levelOf(card: Pick<StoryCard, "level">): StoryLevel | null {
  return present(card.level);
}

export function categoryOf(card: Pick<StoryCard, "category">): StoryCategory | null {
  return present(card.category);
}

/** PrediGol's own headline, or null while no source allows a summary (the story then shows `untitled`, never a source's title). */
export function headlineOf(card: Pick<StoryCard, "headline_es">): string | null {
  const h = present(card.headline_es)?.trim();
  return h ? h : null;
}

export function summaryOf(card: Pick<StoryCard, "summary_es">): string | null {
  const s = present(card.summary_es)?.trim();
  return s ? s : null;
}

/** The text is PrediGol's Spanish: on a page in another language it says so (the translation arrives with C-06 1.1, AP-N06). */
export function textLang(): "es" | undefined {
  return getLocale() === "es" ? undefined : "es";
}

export function inSpanishNote(): string | null {
  return getLocale() === "es" ? null : t("stories.inSpanish");
}

/** The entity a story is mainly about: its protagonist (a team before a player), else the first one named. */
export function protagonist(card: Pick<StoryCard, "entities">): StoryEntity | null {
  const named = card.entities.filter((e) => present(e.name));
  const main = named.filter((e) => e.role === "protagonista");
  return (
    main.find((e) => e.type === "team") ??
    main[0] ??
    named.find((e) => e.type === "team") ??
    named[0] ??
    null
  );
}

const SKIP = new Set([
  "fc",
  "cf",
  "cd",
  "ca",
  "de",
  "del",
  "la",
  "el",
  "los",
  "las",
  "y",
  "and",
  "the",
  "club",
  "sc",
  "ac",
]);

/** Up to two letters for the monogram of a name: «Atlético Nacional» → AN, «Junior» → JU. */
export function initials(name: string): string {
  const words = name
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .split(/[^\p{L}\p{N}]+/u)
    .filter((w) => w && !SKIP.has(w.toLowerCase()));
  const first = words[0] ?? "";
  if (words.length >= 2) return `${first.charAt(0)}${words[1]?.charAt(0) ?? ""}`.toUpperCase();
  return first.slice(0, 2).toUpperCase();
}

/** The letters of a story's monogram: its protagonist's, or «PG» when it names nobody. */
export function monogramOf(card: Pick<StoryCard, "entities">): string {
  const who = protagonist(card);
  const name = who ? present(who.name) : null;
  return (name ? initials(name) : "") || "PG";
}

/** The outlets of a story, each once, newest first, at most `max` of them. */
export function sourceNames(card: Pick<StoryCard, "sources">, max = 3): string[] {
  return [...new Set(card.sources.map((s) => s.name))].slice(0, max);
}

/** «1 fuente» / «3 fuentes». */
export function sourcesCount(n: number): string {
  return t("stories.sources", { count: n });
}

/** When a source published, in the reader's own words: relative, the day only when that is all the source gave, else when PrediGol saw it. */
export function sourceWhen(s: StorySource, now: number = Date.now()): string {
  const at = present(s.published_at);
  if (at && s.published_day_only)
    return t("stories.story.sourceDay", { date: formatDate(at, "UTC") });
  if (at) return t("stories.story.sourceTime", { when: formatRelative(at, now) });
  return t("stories.story.sourceSeen", { when: formatRelative(s.known_at, now) });
}

/** The address of an outlet's page, only when it is a plain web address: nothing else is ever made a link. */
export function safeUrl(url: string): string | null {
  try {
    const u = new URL(url);
    return u.protocol === "https:" || u.protocol === "http:" ? u.toString() : null;
  } catch {
    return null;
  }
}

/** The story's own page. */
export const storyPath = (id: string): string => `/news/${id}`;
