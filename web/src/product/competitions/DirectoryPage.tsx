/**
 * The world directory of competitions (plan PM, PM-09-05; UX-179; lámina I08): what PrediGol follows and how much data each one
 * offers. Every competition shows its coverage level (C-16's directory summary: the only screen that reads it) and, when PrediGol
 * gives it more attention, «Destacada» (its editorial priority, P0 or P1, C-16 1.2.0). The two signals are explained on the page:
 * the level measures the data that arrived this season, not the quality of the league. Grouped by region; a search by name or
 * country, chips by level with their counts, «Solo destacadas» and «Las que sigo». Each row opens the competition's page when it
 * is open, its matches otherwise.
 *
 * Shown only while `FBI_COMPETITION_DIRECTORY` is on; without C-16 (`FBI_AVAILABILITY` off) it says the levels are not published.
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ChevronRight, Pin, Search, Star } from "lucide-react";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { live } from "@/lib/api/v1/queries";
import type { CoverageLevel } from "@/lib/api/v1/types_availability";
import { useAuth, usePmReaderSwitches } from "@/lib/auth/AuthProvider";
import { cn } from "@/lib/utils";
import { countryLabel } from "@/product/matches/country";
import { LevelBadge } from "@/product/shared/CoverageLevel";
import { Card, EmptyState, ErrorState, PageTitle, SkeletonCards } from "@/product/shared/States";
import { competitionApi } from "./api";
import {
  byRegion,
  countryCount,
  directoryEntries,
  filterEntries,
  LEVELS,
  levelCounts,
  NO_FILTER,
  type DirectoryEntry,
  type DirectoryFilter,
  type RegionGroup,
} from "./directory";
import { t } from "./text";

const SHOWN = 6;

const CHIP =
  "inline-flex min-h-11 items-center gap-2 rounded-full border px-4 text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring";

function Chip({
  on,
  onClick,
  children,
  testId,
}: {
  on: boolean;
  onClick: () => void;
  children: React.ReactNode;
  testId?: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      data-testid={testId}
      className={cn(
        CHIP,
        on
          ? "border-primary/50 bg-primary-soft text-primary"
          : "border-border bg-card text-foreground-soft hover:border-border-strong",
      )}
    >
      {children}
    </button>
  );
}

function entryCountry(e: DirectoryEntry): string {
  return countryLabel(e.country, e.countryCode) ?? t("competitions.world");
}

function Row({ e, page }: { e: DirectoryEntry; page: boolean }) {
  const kind = ["cup", "supercup", "friendly"].includes(e.type) ? e.type : "league";
  const body = (
    <>
      <LevelBadge level={e.level} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-semibold">{e.name}</span>
        <span className="block truncate text-caption text-muted-foreground">
          {entryCountry(e)} · {t(`competitions.type.${kind}`).toLowerCase()}
        </span>
      </span>
      {e.featured ? (
        <StatusBadge tone="gold" dot={false}>
          <Pin aria-hidden className="h-3 w-3" />
          {t("competitions.directory.featured")}
        </StatusBadge>
      ) : null}
      <ChevronRight aria-hidden className="h-4 w-4 shrink-0 text-subtle-foreground" />
    </>
  );
  const cls = "flex min-h-14 items-center gap-3 px-4 py-2 hover:bg-elevated";
  return (
    <li data-testid="directory-row" data-level={e.level} data-featured={e.featured}>
      {page ? (
        <Link
          to="/competitions/$competitionId"
          params={{ competitionId: String(e.id) }}
          className={cls}
        >
          {body}
        </Link>
      ) : (
        <Link to="/matches" search={{ competition: e.id }} className={cls}>
          {body}
        </Link>
      )}
    </li>
  );
}

function RegionSection({
  group,
  page,
  open,
  onOpen,
}: {
  group: RegionGroup;
  page: boolean;
  open: boolean;
  onOpen: () => void;
}) {
  const title = t(`competitions.directory.region.${group.region}`);
  const shown = open ? group.entries : group.entries.slice(0, SHOWN);
  return (
    <section
      aria-labelledby={`region-${group.region}`}
      className="space-y-2"
      data-testid={`region-${group.region}`}
    >
      <div className="flex items-baseline justify-between gap-3">
        <h2 id={`region-${group.region}`} className="text-title">
          {title}
        </h2>
        <span className="numeric text-caption text-muted-foreground">
          {t("competitions.directory.count", { n: group.entries.length })}
        </span>
      </div>
      <ul className="card-surface divide-y divide-border rounded-card">
        {shown.map((e) => (
          <Row key={e.id} e={e} page={page} />
        ))}
      </ul>
      {!open && group.entries.length > SHOWN ? (
        <button
          type="button"
          onClick={onOpen}
          className="inline-flex min-h-11 items-center gap-1 text-sm font-semibold text-primary hover:underline"
        >
          {t("competitions.directory.seeAll", { n: group.entries.length, region: title })}
          <ChevronRight aria-hidden className="h-4 w-4" />
        </button>
      ) : null}
    </section>
  );
}

/** How to read the two signals: the editorial priority and the coverage level (what each level offers). */
function Legend() {
  return (
    <section aria-labelledby="directory-legend" className="space-y-2">
      <h2 id="directory-legend" className="text-overline text-subtle-foreground">
        {t("competitions.directory.legendTitle")}
      </h2>
      <Card as="div" className="space-y-3 p-4">
        <p className="flex items-start gap-2 text-small">
          <Pin aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-gold-strong" />
          <span>
            <strong>{t("competitions.directory.featured")}:</strong>{" "}
            {t("competitions.directory.featuredMeaning")}
          </span>
        </p>
        <ul className="space-y-2 border-t border-border pt-3">
          {(["A", "B", "C", "D"] as const).map((l) => (
            <li key={l} className="flex items-start gap-3 text-small">
              <LevelBadge level={l} />
              <span className="text-foreground-soft">
                {t(`competitions.directory.offers.${l}`)}
              </span>
            </li>
          ))}
        </ul>
      </Card>
    </section>
  );
}

export function DirectoryView({
  entries,
  mine,
  page,
}: {
  entries: readonly DirectoryEntry[];
  mine: ReadonlySet<number>;
  page: boolean;
}) {
  const [filter, setFilter] = useState<DirectoryFilter>(NO_FILTER);
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const set = (patch: Partial<DirectoryFilter>) => setFilter((f) => ({ ...f, ...patch }));
  const beforeLevel = filterEntries(entries, { ...filter, level: "all" }, mine, entryCountry);
  const counts = levelCounts(beforeLevel);
  const shown = filterEntries(entries, filter, mine, entryCountry);
  const groups = byRegion(shown);
  const searching = filter.query.trim().length > 0;
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-5" data-testid="directory-page">
      <PageTitle
        title={t("competitions.directory.title")}
        subtitle={t("competitions.directory.subtitle", {
          n: entries.length,
          countries: countryCount(entries),
        })}
      />
      <label className="relative block">
        <span className="sr-only">{t("competitions.directory.search")}</span>
        <Search
          aria-hidden
          className="pointer-events-none absolute left-3.5 top-1/2 h-5 w-5 -translate-y-1/2 text-subtle-foreground"
        />
        <input
          type="search"
          value={filter.query}
          onChange={(ev) => set({ query: ev.target.value })}
          placeholder={t("competitions.directory.search")}
          className="h-12 w-full rounded-field border border-border bg-card pl-11 pr-4 text-base placeholder:text-subtle-foreground focus:border-border-strong focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          data-testid="directory-search"
        />
      </label>
      <div
        className="flex flex-wrap gap-2"
        role="group"
        aria-label={t("competitions.directory.levelsLabel")}
      >
        <Chip on={filter.level === "all"} onClick={() => set({ level: "all" })} testId="level-all">
          {t("competitions.directory.all")}
          <span className="numeric text-caption">{counts.all}</span>
        </Chip>
        {LEVELS.filter((l) => l !== "MI" || counts.MI > 0).map((l: CoverageLevel) => (
          <Chip
            key={l}
            on={filter.level === l}
            onClick={() => set({ level: filter.level === l ? "all" : l })}
            testId={`level-${l}`}
          >
            {l === "MI" ? t("competitions.directory.thin") : l}
            <span className="numeric text-caption">{counts[l]}</span>
          </Chip>
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        <Chip
          on={filter.featured}
          onClick={() => set({ featured: !filter.featured })}
          testId="only-featured"
        >
          <Pin aria-hidden className="h-4 w-4" />
          {t("competitions.directory.onlyFeatured")}
        </Chip>
        {mine.size > 0 ? (
          <Chip on={filter.mine} onClick={() => set({ mine: !filter.mine })} testId="only-mine">
            <Star aria-hidden className="h-4 w-4" />
            {t("competitions.directory.onlyMine")}
          </Chip>
        ) : null}
      </div>
      <Legend />
      {groups.length === 0 ? (
        <Card className="p-4">
          <EmptyState
            title={t("competitions.directory.none")}
            action={
              <button
                type="button"
                onClick={() => setFilter(NO_FILTER)}
                className="min-h-11 text-sm font-semibold text-primary hover:underline"
              >
                {t("competitions.directory.clear")}
              </button>
            }
          />
        </Card>
      ) : (
        groups.map((g) => (
          <RegionSection
            key={g.region}
            group={g}
            page={page}
            open={searching || open.has(g.region)}
            onOpen={() => setOpen((s) => new Set([...s, g.region]))}
          />
        ))
      )}
      <p className="text-caption text-muted-foreground">{t("competitions.directory.note")}</p>
    </div>
  );
}

export function DirectoryPage() {
  const auth = useAuth();
  const { directory: on, competitionPage } = usePmReaderSwitches();
  const availabilityOn = auth.user?.availability === true;
  const reader = auth.user?.role === "USER";
  const levels = useQuery({
    ...competitionApi.directory,
    enabled: on && availabilityOn,
    retry: false,
  });
  const catalogue = useQuery({ ...live.competitions, enabled: on });
  const favorites = useQuery({ ...live.favorites, enabled: on && reader });
  const entries = useMemo(
    () => directoryEntries(levels.data?.data.competitions ?? [], catalogue.data?.data ?? []),
    [levels.data, catalogue.data],
  );
  const mine = useMemo(
    () =>
      new Set(
        favorites.data && !favorites.data.suggested ? favorites.data.leagues.map((l) => l.id) : [],
      ),
    [favorites.data],
  );
  if (!on || !availabilityOn)
    return (
      <Card className="p-4">
        <EmptyState
          title={t("competitions.directory.closed")}
          body={on ? t("competitions.directory.noLevels") : undefined}
        />
      </Card>
    );
  if (levels.isPending || catalogue.isPending) return <SkeletonCards count={3} />;
  if (levels.isError)
    return <ErrorState error={levels.error} onRetry={() => void levels.refetch()} />;
  return <DirectoryView entries={entries} mine={mine} page={competitionPage} />;
}
