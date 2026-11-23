/**
 * Noticias as stories (plan de correcciones UX, AP-N01 and AP-N03; maquetas 08 and 10; contrato C-06 `portada` and `busqueda`):
 * with an empty address, the front page - the lead, «Última hora», «Tus equipos», the featured ones and the topics with how many
 * stories each has -; with a search or any filter in the address, the search with its facets, the filters applied (each one
 * removable) and the stories that match. Every filter lives in the address. Behind FBI_NEWS_FEED and FBI_NEWS_V2: with either off
 * - or with no stories yet from the server - the page shows the news feed as it was.
 */
import { useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { Newspaper, Search, X } from "lucide-react";
import { Switch } from "@/components/ui/switch";
import { buttonVariants } from "@/components/ui/button";
import { stories } from "./storiesApi";
import { isMissing, present } from "@/lib/api/v1/types_intelligence";
import type { StoryFront } from "@/lib/api/v1/types_stories";
import { useAuth } from "@/lib/auth/AuthProvider";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, PageTitle, SkeletonCards } from "@/product/shared/States";
import { NewsFeedPage } from "./NewsFeedPage";
import { StoryCardView, StoryHitView } from "./StoryCardView";
import { CATEGORY_ORDER, categoryWord, levelWord } from "./stories";
import {
  LEVELS,
  isFront,
  parseStoriesSearch,
  storiesQuery,
  without,
  type StoriesSearchParams,
} from "./storiesSearch";
import { t } from "./storyText";

type Go = (next: StoriesSearchParams) => void;

/** The API's name of an applied filter, to the address' field that holds it. */
const PARAM_OF: Readonly<Record<string, keyof StoriesSearchParams>> = {
  from: "since",
  to: "until",
};
const FILTER_NAME: Readonly<Record<string, string>> = {
  q: "stories.filters.names.q",
  team: "stories.filters.names.team",
  player: "stories.filters.names.player",
  competition: "stories.filters.names.competition",
  country: "stories.filters.names.country",
  from: "stories.filters.names.from",
  to: "stories.filters.names.to",
  category: "stories.filters.names.category",
  level: "stories.filters.names.level",
  mine: "stories.filters.names.mine",
};
const filterName = (name: string): string => (FILTER_NAME[name] ? t(FILTER_NAME[name]) : name);

function Section({
  title,
  testId,
  children,
}: {
  title: string;
  testId: string;
  children: React.ReactNode;
}) {
  return (
    <section aria-label={title} data-testid={testId} className="space-y-2">
      <h2 className="text-subheading">{title}</h2>
      {children}
    </section>
  );
}

export function FrontView({ front, go, now }: { front: StoryFront; go: Go; now?: number }) {
  const lead = present(front.lead_story);
  const total = front.counts.reduce((a, c) => a + c.n, 0);
  const counts = new Map(front.counts.map((c) => [c.category, c.n]));
  const empty = !lead && front.breaking.items.length === 0 && front.featured.items.length === 0;
  if (empty) {
    return (
      <EmptyState
        icon={<Newspaper aria-hidden className="h-6 w-6" />}
        title={t("stories.front.empty", { hours: front.window_hours })}
        body={t("stories.front.emptyBody")}
      />
    );
  }
  return (
    <div className="flex flex-col gap-5" data-testid="stories-front">
      <p className="px-1 text-caption text-muted-foreground">
        {t("stories.front.window", { hours: front.window_hours })}
      </p>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)] lg:items-start">
        {lead ? (
          <Section title={t("stories.front.lead")} testId="stories-lead">
            <ul>
              <StoryCardView card={lead} size="lead" {...(now ? { now } : {})} />
            </ul>
          </Section>
        ) : null}
        <div className="flex min-w-0 flex-col gap-5">
          {front.breaking.items.length > 0 ? (
            <Section title={t("stories.front.breaking")} testId="stories-breaking">
              <ul className="space-y-2">
                {front.breaking.items.map((c) => (
                  <StoryCardView key={c.id} card={c} {...(now ? { now } : {})} />
                ))}
              </ul>
            </Section>
          ) : null}
          <Section title={t("stories.front.mine")} testId="stories-mine">
            {front.mine.items.length > 0 ? (
              <ul className="space-y-2">
                {front.mine.items.map((c) => (
                  <StoryCardView key={c.id} card={c} {...(now ? { now } : {})} />
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">{t("stories.front.mineEmpty")}</p>
            )}
          </Section>
        </div>
      </div>
      {front.featured.items.length > 0 ? (
        <Section title={t("stories.front.featured")} testId="stories-featured">
          <ul className="grid gap-3 lg:grid-cols-2">
            {front.featured.items.map((c) => (
              <StoryCardView key={c.id} card={c} {...(now ? { now } : {})} />
            ))}
          </ul>
        </Section>
      ) : null}
      <Section title={t("stories.front.topics")} testId="stories-topics">
        <div className="flex flex-wrap gap-2">
          {CATEGORY_ORDER.map((c) => {
            const n = counts.get(c) ?? 0;
            return (
              <button
                key={c}
                type="button"
                disabled={n === 0}
                onClick={() => go({ category: c })}
                data-testid={`stories-topic-${c}`}
                className="inline-flex min-h-11 items-center gap-1.5 rounded-full border border-border px-3 text-sm hover:bg-elevated disabled:opacity-50"
              >
                {categoryWord(c)}
                <span className="numeric font-semibold">{n}</span>
              </button>
            );
          })}
          <span className="sr-only">{total}</span>
        </div>
      </Section>
    </div>
  );
}

function Chips({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div role="group" aria-label={label} className="scroll-strip -mx-1 flex gap-2 px-1 py-1">
      {children}
    </div>
  );
}

function Chip({
  active,
  onClick,
  children,
  testId,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  testId: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      data-testid={testId}
      className={cn(
        "inline-flex min-h-11 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-3.5 text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
        active
          ? "border-primary/40 bg-primary-soft text-primary"
          : "border-transparent bg-elevated text-foreground-soft hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

export function SearchView({ search, go }: { search: StoriesSearchParams; go: Go }) {
  const q = useInfiniteQuery({
    queryKey: ["v1", "stories", "search", search],
    queryFn: ({ pageParam }) => stories.news(storiesQuery(search, pageParam)),
    initialPageParam: 0,
    getNextPageParam: (last) => last.data?.search?.next_offset ?? undefined,
  });
  const first = q.data?.pages[0]?.data?.search ?? null;
  const results = (q.data?.pages ?? []).flatMap((p) => p.data?.search?.results.items ?? []);
  const facetCategory = new Map((first?.facets.category ?? []).map((f) => [f.code, f.n]));
  const facetLevel = new Map((first?.facets.level ?? []).map((f) => [f.code, f.n]));
  const applied = first?.filters_applied ?? [];
  return (
    <div className="flex flex-col gap-3" data-testid="stories-search">
      <Chips label={t("stories.filters.category")}>
        <Chip
          active={!search.category}
          onClick={() => go(without(search, "category"))}
          testId="stories-category-all"
        >
          {t("stories.filters.all")}
        </Chip>
        {CATEGORY_ORDER.map((c) => (
          <Chip
            key={c}
            active={search.category === c}
            onClick={() => go({ ...search, category: c })}
            testId={`stories-category-${c}`}
          >
            {categoryWord(c)}
            {facetCategory.has(c) ? (
              <span className="numeric text-xs opacity-80">{facetCategory.get(c)}</span>
            ) : null}
          </Chip>
        ))}
      </Chips>
      <Chips label={t("stories.filters.level")}>
        <Chip
          active={!search.level}
          onClick={() => go(without(search, "level"))}
          testId="stories-level-all"
        >
          {t("stories.filters.all")}
        </Chip>
        {LEVELS.map((l) => (
          <Chip
            key={l}
            active={search.level === l}
            onClick={() => go({ ...search, level: l })}
            testId={`stories-level-${l}`}
          >
            {levelWord(l)}
            {facetLevel.has(l) ? (
              <span className="numeric text-xs opacity-80">{facetLevel.get(l)}</span>
            ) : null}
          </Chip>
        ))}
      </Chips>
      <div className="flex flex-wrap items-center justify-between gap-3 px-1">
        <label className="flex min-h-11 items-center gap-3">
          <span className="text-sm font-medium">{t("stories.filters.mine")}</span>
          <Switch
            checked={search.mine === true}
            onCheckedChange={(on) => go(on ? { ...search, mine: true } : without(search, "mine"))}
            data-testid="stories-mine-switch"
          />
        </label>
        <label className="flex min-h-11 items-center gap-2 text-sm">
          <span className="font-medium">{t("stories.filters.sort")}</span>
          <select
            value={search.sort ?? "reciente"}
            onChange={(e) =>
              go({ ...search, sort: e.target.value === "relevante" ? "relevante" : "reciente" })
            }
            data-testid="stories-sort"
            className="h-11 rounded-field border border-border bg-card px-2"
          >
            <option value="reciente">{t("stories.sort.reciente")}</option>
            <option value="relevante">{t("stories.sort.relevante")}</option>
          </select>
        </label>
      </div>
      <div className="flex flex-wrap items-center gap-3 px-1">
        <label className="flex min-h-11 items-center gap-2 text-sm">
          <span>{t("stories.filters.since")}</span>
          <input
            type="date"
            value={search.since ?? ""}
            max={search.until ?? ""}
            onChange={(e) =>
              go(e.target.value ? { ...search, since: e.target.value } : without(search, "since"))
            }
            data-testid="stories-since"
            className="h-11 rounded-field border border-border bg-card px-2"
          />
        </label>
        <label className="flex min-h-11 items-center gap-2 text-sm">
          <span>{t("stories.filters.until")}</span>
          <input
            type="date"
            value={search.until ?? ""}
            min={search.since ?? ""}
            onChange={(e) =>
              go(e.target.value ? { ...search, until: e.target.value } : without(search, "until"))
            }
            data-testid="stories-until"
            className="h-11 rounded-field border border-border bg-card px-2"
          />
        </label>
      </div>
      {applied.length > 0 ? (
        <ul
          aria-label={t("stories.filters.applied")}
          className="flex flex-wrap gap-2 px-1"
          data-testid="stories-applied"
        >
          {applied.map((f) => {
            const key = PARAM_OF[f.name] ?? (f.name as keyof StoriesSearchParams);
            const name = filterName(f.name);
            return (
              <li key={`${f.name}-${f.value}`}>
                <button
                  type="button"
                  onClick={() => go(without(search, key))}
                  aria-label={t("stories.filters.remove", { name })}
                  className="inline-flex min-h-11 items-center gap-1 rounded-full border border-border px-3 text-sm hover:bg-elevated"
                >
                  {name}: {f.value}
                  <X aria-hidden className="h-3.5 w-3.5" />
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
      {first && first.normalized && first.normalized !== first.query ? (
        <p className="px-1 text-caption text-muted-foreground">
          {t("stories.search.did", { normalized: first.normalized })}
        </p>
      ) : null}
      {q.isPending ? (
        <SkeletonCards count={3} />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : results.length === 0 ? (
        <EmptyState
          icon={<Newspaper aria-hidden className="h-6 w-6" />}
          title={t("stories.results.none")}
          body={t("stories.results.noneBody")}
          action={
            <button
              type="button"
              onClick={() => go({})}
              className={buttonVariants({ variant: "secondary" })}
            >
              {t("stories.filters.clear")}
            </button>
          }
        />
      ) : (
        <>
          <p
            className="numeric px-1 text-sm text-muted-foreground"
            aria-live="polite"
            data-testid="stories-total"
          >
            {t("stories.results.total", { count: first?.total ?? results.length })}
          </p>
          <ul className="space-y-2" data-testid="stories-results">
            {results.map((h) => (
              <StoryHitView key={h.story_id} hit={h} />
            ))}
          </ul>
          {q.hasNextPage ? (
            <button
              type="button"
              onClick={() => void q.fetchNextPage()}
              disabled={q.isFetchingNextPage}
              data-testid="stories-more"
              className={buttonVariants({ variant: "secondary", block: true })}
            >
              {t("stories.results.more")}
            </button>
          ) : null}
        </>
      )}
    </div>
  );
}

function SearchBox({ search, go }: { search: StoriesSearchParams; go: Go }) {
  const [text, setText] = useState(search.q ?? "");
  return (
    <form
      role="search"
      aria-label={t("stories.search.label")}
      onSubmit={(e) => {
        e.preventDefault();
        const v = text.trim();
        go(v ? { ...search, q: v } : without(search, "q"));
      }}
      className="flex gap-2"
      data-testid="stories-searchbox"
    >
      <label className="relative min-w-0 flex-1">
        <span className="sr-only">{t("stories.search.label")}</span>
        <Search
          aria-hidden
          className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-subtle-foreground"
        />
        <input
          type="search"
          value={text}
          maxLength={120}
          onChange={(e) => setText(e.target.value)}
          placeholder={t("stories.search.placeholder")}
          className="h-11 w-full rounded-field border border-border bg-card pl-9 pr-3 text-sm"
        />
      </label>
      <button type="submit" className={buttonVariants({ variant: "primary" })}>
        {t("stories.search.submit")}
      </button>
      {search.q ? (
        <button
          type="button"
          onClick={() => {
            setText("");
            go(without(search, "q"));
          }}
          aria-label={t("stories.search.clear")}
          className={buttonVariants({ variant: "secondary" })}
        >
          <X aria-hidden className="h-4 w-4" />
        </button>
      ) : null}
    </form>
  );
}

/** The page: stories when the owner's two switches are on and the server has any; the news feed as it was when not. */
export function StoriesPage({ search: raw }: { search: StoriesSearchParams }) {
  const search = parseStoriesSearch({ ...raw });
  const user = useAuth().user;
  const on = user?.news_feed === true && user?.news_v2 === true;
  const navigate = useNavigate({ from: "/news/" });
  const go: Go = (next) => void navigate({ search: next as never });
  const front = useQuery({
    queryKey: ["v1", "stories", "front"],
    queryFn: () => stories.news(),
    enabled: on && isFront(search),
    refetchInterval: 5 * 60_000,
    retry: false,
  });
  if (!on) return <NewsFeedPage />;
  const frontData = front.data?.data?.front;
  // the server has no stories (the answer is empty, or it does not know the route yet): the feed as it was
  if (
    isFront(search) &&
    !front.isPending &&
    (front.isError || !frontData || isMissing(frontData))
  ) {
    return <NewsFeedPage />;
  }
  return (
    <div
      className="mx-auto flex w-full max-w-2xl flex-col gap-4 lg:max-w-6xl"
      data-testid="stories-page"
    >
      <PageTitle title={t("stories.title")} subtitle={t("stories.subtitle")} />
      <SearchBox key={search.q ?? ""} search={search} go={go} />
      {isFront(search) ? (
        front.isPending ? (
          <SkeletonCards count={3} />
        ) : frontData && !isMissing(frontData) ? (
          <FrontView front={frontData} go={go} />
        ) : null
      ) : (
        <SearchView search={search} go={go} />
      )}
      {!isFront(search) ? (
        <Link
          to="/news"
          search={{} as never}
          className="tap-y relative inline-flex min-h-11 items-center text-sm font-semibold text-primary"
        >
          {t("stories.filters.clear")}
        </Link>
      ) : null}
    </div>
  );
}
