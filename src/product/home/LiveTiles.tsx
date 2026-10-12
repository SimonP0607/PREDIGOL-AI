/** Up to six matches in play, as small score tiles that open the match. */
import { Link } from "@tanstack/react-router";
import { Radio } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { formatRelative, formatTime } from "@/lib/time";
import type { Section } from "@/lib/api/v1/types";
import type { LiveMatch } from "@/lib/api/v1/types_center";
import { CompetitionTag, TeamLogo } from "@/components/football/Logos";
import { MatchClock } from "@/product/live/LiveCard";
import { SectionHeader } from "@/product/shared/States";
import { emptyReason } from "@/product/shared/markets";

/** The two feeds name the same states differently ("NS" / "Not Started", "FT" / "Match Finished"). */
const NOT_STARTED = new Set(["NS", "TBD", "Not Started"]);
const FINISHED = new Set(["FT", "AET", "PEN", "Match Finished", "Finished", "Ended"]);

function MatchState({ m }: { m: LiveMatch }) {
  if (NOT_STARTED.has(m.status)) {
    return (
      <span
        title={t("home.live.notStarted")}
        className="numeric shrink-0 rounded-md border border-border-strong px-1.5 py-0.5 text-xs text-muted-foreground"
      >
        {formatTime(m.kickoff_at)}
      </span>
    );
  }
  if (FINISHED.has(m.status)) {
    return (
      <span className="shrink-0 rounded-md border border-border-strong px-1.5 py-0.5 text-xs font-semibold text-muted-foreground">
        {t("home.live.finished")}
      </span>
    );
  }
  // In play, the pill /live shows (Descanso, Penales, Pausa, Suspendido...): the minute alone read "120'" in a
  // shoot-out and "61'" for a suspended match.
  return <MatchClock m={m} className="shrink-0" />;
}

function TeamLine({
  name,
  logo,
  goals,
  lead,
}: {
  name: string;
  logo: string | null | undefined;
  goals: number | null;
  /** 1 ahead, -1 behind, 0 level or unknown. */
  lead: number;
}) {
  return (
    <div className="flex items-center gap-2">
      <TeamLogo src={logo} name={name} size={20} />
      {/* The whole name, wrapping: two tiles side by side on a phone left "New E…" and "Americ…" (audit, live). */}
      <span
        data-testid="team-name"
        className={cn(
          "min-w-0 flex-1 break-words text-sm leading-snug [overflow-wrap:anywhere]",
          lead > 0 ? "font-semibold text-foreground" : lead < 0 ? "text-muted-foreground" : "",
        )}
      >
        {name}
      </span>
      <span
        className={cn(
          "numeric w-5 shrink-0 text-right text-base font-semibold",
          lead < 0 && "text-muted-foreground",
        )}
      >
        {goals ?? "–"}
      </span>
    </div>
  );
}

function LiveTile({ m }: { m: LiveMatch }) {
  const gh = m.goals_home;
  const ga = m.goals_away;
  const lead = gh !== null && ga !== null ? Math.sign(gh - ga) : 0;
  return (
    <Link
      to="/matches/$fixtureId"
      params={{ fixtureId: String(m.fixture_id) }}
      data-testid="live-tile"
      className="block h-full rounded-xl border border-border bg-card p-3 transition-colors hover:border-border-strong focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring sm:p-3.5"
    >
      <div className="flex items-center justify-between gap-2 text-caption">
        <CompetitionTag
          name={m.competition}
          logo={m.competition_logo}
          flag={m.competition_flag}
          country={m.country}
          size={14}
          className="min-w-0"
        />
        <MatchState m={m} />
      </div>
      <div className="mt-3 space-y-2">
        <TeamLine name={m.home.name} logo={m.home.logo_url} goals={gh} lead={lead} />
        <TeamLine name={m.away.name} logo={m.away.logo_url} goals={ga} lead={-lead} />
      </div>
    </Link>
  );
}

export function LiveTiles({
  section,
  liveAt,
}: {
  section: Section<LiveMatch[]>;
  liveAt: string | null | undefined;
}) {
  const matches = section.data.slice(0, 6);
  return (
    <section data-testid="home-live">
      <SectionHeader
        title={t("home.live.title")}
        subtitle={
          matches.length > 0 && liveAt
            ? t("home.live.updated", { when: formatRelative(liveAt) })
            : undefined
        }
        icon={<Radio aria-hidden className="h-4 w-4 shrink-0 text-primary" />}
        action={{ label: t("common.seeAll"), to: "/live" }}
      />
      {matches.length === 0 ? (
        <p
          data-empty-state
          className="mt-3 flex items-center gap-2.5 rounded-xl border border-border bg-card px-4 py-3 text-sm text-muted-foreground"
        >
          <Radio aria-hidden className="h-4 w-4 shrink-0 text-subtle-foreground" />
          {emptyReason(section.reason) || t("home.live.empty")}
        </p>
      ) : (
        // One tile a row on a phone: two side by side squeezed the competition into a column of single letters
        // ("M / a / j / o / r…") at 320 px and cut every team name up to 430 px.
        <ul className="mt-3 grid grid-cols-1 gap-2.5 sm:grid-cols-2 sm:gap-3 lg:grid-cols-3">
          {matches.map((m) => (
            <li key={m.fixture_id}>
              <LiveTile m={m} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
