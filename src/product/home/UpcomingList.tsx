/** The next matches of the followed competitions: when, where, who, and how many bookmakers quote them. */
import { Link } from "@tanstack/react-router";
import { CalendarDays } from "lucide-react";
import { t } from "@/lib/i18n";
import { formatDate, formatTime, relativeDay } from "@/lib/time";
import type { Section } from "@/lib/api/v1/types";
import type { UpcomingMatch } from "@/lib/api/v1/types_product";
import { CompetitionTag, TeamName } from "@/components/football/Logos";
import { Card, SectionHeader } from "@/product/shared/States";
import { emptyReason } from "@/product/shared/markets";

function dayLabel(at: string): string {
  const rel = relativeDay(at);
  if (rel === "today") return t("common.day.today");
  if (rel === "tomorrow") return t("common.day.tomorrow");
  if (rel === "yesterday") return t("common.day.yesterday");
  return formatDate(at);
}

function UpcomingRow({ m }: { m: UpcomingMatch }) {
  return (
    <Link
      to="/matches/$fixtureId"
      params={{ fixtureId: String(m.fixture_id) }}
      data-testid="upcoming-row"
      className="flex h-full items-center gap-3 px-4 py-3 transition-colors hover:bg-elevated/50 focus-visible:bg-elevated/60 focus-visible:outline-none sm:px-5"
    >
      <div className="w-12 shrink-0 text-center">
        <div className="numeric text-sm font-semibold leading-tight">
          {formatTime(m.kickoff_at)}
        </div>
        <div className="mt-0.5 truncate text-caption text-muted-foreground">
          {dayLabel(m.kickoff_at)}
        </div>
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-1.5 text-sm font-medium">
          <TeamName name={m.home.name} logo={m.home.logo_url} size={18} className="min-w-0" />
          <span aria-hidden className="shrink-0 text-subtle-foreground">
            –
          </span>
          <TeamName name={m.away.name} logo={m.away.logo_url} size={18} className="min-w-0" />
        </div>
        <div className="mt-1.5 flex min-w-0 items-center justify-between gap-2 text-caption">
          <CompetitionTag
            name={m.competition.name}
            logo={m.competition.logo_url}
            flag={m.competition.flag_url}
            country={m.competition.country}
            size={12}
            className="min-w-0"
          />
          {m.bookmakers > 0 ? (
            <span
              title={t("home.upcoming.bookmakersHelp")}
              className="shrink-0 rounded-full border border-border-strong bg-elevated px-2 py-px font-medium text-muted-foreground"
            >
              {t("home.upcoming.bookmakers", { count: m.bookmakers })}
            </span>
          ) : null}
        </div>
      </div>
    </Link>
  );
}

export function UpcomingList({ section }: { section: Section<UpcomingMatch[]> }) {
  const matches = section.data.slice(0, 8);
  return (
    <section data-testid="home-upcoming">
      <SectionHeader
        title={t("home.upcoming.title")}
        icon={<CalendarDays aria-hidden className="h-4 w-4 shrink-0 text-primary" />}
        action={{ label: t("home.upcoming.seeAll"), to: "/matches" }}
      />
      {matches.length === 0 ? (
        <p
          data-empty-state
          className="mt-3 flex items-center gap-2.5 rounded-xl border border-border bg-card px-4 py-3 text-sm text-muted-foreground"
        >
          <CalendarDays aria-hidden className="h-4 w-4 shrink-0 text-subtle-foreground" />
          {emptyReason(section.reason) || t("home.upcoming.empty")}
        </p>
      ) : (
        <Card className="mt-3 overflow-hidden">
          {/* Hairlines between rows (and between the two columns on desktop). */}
          <ul className="grid grid-cols-1 gap-px bg-border/70 lg:grid-cols-2">
            {matches.map((m) => (
              <li key={m.fixture_id} className="bg-card">
                <UpcomingRow m={m} />
              </li>
            ))}
            {matches.length % 2 === 1 ? (
              <li aria-hidden className="hidden bg-card lg:block" />
            ) : null}
          </ul>
        </Card>
      )}
    </section>
  );
}
