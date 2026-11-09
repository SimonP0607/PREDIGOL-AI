/**
 * A match that has kicked off and the pre-match picks taken on it (plan PICKS, F6). The teams, the
 * competition, the kick-off and the score are said once, at the top; each pick keeps its own card below with what
 * it was when taken and its own result. A match with three picks reads as one match, not as three cards that
 * repeat it.
 */
import { Link } from "@tanstack/react-router";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { CompetitionTag, Matchup } from "@/components/football/Logos";
import { isLivePhase } from "@/product/matches/status";
import { startedScore, type StartedMatchGroup } from "@/product/picks/started";
import { Kickoff, ShadowBadge } from "./Bits";
import { StartedPickCard } from "./StartedPickCard";

export function StartedMatchGroupCard({
  group,
  shadow = false,
  className,
}: {
  group: StartedMatchGroup;
  /** From the admin's shadow preview: labelled, never a recommendation. */
  shadow?: boolean;
  className?: string | undefined;
}) {
  const { head, picks } = group;
  return (
    <section
      data-testid="started-match"
      data-fixture={group.fixtureId}
      aria-label={`${head.home.name} - ${head.away.name}`}
      className={cn("rounded-xl border border-border/80 bg-card/40 p-2 sm:p-3", className)}
    >
      <Link
        to="/matches/$fixtureId"
        params={{ fixtureId: String(group.fixtureId) }}
        className="block rounded-lg px-2 pb-2 pt-1 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      >
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <CompetitionTag
            name={head.competition.name}
            logo={head.competition.logo_url}
            flag={head.competition.flag_url}
            country={head.competition.country}
            className="min-w-[9rem] flex-1"
          />
          <div className="ml-auto flex shrink-0 items-center gap-1.5">
            {shadow ? <ShadowBadge compact /> : null}
            <Kickoff at={head.kickoff_at} />
          </div>
        </div>
        <Matchup
          home={{ name: head.home.name, logo: head.home.logo_url }}
          away={{ name: head.away.name, logo: head.away.logo_url }}
          score={startedScore(head)}
          live={isLivePhase(head.phase)}
          className="pt-2.5"
        />
        <p
          className="mt-2 text-caption font-semibold text-muted-foreground"
          data-testid="started-match-count"
        >
          {t("picks.started.inMatch", { count: picks.length })}
        </p>
      </Link>
      <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3">
        {picks.map((p) => (
          <StartedPickCard key={p.pick_id} pick={p} shadow={shadow} hideMatch />
        ))}
      </div>
    </section>
  );
}
