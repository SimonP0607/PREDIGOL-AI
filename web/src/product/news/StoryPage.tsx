/**
 * One story (plan de correcciones UX, AP-N02; maqueta 09; C-06 `noticia`): the essentials in PrediGol's own words, how confirmed it
 * is and why, who it is about, how it bears on a match, how it came to be known, every source with its time and its link («Leer
 * en la fuente») and the related stories. Never an article's text, title, author or picture. A story withdrawn at a request
 * or still in moderation says so and shows nothing of itself. Behind FBI_NEWS_FEED and FBI_NEWS_V2.
 */
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowLeft, ExternalLink, Newspaper } from "lucide-react";
import { LiveApiError } from "@/lib/api/v1/client";
import { stories } from "./storiesApi";
import { isMissing, present } from "@/lib/api/v1/types_intelligence";
import type { StoryDetail, StoryEntity } from "@/lib/api/v1/types_stories";
import { useAuth } from "@/lib/auth/AuthProvider";
import { formatDateTime } from "@/lib/time";
import { EmptyState, ErrorState, SkeletonCards } from "@/product/shared/States";
import { CategoryChip, LevelChip, Monogram, WarningChips } from "./StoryBits";
import {
  categoryOf,
  headlineOf,
  inSpanishNote,
  levelHelp,
  levelOf,
  levelWord,
  safeUrl,
  sourceWhen,
  summaryOf,
  textLang,
} from "./stories";
import { t } from "./storyText";

function EntityLine({ entity }: { entity: StoryEntity }) {
  const name = present(entity.name);
  if (!name) return null;
  const role =
    entity.role === "protagonista" ? t("stories.story.protagonist") : t("stories.story.mentioned");
  const body =
    entity.type === "team" ? (
      <Link
        to="/teams/$teamId"
        params={{ teamId: String(entity.id) }}
        className="font-medium text-primary hover:underline"
      >
        {name}
      </Link>
    ) : entity.type === "player" ? (
      <Link
        to="/players/$playerId"
        params={{ playerId: String(entity.id) }}
        className="font-medium text-primary hover:underline"
      >
        {name}
      </Link>
    ) : entity.type === "competition" ? (
      <Link
        to="/competitions/$competitionId"
        params={{ competitionId: String(entity.id) }}
        className="font-medium text-primary hover:underline"
      >
        {name}
      </Link>
    ) : (
      <span className="font-medium">{name}</span>
    );
  return (
    <li
      className="flex min-h-11 items-center justify-between gap-3 text-sm"
      data-testid="story-entity"
    >
      {body}
      <span className="text-caption text-muted-foreground">{role}</span>
    </li>
  );
}

function Section({
  title,
  children,
  testId,
}: {
  title: string;
  children: React.ReactNode;
  testId: string;
}) {
  return (
    <section
      aria-label={title}
      data-testid={testId}
      className="card-surface space-y-2 rounded-card p-4"
    >
      <h2 className="text-subheading">{title}</h2>
      {children}
    </section>
  );
}

export function StoryBody({ story }: { story: StoryDetail }) {
  const headline = headlineOf(story);
  const essentials = present(story.essentials_es)?.trim() || summaryOf(story);
  const category = categoryOf(story);
  const level = levelOf(story);
  const lang = textLang();
  const note = inSpanishNote();
  const impact = present(story.match_impact);
  const timeline = [...story.timeline].sort((a, b) => a.known_at.localeCompare(b.known_at));
  return (
    <article className="flex flex-col gap-4" data-testid="story-page">
      <header className="flex items-start gap-3">
        <Monogram card={story} />
        <div className="min-w-0 space-y-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <LevelChip level={level} />
            {category ? <CategoryChip category={category} /> : null}
            <WarningChips warnings={story.warnings} />
          </div>
          <h1 className="text-title leading-snug" lang={lang} data-testid="story-headline">
            {headline ?? t("stories.untitled")}
          </h1>
          <p className="text-caption text-muted-foreground">
            {t("stories.latest", { when: formatDateTime(story.latest_at) })}
          </p>
        </div>
      </header>

      <Section title={t("stories.story.essentials")} testId="story-essentials">
        <p className="text-sm leading-relaxed" lang={lang}>
          {essentials ?? t("stories.noSummary")}
        </p>
        {essentials && note ? <p className="text-caption text-muted-foreground">{note}</p> : null}
      </Section>

      <Section title={t("stories.story.level")} testId="story-level-section">
        <p className="flex flex-wrap items-center gap-2 text-sm">
          <LevelChip level={level} />
          <span>{levelWord(level)}</span>
        </p>
        <p className="text-sm text-muted-foreground">{levelHelp(level)}</p>
      </Section>

      {story.entities.some((e) => present(e.name)) ? (
        <Section title={t("stories.story.about")} testId="story-about">
          <ul className="divide-y divide-border">
            {story.entities.map((e) => (
              <EntityLine key={`${e.type}-${e.id}`} entity={e} />
            ))}
          </ul>
        </Section>
      ) : null}

      {impact ? (
        <Section title={t("stories.story.impact")} testId="story-impact">
          <p className="text-sm" lang={lang}>
            {t("stories.story.impactBody", { aspect: impact.aspect_es })}
          </p>
          {impact.analysis_published ? (
            <Link
              to="/matches/$fixtureId"
              params={{ fixtureId: String(impact.fixture_id) }}
              className="inline-flex min-h-11 items-center text-sm font-semibold text-primary"
            >
              {t("stories.story.impactOpen")}
            </Link>
          ) : (
            <p className="text-caption text-muted-foreground">{t("stories.story.impactPending")}</p>
          )}
        </Section>
      ) : null}

      {timeline.length > 0 ? (
        <Section title={t("stories.story.timeline")} testId="story-timeline">
          <ol className="space-y-1.5 border-l border-border-strong pl-3">
            {timeline.map((e, i) => (
              <li key={`${e.known_at}-${i}`} className="text-sm">
                <span className="numeric">
                  {t("stories.story.timelineLine", {
                    when: formatDateTime(e.known_at),
                    source: e.source,
                  })}
                </span>
                <span className="ml-2 align-middle">
                  <LevelChip level={present(e.level)} />
                </span>
              </li>
            ))}
          </ol>
        </Section>
      ) : null}

      <Section title={t("stories.story.sources")} testId="story-sources">
        {story.sources.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("stories.story.noSources")}</p>
        ) : (
          <ul className="divide-y divide-border">
            {story.sources.map((s) => {
              const href = safeUrl(s.url);
              return (
                <li
                  key={`${s.name}-${s.known_at}`}
                  className="flex flex-wrap items-center justify-between gap-2 py-2"
                  data-testid="story-source"
                >
                  <span className="min-w-0 text-sm">
                    <span className="font-medium">{s.name}</span>
                    <span className="block text-caption text-muted-foreground">
                      {sourceWhen(s)}
                    </span>
                  </span>
                  {href ? (
                    <a
                      href={href}
                      target="_blank"
                      rel="noopener noreferrer"
                      aria-label={t("stories.readSourceNamed", { name: s.name })}
                      className="tap-y relative inline-flex min-h-11 items-center gap-1 text-sm font-semibold text-primary"
                    >
                      {t("stories.readSource")}
                      <ExternalLink aria-hidden className="h-3.5 w-3.5" />
                    </a>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </Section>

      {story.related.items.length > 0 ? (
        <Section title={t("stories.story.related")} testId="story-related">
          <ul className="divide-y divide-border">
            {story.related.items.map((r) => (
              <li key={r.id}>
                <Link
                  to="/news/$key"
                  params={{ key: r.id }}
                  className="flex min-h-11 items-center justify-between gap-3 py-2 text-sm hover:text-primary"
                >
                  <span lang={lang}>{present(r.headline_es) ?? t("stories.untitled")}</span>
                  <LevelChip level={present(r.level)} />
                </Link>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      <p className="px-1 text-caption text-muted-foreground" data-testid="story-rights">
        {t("stories.story.rights")}
      </p>
    </article>
  );
}

export function StoryPage({ storyKey }: { storyKey: string }) {
  const auth = useAuth().user;
  const open = auth?.news_feed === true && auth?.news_v2 === true;
  const q = useQuery({
    queryKey: ["v1", "story", storyKey],
    queryFn: () => stories.story(storyKey),
    enabled: open,
    retry: false,
  });
  const back = (
    <Link
      to="/news"
      className="tap-y relative inline-flex min-h-11 items-center gap-1 text-sm font-semibold text-primary"
      data-testid="story-back"
    >
      <ArrowLeft aria-hidden className="h-4 w-4" />
      {t("stories.story.back")}
    </Link>
  );
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-4" data-testid="story-view">
      {back}
      {!open ? (
        <EmptyState
          icon={<Newspaper aria-hidden className="h-6 w-6" />}
          title={t("stories.story.closed")}
        />
      ) : q.isPending ? (
        <SkeletonCards count={3} />
      ) : q.isError ? (
        q.error instanceof LiveApiError && q.error.status === 404 ? (
          <EmptyState
            icon={<Newspaper aria-hidden className="h-6 w-6" />}
            title={t("stories.story.notFound")}
          />
        ) : (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        )
      ) : (
        <StoryResult data={q.data.data?.story} />
      )}
    </div>
  );
}

/** What the API gave for the story: the story, or why it is not shown. */
export function StoryResult({
  data,
}: {
  data: StoryDetail | { missing_reason: string } | null | undefined;
}) {
  if (!data) {
    return (
      <EmptyState
        icon={<Newspaper aria-hidden className="h-6 w-6" />}
        title={t("stories.story.notFound")}
      />
    );
  }
  if (isMissing(data)) {
    return (
      <div data-testid="story-hidden">
        <EmptyState
          icon={<Newspaper aria-hidden className="h-6 w-6" />}
          title={t(
            data.missing_reason === "retirado_por_derechos"
              ? "stories.story.withdrawn"
              : "stories.story.moderation",
          )}
        />
      </div>
    );
  }
  return <StoryBody story={data as StoryDetail} />;
}
