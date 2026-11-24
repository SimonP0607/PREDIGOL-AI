/**
 * The stories of a match (plan de correcciones UX, AP-N04 and AP-P11a; maqueta 09; contrato C-06 `partido`): what the sources
 * say about the match, from the previous match of either team (or 14 days before) until it is played - each as a card with
 * its level in words -, with a way to the rest of each team's stories. PrediGol's words only. Behind FBI_NEWS_FEED and
 * FBI_NEWS_V2: the Noticias tab keeps its cards as they were when this has nothing to show.
 */
import { Link } from "@tanstack/react-router";
import { Newspaper } from "lucide-react";
import { formatDate } from "@/lib/time";
import type { MatchStories as MatchStoriesData } from "@/lib/api/v1/types_stories";
import { StoryCardView } from "./StoryCardView";
import { t } from "./storyText";

export interface MatchTeam {
  id: number;
  name: string;
}

export function MatchStoriesView({
  data,
  teams,
  now,
}: {
  data: MatchStoriesData;
  teams: readonly MatchTeam[];
  now?: number;
}) {
  const items = data.stories.items;
  if (items.length === 0) return null;
  return (
    <section
      aria-labelledby="match-stories-title"
      data-testid="match-stories"
      className="min-w-0 rounded-xl border border-border bg-card"
    >
      <header className="flex items-start justify-between gap-3 px-4 pt-3.5">
        <div className="min-w-0">
          <h2
            id="match-stories-title"
            className="flex items-center gap-2 font-display text-[0.95rem] font-bold uppercase tracking-[0.08em]"
          >
            <Newspaper aria-hidden className="h-4 w-4 shrink-0 text-primary" />
            <span className="min-w-0 break-words">{t("stories.match.title")}</span>
          </h2>
          <p className="mt-0.5 text-xs text-muted-foreground">{t("stories.match.note")}</p>
          <p className="mt-0.5 text-caption text-subtle-foreground">
            {t("stories.match.since", { date: formatDate(data.window_from, "UTC") })}
          </p>
        </div>
        <span
          className="shrink-0 text-caption text-subtle-foreground"
          data-testid="match-stories-count"
        >
          {t("stories.match.count", { count: items.length })}
        </span>
      </header>
      <ul className="space-y-2 px-4 pb-3 pt-3">
        {items.map((c) => (
          <StoryCardView key={c.id} card={c} {...(now ? { now } : {})} />
        ))}
      </ul>
      <nav className="flex flex-wrap gap-x-4 px-4 pb-3" aria-label={t("stories.match.all")}>
        {teams.map((team) => (
          <Link
            key={team.id}
            to="/news"
            search={{ team: team.id } as never}
            className="tap-y relative inline-flex min-h-11 items-center text-sm font-semibold text-primary"
          >
            {t("stories.match.team", { team: team.name })}
          </Link>
        ))}
      </nav>
    </section>
  );
}
