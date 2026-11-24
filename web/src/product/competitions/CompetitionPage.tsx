/**
 * A competition's page (plan PM, PM-09-04; UX-178; lámina I07): its tables, its calendar and results, its leaders and the level of
 * what PrediGol has of it. Built from routes readers already have - the competition (`/competitions/{id}`), its tables by stage
 * (`/standings`), the provider's leaders and rounds (`/reference`), its matches (`/matches?competition_id=`) - and, where they are on,
 * C-16 (`FBI_AVAILABILITY`: the level and what each tab may show) and the season tables computed from the regulation (BE-082,
 * `FBI_COMPETITION_TABLES`). Each tab is shown by the level of its own data (`model.ts`): a competition at level D shows only its
 * calendar and results, and says once what it does not offer.
 *
 * Shown only while `FBI_COMPETITION_PAGE` is on. Nothing here is a forecast; «Qué se juega» waits for its signature (DM-14).
 */
import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { CalendarDays, ChevronRight, ListOrdered, ShieldCheck, Trophy } from "lucide-react";
import { Segmented } from "@/components/ui/segmented";
import { TeamName } from "@/components/football/Logos";
import { LiveApiError } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type { CompetitionAvailability } from "@/lib/api/v1/types_availability";
import type {
  CompetitionReference,
  CompetitionTable,
  LeaderListName,
} from "@/lib/api/v1/types_center";
import type { MatchSummary } from "@/lib/api/v1/types";
import { useAuth, usePmReaderSwitches } from "@/lib/auth/AuthProvider";
import { formatKickoff } from "@/lib/time";
import { FullTable } from "@/product/shared/StandingsTable";
import { countryLabel } from "@/product/matches/country";
import { CoverageChip, LevelBadge } from "@/product/shared/CoverageLevel";
import { EntityHeader } from "@/product/shared/intelligence/Pieces";
import { NotOffered } from "@/product/shared/Unavailable";
import { leaderFigure } from "@/product/shared/reference";
import { defaultSection, tableSections } from "@/product/shared/standings";
import { Card, EmptyState, ErrorState, SkeletonCards } from "@/product/shared/States";
import {
  chosenTab,
  competitionModules,
  FAMILY_ORDER,
  familyLevel,
  type CompetitionTab,
} from "./model";
import { competitionApi } from "./api";
import { SeasonTablesBlock } from "./SeasonTables";
import { WhatIf } from "./WhatIf";
import { t } from "./text";

const NO_TEAMS: ReadonlySet<number> = new Set();

function Block({
  title,
  icon,
  children,
  testId,
}: {
  title: string;
  icon?: ReactNode;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <Card className="space-y-3 p-4 sm:p-5" data-testid={testId}>
      <h2 className="flex items-center gap-2 text-subheading">
        {icon ? <span className="text-subtle-foreground">{icon}</span> : null}
        {title}
      </h2>
      {children}
    </Card>
  );
}

// ── the tables ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

export function ProviderTables({ table }: { table: CompetitionTable }) {
  const sections = tableSections(table);
  const [chosen, setChosen] = useState<string | null>(null);
  const id = chosen ?? defaultSection(sections);
  const section = sections.find((s) => s.id === id) ?? sections[0];
  if (!section)
    return <p className="text-sm text-muted-foreground">{t("competitions.table.none")}</p>;
  return (
    <div className="space-y-3" data-testid="provider-tables">
      {sections.length > 1 ? (
        <div className="-mx-1 overflow-x-auto px-1 [scrollbar-width:none]">
          <Segmented<string>
            full={false}
            className="min-w-max"
            value={section.id}
            onChange={setChosen}
            label={t("competitions.table.stage")}
            testId="table-stages"
            options={sections.map((s) => ({
              value: s.id,
              label: s.stage ?? s.tables[0]?.label ?? t("competitions.table.other"),
            }))}
          />
        </div>
      ) : null}
      {section.tables.map((tb) => (
        <div key={tb.key} className="space-y-1">
          {section.tables.length > 1 ? (
            <p className="text-caption font-medium text-muted-foreground">{tb.label}</p>
          ) : null}
          <FullTable rows={tb.rows} mine={NO_TEAMS} label={tb.label} />
        </div>
      ))}
      <p className="text-caption text-subtle-foreground">{t("competitions.table.source")}</p>
    </div>
  );
}

function TableTab({ id, season }: { id: string; season: number | undefined }) {
  const { competitionTables, whatIf } = usePmReaderSwitches();
  const standings = useQuery(live.standings(id));
  const tables = useQuery({
    ...competitionApi.seasonTables(id, season),
    enabled: competitionTables,
  });
  const computed = tables.data?.status === "ok" ? tables.data.data : null;
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:items-start">
      {competitionTables && tables.isPending ? (
        // the computed tables arrive after the provider's: their place is kept so the page does not jump (CLS, PM-15-02)
        <Card className="p-4 sm:p-5">
          <SkeletonCards count={6} />
        </Card>
      ) : null}
      {computed ? (
        <Card className="p-4 sm:p-5">
          <SeasonTablesBlock data={computed}>
            {/* plan PM, PM-09-03 (UX-181): the reader's own calculation, behind FBI_WHAT_IF (DM-14) */}
            {(table, places) =>
              whatIf && !places ? <WhatIf key={table.key} data={computed} table={table} /> : null
            }
          </SeasonTablesBlock>
        </Card>
      ) : null}
      <Block title={t("competitions.table.title")} icon={<ListOrdered className="h-4 w-4" />}>
        {standings.isPending ? (
          <SkeletonCards count={1} />
        ) : standings.data?.data ? (
          <ProviderTables table={standings.data.data} />
        ) : (
          <p className="text-sm text-muted-foreground">
            {standings.data?.reason ?? t("competitions.table.none")}
          </p>
        )}
      </Block>
    </div>
  );
}

// ── the calendar and the results ────────────────────────────────────────────────────────────────────────────────────────────

export function MatchItem({ m }: { m: MatchSummary }) {
  return (
    <Link
      to="/matches/$fixtureId"
      params={{ fixtureId: String(m.id) }}
      className="flex min-h-12 items-center gap-3 py-2 hover:text-primary"
      data-testid="competition-match"
    >
      <span className="numeric w-24 shrink-0 text-caption text-muted-foreground">
        {formatKickoff(m.kickoff_at)}
        {m.round ? <span className="block truncate text-subtle-foreground">{m.round}</span> : null}
      </span>
      <span className="min-w-0 flex-1 space-y-0.5 text-sm">
        <TeamName name={m.home.name} logo={m.home.logo_url} size={18} wrap />
        <TeamName name={m.away.name} logo={m.away.logo_url} size={18} wrap />
      </span>
      {m.score ? (
        <span className="numeric flex shrink-0 flex-col items-end text-sm font-semibold">
          <span>{m.score.home}</span>
          <span>{m.score.away}</span>
        </span>
      ) : null}
      <ChevronRight aria-hidden className="h-4 w-4 shrink-0 text-subtle-foreground" />
    </Link>
  );
}

function MatchList({ query, empty }: { query: ReturnType<typeof useMatchesOf>; empty: string }) {
  if (query.isPending) return <SkeletonCards count={2} />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  const rows = query.data?.data ?? [];
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">{empty}</p>;
  return (
    <div className="divide-y divide-border">
      {rows.map((m) => (
        <MatchItem key={m.id} m={m} />
      ))}
    </div>
  );
}

function useMatchesOf(id: number, status: "scheduled" | "finished") {
  return useQuery(
    live.matches({
      competition_id: id,
      status,
      order: status === "scheduled" ? "asc" : "desc",
      limit: 20,
    }),
  );
}

function CalendarTab({ id, reference }: { id: number; reference: CompetitionReference | null }) {
  const upcoming = useMatchesOf(id, "scheduled");
  const results = useMatchesOf(id, "finished");
  const current = reference?.current_rounds ?? [];
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Block
        title={t("competitions.calendar.upcoming")}
        icon={<CalendarDays className="h-4 w-4" />}
      >
        {current.length > 0 ? (
          <p className="text-caption text-muted-foreground">
            {t("competitions.calendar.current", { rounds: current.join(" · ") })}
          </p>
        ) : null}
        <MatchList query={upcoming} empty={t("competitions.calendar.upcomingNone")} />
      </Block>
      <Block title={t("competitions.calendar.results")} icon={<CalendarDays className="h-4 w-4" />}>
        <MatchList query={results} empty={t("competitions.calendar.resultsNone")} />
      </Block>
    </div>
  );
}

// ── the leaders ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

const LEADER_KINDS: readonly LeaderListName[] = [
  "topscorers",
  "topassists",
  "topyellowcards",
  "topredcards",
];

export function LeadersTab({ reference }: { reference: CompetitionReference }) {
  const lists = reference.leaders.status === "ok" ? reference.leaders.data : [];
  const kinds = LEADER_KINDS.filter((k) => lists.some((l) => l.kind === k && l.rows.length > 0));
  const [kind, setKind] = useState<LeaderListName | null>(null);
  const shown = lists.find((l) => l.kind === (kind ?? kinds[0]));
  if (!shown)
    return (
      <Card className="p-4">
        <EmptyState title={t("competitions.leaders.none")} />
      </Card>
    );
  return (
    <Block
      title={t("competitions.leaders.title")}
      icon={<Trophy className="h-4 w-4" />}
      testId="competition-leaders"
    >
      {kinds.length > 1 ? (
        <div className="-mx-1 overflow-x-auto px-1 [scrollbar-width:none]">
          <Segmented<LeaderListName>
            full={false}
            className="min-w-max"
            value={shown.kind}
            onChange={setKind}
            label={t("competitions.leaders.choose")}
            testId="leader-kinds"
            options={kinds.map((k) => ({ value: k, label: t(`competitions.leaders.kind.${k}`) }))}
          />
        </div>
      ) : null}
      <ol className="divide-y divide-border">
        {shown.rows.slice(0, 10).map((r) => {
          const who = (
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-semibold">{r.name ?? "—"}</span>
              {r.team ? (
                <span className="block truncate text-caption text-muted-foreground">{r.team}</span>
              ) : null}
            </span>
          );
          return (
            <li
              key={`${r.rank}-${r.provider_player_id}`}
              className="flex min-h-12 items-center gap-3 py-1.5"
            >
              <span className="numeric w-6 shrink-0 text-caption text-muted-foreground">
                {r.rank}
              </span>
              {r.player_id !== null ? (
                <Link
                  to="/players/$playerId"
                  params={{ playerId: String(r.player_id) }}
                  className="flex min-w-0 flex-1 items-center hover:text-primary"
                >
                  {who}
                </Link>
              ) : (
                who
              )}
              <span className="numeric shrink-0 text-base font-bold">
                {leaderFigure(shown.kind, r) ?? "—"}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="text-caption text-subtle-foreground">{t("competitions.leaders.source")}</p>
    </Block>
  );
}

// ── the coverage ────────────────────────────────────────────────────────────────────────────────────────────────────────────

export function CoverageTab({ availability }: { availability: CompetitionAvailability }) {
  return (
    <Block
      title={t("competitions.coverage.title")}
      icon={<ShieldCheck className="h-4 w-4" />}
      testId="competition-coverage"
    >
      <p className="text-small text-muted-foreground">{t("competitions.coverage.intro")}</p>
      <ul className="divide-y divide-border">
        {FAMILY_ORDER.map((f) => {
          const level = familyLevel(availability, f);
          return (
            <li key={f} className="flex min-h-12 items-center gap-3 py-2">
              {level ? <LevelBadge level={level} /> : <span className="w-8" />}
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-semibold">
                  {t(`competitions.coverage.family.${f}`)}
                </span>
                <span className="block text-caption text-muted-foreground">
                  {level
                    ? t(`competitions.coverage.meaning.${level}`)
                    : t("competitions.coverage.unmeasured")}
                </span>
              </span>
            </li>
          );
        })}
      </ul>
      <p className="text-caption text-subtle-foreground">{t("competitions.coverage.note")}</p>
    </Block>
  );
}

// ── the page ────────────────────────────────────────────────────────────────────────────────────────────────────────────────

/** league, cup, supercup or friendly (core.competitions.type); anything else reads as a league. */
export function competitionKind(type: string): "league" | "cup" | "supercup" | "friendly" {
  return type === "cup" || type === "supercup" || type === "friendly" ? type : "league";
}

function missing(error: unknown): boolean {
  return error instanceof LiveApiError && error.status === 404;
}

export function CompetitionPage({ competitionId }: { competitionId: string }) {
  const auth = useAuth();
  const { competitionPage } = usePmReaderSwitches();
  const availabilityOn = auth.user?.availability === true;
  const search = useSearch({ strict: false }) as { tab?: string };
  const navigate = useNavigate();
  const detail = useQuery({ ...live.competition(competitionId), enabled: competitionPage });
  const standings = useQuery({ ...live.standings(competitionId), enabled: competitionPage });
  const reference = useQuery({
    ...live.competitionReference(competitionId),
    enabled: competitionPage,
  });
  const coverage = useQuery({
    ...competitionApi.availability(competitionId),
    enabled: competitionPage && availabilityOn,
    retry: false,
  });
  if (!competitionPage)
    return (
      <Card className="p-4">
        <EmptyState title={t("competitions.closed")} />
      </Card>
    );
  if (detail.isPending) return <SkeletonCards count={3} />;
  if (detail.isError)
    return (
      <Card className={missing(detail.error) ? "p-4" : undefined}>
        {missing(detail.error) ? (
          <EmptyState title={t("competitions.missing")} />
        ) : (
          <ErrorState error={detail.error} onRetry={() => void detail.refetch()} />
        )}
      </Card>
    );
  const c = detail.data.data.competition;
  const ref = reference.data?.data ?? null;
  const availability = coverage.data?.data.competitions[0] ?? null;
  const hasLeaders =
    !!ref && ref.leaders.status === "ok" && ref.leaders.data.some((l) => l.rows.length > 0);
  const hasTable = !!standings.data?.data || auth.user?.competition_tables === true;
  const modules = competitionModules(availability, { table: hasTable, leaders: hasLeaders });
  const tab = chosenTab(search.tab, modules.tabs);
  const facts = [
    countryLabel(c.country, c.country_code) ?? t("competitions.world"),
    t(`competitions.type.${competitionKind(c.type)}`),
    c.current_season ? t("competitions.season", { season: c.current_season }) : null,
  ].filter((x): x is string => Boolean(x));
  return (
    <div
      className="mx-auto flex w-full max-w-6xl flex-col gap-5"
      data-testid="competition-page"
      data-tab={tab}
    >
      <EntityHeader kind="competition" name={c.name} logo={c.logo_url} facts={facts} />
      {modules.level ? (
        <div className="-mt-2 flex flex-wrap items-center gap-2">
          <CoverageChip level={modules.level} label={modules.label ?? undefined} />
        </div>
      ) : null}
      <div className="-mx-1 overflow-x-auto px-1 [scrollbar-width:none]">
        <Segmented<CompetitionTab>
          full={false}
          className="min-w-max"
          value={tab}
          onChange={(v) => void navigate({ to: ".", search: { tab: v } as never, replace: true })}
          label={t("competitions.tabsLabel")}
          testId="competition-tabs"
          options={modules.tabs.map((v) => ({ value: v, label: t(`competitions.tabs.${v}`) }))}
        />
      </div>
      {modules.notOffered.length > 0 ? (
        <NotOffered subjects={modules.notOffered.map((m) => t(`competitions.notOffered.${m}`))} />
      ) : null}
      {tab === "table" ? (
        <TableTab id={competitionId} season={undefined} />
      ) : tab === "leaders" && ref ? (
        <LeadersTab reference={ref} />
      ) : tab === "coverage" && availability ? (
        <CoverageTab availability={availability} />
      ) : (
        <CalendarTab id={c.id} reference={ref} />
      )}
    </div>
  );
}
