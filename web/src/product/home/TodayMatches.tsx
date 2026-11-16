/**
 * «Partidos de hoy» (maqueta 01 de PrediGol Intelligence): the day's matches by competition, compact - the time or the
 * live minute and score, the two teams and whether PrediGol has its reading of the match. Read from GET /today, which Inicio
 * already asks for; nothing is computed.
 */
import { Link } from "@tanstack/react-router";
import { BookOpenText, CalendarDays } from "lucide-react";
import { CompetitionTag, TeamName } from "@/components/football/Logos";
import { t } from "@/lib/i18n";
import { formatTime } from "@/lib/time";
import type { TodayMatch } from "@/lib/api/v1/types_today";
import { Card, SectionHeader } from "@/product/shared/States";

/** How many matches the block lists before «Todos». */
const SHOWN = 8;

const LIVE = new Set(["LIVE", "HT", "1H", "2H", "ET", "P", "BT", "IN_PLAY"]);
const OVER = new Set(["FT", "AET", "PEN", "FINISHED"]);

function when(m: TodayMatch): { text: string; live: boolean } {
  const group = m.status_group.toUpperCase();
  if (
    LIVE.has(group) ||
    (m.elapsed !== null && !OVER.has(group) && group !== "NS" && group !== "SCHEDULED")
  )
    return { text: m.elapsed !== null ? `${m.elapsed}'` : t("home.todayMatches.live"), live: true };
  if (OVER.has(group)) return { text: t("home.todayMatches.final"), live: false };
  return { text: formatTime(m.kickoff_at), live: false };
}

export function TodayMatchesBlock({ matches }: { matches: readonly TodayMatch[] }) {
  if (matches.length === 0) return null;
  const shown = [...matches]
    .sort((a, b) => Date.parse(a.kickoff_at) - Date.parse(b.kickoff_at))
    .slice(0, SHOWN);
  const groups = new Map<
    number,
    { name: string; badge: TodayMatch["competition"]; rows: TodayMatch[] }
  >();
  for (const m of shown) {
    const g = groups.get(m.competition.id);
    if (g) g.rows.push(m);
    else
      groups.set(m.competition.id, { name: m.competition.name, badge: m.competition, rows: [m] });
  }
  return (
    <section data-testid="home-today-matches">
      <SectionHeader
        title={t("home.todayMatches.title")}
        icon={<CalendarDays aria-hidden className="h-4 w-4 shrink-0 text-primary" />}
        action={{ label: t("home.todayMatches.all", { count: matches.length }), to: "/matches" }}
      />
      <Card className="mt-3 divide-y divide-border/70 overflow-hidden p-0">
        {[...groups.values()].map((g) => (
          <div key={g.badge.id} className="px-4 py-3">
            <CompetitionTag
              name={g.name}
              logo={g.badge.logo_url}
              flag={g.badge.flag_url}
              country={g.badge.country}
              size={14}
              className="text-caption font-semibold text-foreground"
            />
            <ul className="mt-2 space-y-2.5">
              {g.rows.map((m) => {
                const w = when(m);
                return (
                  <li key={m.fixture_id}>
                    <Link
                      to="/matches/$fixtureId"
                      params={{ fixtureId: String(m.fixture_id) }}
                      data-testid="home-today-match"
                      className="grid grid-cols-[3rem_minmax(0,1fr)_auto] gap-x-2 rounded-md hover:bg-elevated/40 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    >
                      <span
                        className={`numeric pt-0.5 text-caption font-semibold ${w.live ? "text-positive" : "text-muted-foreground"}`}
                      >
                        {w.text}
                      </span>
                      <span className="min-w-0 space-y-0.5 text-sm">
                        <TeamName name={m.home.name} logo={m.home.logo_url} size={16} wrap />
                        <TeamName name={m.away.name} logo={m.away.logo_url} size={16} wrap />
                        {m.has_reading ? (
                          <span className="flex items-center gap-1 text-caption font-medium text-primary">
                            <BookOpenText aria-hidden className="h-3 w-3" />
                            {t("home.todayMatches.withReading")}
                          </span>
                        ) : null}
                      </span>
                      {m.goals_home !== null && m.goals_away !== null ? (
                        <span className="numeric space-y-0.5 text-right text-sm font-semibold">
                          <span className="block">{m.goals_home}</span>
                          <span className="block">{m.goals_away}</span>
                        </span>
                      ) : (
                        <span />
                      )}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </Card>
    </section>
  );
}
