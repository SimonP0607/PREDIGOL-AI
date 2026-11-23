/**
 * «Equipos» → a league opens, in its own place, onto ITS teams (plan de correcciones UX, AP-E01; audit E1): country → league →
 * teams → profile. Before, a league led to Partidos; now no click of Equipos does. The teams come from GET /teams?competition_id
 * and are fetched only when the league is opened.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ChevronRight } from "lucide-react";
import { TeamName } from "@/components/football/Logos";
import { live } from "@/lib/api/v1/queries";
import type { CompetitionSummary, TeamSummary } from "@/lib/api/v1/types";
import { t } from "@/lib/i18n";
import { Skeleton } from "@/components/ui/skeleton";
import { isNation, teamLabel } from "./model";

/** Crest and name, 2 to 6 columns by the width of the card (a container query, not the screen's). */
export function TeamGrid({ teams }: { teams: readonly TeamSummary[] }) {
  return (
    <ul
      className="grid grid-cols-2 gap-2 @[28rem]:grid-cols-3 @[40rem]:grid-cols-4 @[52rem]:grid-cols-5 @[64rem]:grid-cols-6"
      data-testid="league-teams"
    >
      {[...teams]
        .sort((a, b) => teamLabel(a).localeCompare(teamLabel(b)))
        .map((team) => (
          <li key={team.id} className="min-w-0">
            <Link
              to={isNation(team) ? "/nations/$teamId" : "/teams/$teamId"}
              params={{ teamId: String(team.id) }}
              data-testid="league-team"
              className="flex min-h-12 items-center gap-2.5 rounded-control border border-border px-3 py-2 text-sm font-semibold hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <TeamName
                name={teamLabel(team)}
                logo={team.logo_url}
                size={22}
                className="min-w-0 flex-1"
              />
            </Link>
          </li>
        ))}
    </ul>
  );
}

function LeagueTeams({ id }: { id: number }) {
  const teams = useQuery(live.competitionTeams(id));
  if (teams.isPending) return <Skeleton className="h-16 w-full" />;
  if (teams.isError)
    return (
      <p className="text-sm text-muted-foreground" role="status">
        {t("profiles.teams.leagueError")}{" "}
        <button
          type="button"
          onClick={() => void teams.refetch()}
          className="font-semibold text-primary hover:underline"
        >
          {t("common.retry")}
        </button>
      </p>
    );
  const list = teams.data.data;
  if (list.length === 0)
    return <p className="text-sm text-muted-foreground">{t("profiles.teams.leagueNone")}</p>;
  return <TeamGrid teams={list} />;
}

/**
 * One league of a country: its name opens (a native disclosure: the browser says «expandido/contraído» to a screen reader and
 * the keyboard opens it) onto its teams, and a quiet link to its table and calendar when PM has that page on.
 */
export function LeagueRow({
  competition,
  competitionPage,
}: {
  competition: CompetitionSummary;
  competitionPage: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <li>
      <details
        className="group/l"
        onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}
      >
        <summary
          data-testid="league-summary"
          className="flex min-h-11 cursor-pointer list-none items-center gap-3 px-6 py-2 text-sm hover:bg-elevated [&::-webkit-details-marker]:hidden"
        >
          <span className="min-w-0 flex-1">{competition.name}</span>
          <ChevronRight
            aria-hidden
            className="h-4 w-4 shrink-0 text-subtle-foreground transition-transform group-open/l:rotate-90"
          />
        </summary>
        {open ? (
          <div className="@container space-y-3 px-4 pb-3 pt-1 sm:px-6" data-testid="league-panel">
            <LeagueTeams id={competition.id} />
            {competitionPage ? (
              <Link
                to="/competitions/$competitionId"
                params={{ competitionId: String(competition.id) }}
                data-testid="league-table-link"
                className="inline-flex min-h-9 items-center gap-1 text-sm font-semibold text-primary hover:underline"
              >
                {t("profiles.teams.leagueTable")}
                <ChevronRight aria-hidden className="h-4 w-4" />
              </Link>
            ) : null}
          </div>
        ) : null}
      </details>
    </li>
  );
}
