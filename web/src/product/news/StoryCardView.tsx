/**
 * A story as the front and the search draw it (plan de correcciones UX, AP-N01/N03; maqueta 08): its monogram where a picture
 * would be, how confirmed it is in words, PrediGol's own headline and summary, and «Según A y B · 3 fuentes · hace 2 h».
 * Never an article's text, title or picture. The whole card leads to the story's page.
 */
import { Link } from "@tanstack/react-router";
import { formatRelative } from "@/lib/time";
import { cn } from "@/lib/utils";
import type { SearchHit, StoryCard } from "@/lib/api/v1/types_stories";
import { CategoryChip, LevelChip, Monogram, WarningChips } from "./StoryBits";
import {
  categoryOf,
  headlineOf,
  inSpanishNote,
  levelOf,
  sourceNames,
  sourcesCount,
  summaryOf,
  textLang,
} from "./stories";
import { t } from "./storyText";

/** «Según Club y Diario · 2 fuentes · hace 2 h». */
export function byline(
  card: Pick<StoryCard, "sources" | "sources_count" | "latest_at">,
  now: number,
): string {
  const names = sourceNames(card, 2);
  const parts: string[] = [];
  if (names.length > 0) parts.push(t("stories.by", { names: names.join(" · ") }));
  parts.push(sourcesCount(card.sources_count));
  parts.push(formatRelative(card.latest_at, now));
  return parts.join(" · ");
}

export function StoryCardView({
  card,
  now = Date.now(),
  size = "normal",
}: {
  card: StoryCard;
  now?: number;
  size?: "lead" | "normal";
}) {
  const headline = headlineOf(card);
  const summary = summaryOf(card);
  const lang = textLang();
  const note = inSpanishNote();
  return (
    <li data-testid="story-card" data-story={card.id} className="list-none">
      <article
        className={cn(
          "card-surface relative flex gap-3 rounded-card p-4 transition-colors hover:bg-elevated/60",
          size === "lead" && "flex-col sm:flex-row sm:p-5",
        )}
      >
        <Monogram
          card={card}
          className={size === "lead" ? "h-20 w-20 text-2xl" : "h-12 w-12 text-base"}
        />
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex flex-wrap items-center gap-1.5">
            <LevelChip level={levelOf(card)} />
            {categoryOf(card) ? <CategoryChip category={categoryOf(card)!} /> : null}
            <WarningChips warnings={card.warnings} />
          </div>
          <h3
            className={cn(
              "font-semibold leading-snug",
              size === "lead" ? "text-title" : "text-base",
            )}
            lang={lang}
          >
            <Link
              to="/news/$key"
              params={{ key: card.id }}
              className="after:absolute after:inset-0 hover:text-primary focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              aria-label={`${t("stories.card.open")}: ${headline ?? t("stories.untitled")}`}
            >
              {headline ?? t("stories.untitled")}
            </Link>
          </h3>
          {summary ? (
            <p className="text-sm text-muted-foreground" lang={lang}>
              {summary}
              {note ? <span className="ml-1 text-caption">{note}</span> : null}
            </p>
          ) : null}
          <p className="text-caption text-muted-foreground">{byline(card, now)}</p>
        </div>
      </article>
    </li>
  );
}

/** A search result: the card's essentials, without sources (the search gives only their count). */
export function StoryHitView({ hit, now = Date.now() }: { hit: SearchHit; now?: number }) {
  const headline = headlineOf(hit);
  const lang = textLang();
  return (
    <li data-testid="story-hit" data-story={hit.story_id} className="list-none">
      <article className="card-surface relative flex flex-col gap-1.5 rounded-card p-4 hover:bg-elevated/60">
        <div className="flex flex-wrap items-center gap-1.5">
          <LevelChip level={levelOf(hit)} />
          {categoryOf(hit) ? <CategoryChip category={categoryOf(hit)!} /> : null}
        </div>
        <h3 className="text-base font-semibold leading-snug" lang={lang}>
          <Link
            to="/news/$key"
            params={{ key: hit.story_id }}
            className="after:absolute after:inset-0 hover:text-primary focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            aria-label={`${t("stories.card.open")}: ${headline ?? t("stories.untitled")}`}
          >
            {headline ?? t("stories.untitled")}
          </Link>
        </h3>
        <p className="text-caption text-muted-foreground">
          {sourcesCount(hit.sources_count)} · {formatRelative(hit.latest_at, now)}
        </p>
      </article>
    </li>
  );
}
