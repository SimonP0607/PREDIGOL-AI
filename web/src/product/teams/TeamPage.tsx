/**
 * The profile of a club or a national team (plan maestro unificado, UX-154 and UX-155; maquetas 11 and 12), the part that
 * needs no new contract: the head (crest, country, stadium, follow), the next match, the last results, the league table
 * around the team, the matches before and after, the squad of the last 30 days and the record per competition. What the
 * profile contract (C-09) will bring - «Qué se juega», novedades, bajas with their source and date, the news of the team,
 * the trophies - is not drawn until it arrives: each place says so instead of being filled.
 *
 * Shown only while FBI_PROFILES is on (`/auth/me`): the API behind it is already the product's.
 */
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { CalendarDays, ChevronRight, ListOrdered, Newspaper, Users } from "lucide-react";
import { live } from "@/lib/api/v1/queries";
import { LiveApiError } from "@/lib/api/v1/client";
import type { MatchSummary, TeamDetail, TeamRecord } from "@/lib/api/v1/types";
import { useAuth, useStatsSwitches } from "@/lib/auth/AuthProvider";
import { t } from "@/lib/i18n";
import { formatKickoff } from "@/lib/time";
import { cn } from "@/lib/utils";
import { Segmented } from "@/components/ui/segmented";
import { TeamName } from "@/components/football/Logos";
import { FollowStar } from "@/product/favorites/FollowStar";
import { EntityHeader } from "@/product/shared/intelligence/Pieces";
import { TeamStatsHub } from "./stats/TeamStatsHub";
import { Card, EmptyState, ErrorState, SkeletonCards } from "@/product/shared/States";
import {
  excerpt,
  formOf,
  countryName,
  isNation,
  PROFILE_TABS,
  squadGroups,
  tableCompetition,
  teamLabel,
  type FormItem,
  type ProfileTab,
} from "./model";

const RESULT_TONE: Record<FormItem["result"], string> = {
  W: "bg-positive-soft text-positive",
  D: "bg-elevated text-muted-foreground",
  L: "bg-negative-soft text-negative",
};

function Block({
  title,
  icon,
  children,
  testId,
}: {
  title: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
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

function MatchLine({ m, teamId }: { m: MatchSummary; teamId: number }) {
  const home = m.home.id === teamId;
  const rival = home ? m.away : m.home;
  return (
    <Link
      to="/matches/$fixtureId"
      params={{ fixtureId: String(m.id) }}
      className="flex min-h-12 items-center gap-3 py-2 hover:text-primary"
      data-testid="profile-match"
    >
      <span className="numeric w-24 shrink-0 text-caption text-muted-foreground">
        {formatKickoff(m.kickoff_at)}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2 text-sm font-semibold">
          <span className="text-caption font-normal text-subtle-foreground">
            {home ? t("profiles.vsHome") : t("profiles.vsAway")}
          </span>
          <TeamName name={rival.name} logo={rival.logo_url} size={18} />
        </span>
        <span className="block truncate text-caption text-muted-foreground">
          {m.competition.name}
        </span>
      </span>
      {m.score ? (
        <span className="numeric shrink-0 text-sm font-semibold">
          {home ? `${m.score.home}–${m.score.away}` : `${m.score.away}–${m.score.home}`}
        </span>
      ) : null}
      <ChevronRight aria-hidden className="h-4 w-4 shrink-0 text-subtle-foreground" />
    </Link>
  );
}

function FormStrip({ items }: { items: FormItem[] }) {
  if (items.length === 0)
    return <p className="text-sm text-muted-foreground">{t("profiles.formNone")}</p>;
  return (
    <ol className="flex flex-wrap gap-2" data-testid="profile-form">
      {items.map((f) => (
        <li key={f.match.id}>
          <Link
            to="/matches/$fixtureId"
            params={{ fixtureId: String(f.match.id) }}
            className={cn(
              "numeric inline-flex h-9 min-w-9 items-center justify-center rounded-full px-2 text-sm font-bold",
              RESULT_TONE[f.result],
            )}
            title={`${f.match.home.name} ${f.match.score?.home}–${f.match.score?.away} ${f.match.away.name}`}
          >
            {t(`profiles.result.${f.result}`)}
            <span className="sr-only">
              {" "}
              {f.goalsFor}–{f.goalsAgainst}
            </span>
          </Link>
        </li>
      ))}
    </ol>
  );
}

function TableExcerpt({ competitionId, teamId }: { competitionId: number; teamId: number }) {
  const q = useQuery(live.standings(String(competitionId)));
  const table = q.data?.data ?? null;
  const rows = table ? excerpt(table.rows, teamId) : [];
  if (q.isPending) return <SkeletonCards count={1} />;
  if (!table || rows.length === 0)
    return <p className="text-sm text-muted-foreground">{t("profiles.tableNone")}</p>;
  return (
    <table className="w-full text-sm" data-testid="profile-table">
      <thead>
        <tr className="text-left text-label text-subtle-foreground">
          <th scope="col" className="w-8 py-1 font-medium">
            #
          </th>
          <th scope="col" className="py-1 font-medium">
            {t("profiles.team")}
          </th>
          <th scope="col" className="py-1 text-right font-medium">
            {t("profiles.played")}
          </th>
          <th scope="col" className="py-1 text-right font-medium">
            {t("profiles.points")}
          </th>
        </tr>
      </thead>
      <tbody className="numeric">
        {rows.map((r) => (
          <tr
            key={r.team_id}
            className={cn(
              "border-t border-border",
              r.team_id === teamId && "bg-primary-soft/40 font-semibold",
            )}
          >
            <td className="py-1.5 text-muted-foreground">{r.rank}</td>
            <th scope="row" className="py-1.5 text-left font-[inherit]">
              <TeamName name={r.team} logo={r.team_logo} size={16} />
            </th>
            <td className="py-1.5 text-right">{r.played}</td>
            <td className="py-1.5 text-right font-semibold">{r.points}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function RecordRow({ r, label }: { r: TeamRecord; label: string }) {
  return (
    <tr className="border-t border-border">
      <th scope="row" className="py-2 pr-2 text-left font-semibold">
        {label}
        {r.season ? (
          <span className="block text-caption font-normal text-muted-foreground">{r.season}</span>
        ) : null}
      </th>
      <td className="py-2 text-right">{r.played}</td>
      <td className="whitespace-nowrap py-2 text-right">
        {r.won}-{r.drawn}-{r.lost}
      </td>
      <td className="whitespace-nowrap py-2 text-right">
        {r.goals_for}:{r.goals_against}
      </td>
    </tr>
  );
}

function Stats({ detail }: { detail: TeamDetail }) {
  const rows = detail.records?.data ?? (detail.record.data ? [detail.record.data] : []);
  const life = detail.lifetime?.data ?? null;
  if (rows.length === 0 && !life)
    return (
      <p className="text-sm text-muted-foreground">
        {detail.record.reason ?? t("profiles.statsNone")}
      </p>
    );
  return (
    <table className="w-full text-sm" data-testid="profile-records">
      <thead>
        <tr className="text-left text-label text-subtle-foreground">
          <th scope="col" className="py-1 font-medium">
            {t("profiles.competition")}
          </th>
          <th scope="col" className="py-1 text-right font-medium">
            {t("profiles.played")}
          </th>
          <th scope="col" className="py-1 text-right font-medium">
            {t("profiles.wdl")}
          </th>
          <th scope="col" className="py-1 text-right font-medium">
            {t("profiles.goals")}
          </th>
        </tr>
      </thead>
      <tbody className="numeric">
        {rows.map((r, i) => (
          <RecordRow key={`${r.competition}-${r.season}-${i}`} r={r} label={r.competition ?? "—"} />
        ))}
        {life ? <RecordRow r={life} label={t("profiles.lifetime")} /> : null}
      </tbody>
    </table>
  );
}

function Squad({ teamId }: { teamId: number }) {
  const q = useQuery(live.players({ team_id: teamId }));
  if (q.isPending) return <SkeletonCards count={2} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  const groups = squadGroups(q.data?.data ?? []);
  if (groups.length === 0)
    return <p className="text-sm text-muted-foreground">{t("profiles.squadNone")}</p>;
  return (
    <div className="space-y-4" data-testid="profile-squad">
      {groups.map((g) => (
        <section key={g.group} aria-label={t(`profiles.positions.${g.group}`)}>
          <h3 className="text-overline text-subtle-foreground">
            {t(`profiles.positions.${g.group}`)}
          </h3>
          <ul className="mt-1 divide-y divide-border">
            {g.players.map((p) => (
              <li key={p.id}>
                <Link
                  to="/players/$playerId"
                  params={{ playerId: String(p.id) }}
                  className="flex min-h-11 items-center gap-3 py-1.5 hover:text-primary"
                >
                  <span className="min-w-0 flex-1 truncate text-sm font-semibold">{p.name}</span>
                  <span className="numeric shrink-0 text-caption text-muted-foreground">
                    {t("profiles.appsGoals", { apps: p.apps, goals: p.goals ?? 0 })}
                  </span>
                  <ChevronRight aria-hidden className="h-4 w-4 shrink-0 text-subtle-foreground" />
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ))}
      <p className="text-caption text-muted-foreground">{t("profiles.squadNote")}</p>
    </div>
  );
}

function Body({
  detail,
  tab,
  kind,
}: {
  detail: TeamDetail;
  tab: ProfileTab;
  kind: "club" | "nation";
}) {
  const { stats: statsV2 } = useStatsSwitches();
  const id = detail.team.id;
  const next = detail.upcoming[0];
  const form = formOf(detail.recent, id);
  const competition = tableCompetition(detail);
  if (tab === "matches")
    return (
      <div className="grid gap-4 lg:grid-cols-2">
        <Block title={t("profiles.upcoming")} icon={<CalendarDays className="h-4 w-4" />}>
          {detail.upcoming.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("profiles.upcomingNone")}</p>
          ) : (
            <div className="divide-y divide-border">
              {detail.upcoming.map((m) => (
                <MatchLine key={m.id} m={m} teamId={id} />
              ))}
            </div>
          )}
        </Block>
        <Block title={t("profiles.recent")} icon={<CalendarDays className="h-4 w-4" />}>
          {detail.recent.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("profiles.recentNone")}</p>
          ) : (
            <div className="divide-y divide-border">
              {detail.recent.map((m) => (
                <MatchLine key={m.id} m={m} teamId={id} />
              ))}
            </div>
          )}
        </Block>
      </div>
    );
  if (tab === "squad")
    return (
      <Block
        title={kind === "nation" ? t("profiles.callUp") : t("profiles.squad")}
        icon={<Users className="h-4 w-4" />}
      >
        <Squad teamId={id} />
      </Block>
    );
  if (tab === "stats")
    return statsV2 ? (
      <TeamStatsHub teamId={String(id)} />
    ) : (
      <Block title={t("profiles.stats")} icon={<ListOrdered className="h-4 w-4" />}>
        <Stats detail={detail} />
      </Block>
    );
  if (tab === "news")
    return (
      <Card className="p-4">
        <EmptyState
          icon={<Newspaper aria-hidden className="h-5 w-5" />}
          title={t("profiles.newsSoon")}
          body={t("profiles.newsSoonBody")}
          action={
            <Link to="/news" className="text-sm font-semibold text-primary hover:underline">
              {t("profiles.toNews")}
            </Link>
          }
        />
      </Card>
    );
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,24rem)] lg:items-start">
      <div className="flex min-w-0 flex-col gap-4">
        <Block title={t("profiles.next")} testId="profile-next">
          {next ? (
            <MatchLine m={next} teamId={id} />
          ) : (
            <p className="text-sm text-muted-foreground">{t("profiles.upcomingNone")}</p>
          )}
        </Block>
        <Block title={t("profiles.form")}>
          <FormStrip items={form} />
        </Block>
        <Block title={t("profiles.stats")} icon={<ListOrdered className="h-4 w-4" />}>
          <Stats detail={detail} />
        </Block>
      </div>
      <div className="flex min-w-0 flex-col gap-4">
        <Block title={t("profiles.table")}>
          {competition ? (
            <TableExcerpt competitionId={competition} teamId={id} />
          ) : (
            <p className="text-sm text-muted-foreground">{t("profiles.tableNone")}</p>
          )}
        </Block>
        <Card className="p-4 text-caption text-muted-foreground" data-testid="profile-coming">
          {t("profiles.coming")}
        </Card>
      </div>
    </div>
  );
}

export function TeamPage({ teamId, nation = false }: { teamId: string; nation?: boolean }) {
  const open = useAuth().user?.profiles === true;
  const search = useSearch({ strict: false }) as { tab?: ProfileTab };
  const navigate = useNavigate();
  const tab = search.tab ?? "summary";
  const q = useQuery({ ...live.team(teamId), enabled: open });
  if (!open)
    return (
      <Card className="p-4">
        <EmptyState title={t("profiles.closed")} />
      </Card>
    );
  if (q.isPending) return <SkeletonCards count={3} />;
  if (q.isError)
    return (
      <Card className={missing(q.error) ? "p-4" : undefined}>
        {missing(q.error) ? (
          <EmptyState title={t("profiles.teamMissing")} />
        ) : (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        )}
      </Card>
    );
  const detail = q.data.data;
  const kind = nation || isNation(detail.team) ? "nation" : "club";
  const venue = detail.venue;
  const facts = [
    countryName(detail.team.country),
    venue ? [venue.name, venue.city].filter(Boolean).join(", ") : null,
    venue?.capacity ? t("profiles.capacity", { n: venue.capacity.toLocaleString() }) : null,
  ].filter((x): x is string => Boolean(x));
  return (
    <div
      className="mx-auto flex w-full max-w-6xl flex-col gap-5"
      data-testid="team-page"
      data-kind={kind}
    >
      <EntityHeader
        kind={kind}
        name={teamLabel(detail.team)}
        logo={detail.team.logo_url}
        facts={facts}
        actions={
          <FollowStar
            team={{
              id: detail.team.id,
              name: detail.team.name,
              logo_url: detail.team.logo_url ?? null,
            }}
          />
        }
      />
      {/* five tabs: on a narrow phone they scroll sideways rather than squeeze */}
      <div className="-mx-1 overflow-x-auto px-1 [scrollbar-width:none]">
        <Segmented<ProfileTab>
          full={false}
          className="min-w-max"
          value={tab}
          onChange={(v) =>
            void navigate({
              to: ".",
              search: (v === "summary" ? {} : { tab: v }) as never,
              replace: true,
            })
          }
          label={t("profiles.tabsLabel")}
          testId="profile-tabs"
          options={PROFILE_TABS.map((v) => ({ value: v, label: t(`profiles.tabs.${v}`) }))}
        />
      </div>
      <Body detail={detail} tab={tab} kind={kind} />
    </div>
  );
}

/** A profile that does not exist answers 404: said as such, not as an error to retry. */
function missing(error: unknown): boolean {
  return error instanceof LiveApiError && error.status === 404;
}
