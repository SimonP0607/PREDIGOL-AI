/**
 * A match in play we know little more than the score of, as a compact row on /live: the minute (or the kick-off),
 * home above away with the goals on the right, and - when PrediGol has picks on it - their count under the minute.
 */
import { Link } from "@tanstack/react-router";
import { Clock, Target } from "lucide-react";
import type { LiveMatch } from "@/lib/api/v1/types_center";
import { t } from "@/lib/i18n";
import { formatTime } from "@/lib/time";
import { FixtureLine } from "@/product/matches/FixtureLine";
import { RowClock } from "@/product/matches/MatchRow";
import { liveLabel, phaseOf, shortStatus } from "@/product/matches/status";

/**
 * A row's mark for the matches PrediGol has picks on: the count under the minute, in the row's own flow. Laid over
 * the row (as the cards' badge is), "PrediGol · 2 picks" covered the team names and the score on a phone.
 */
function PicksMark({ count }: { count: number }) {
  return (
    <span
      className="inline-flex items-center gap-0.5 rounded-full border border-gold/50 bg-gold-soft px-1.5 text-[0.6875rem] font-semibold leading-4 text-gold-strong"
      data-testid="live-picks-badge"
      title={t("live.picksBadge", { count })}
    >
      <Target aria-hidden className="h-3 w-3" />
      <span aria-hidden className="numeric">
        {count}
      </span>
      <span className="sr-only">{t("live.picksBadge", { count })}</span>
    </span>
  );
}

export function LiveRow({ m, picks }: { m: LiveMatch; picks: number }) {
  const pre = phaseOf(shortStatus(m.status)) === "pre";
  const score =
    !pre && m.goals_home !== null && m.goals_away !== null
      ? { home: m.goals_home, away: m.goals_away }
      : null;
  return (
    <Link
      to="/matches/$fixtureId"
      params={{ fixtureId: String(m.fixture_id) }}
      data-testid="live-row"
      className="flex min-h-[3.25rem] items-center gap-2 px-3 py-2.5 transition-colors hover:bg-elevated/60 focus-visible:bg-elevated focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring sm:min-h-11 sm:gap-3 sm:py-2"
    >
      <span className="flex w-[3.25rem] shrink-0 flex-col items-start gap-1 sm:w-14">
        {pre ? (
          <span className="numeric text-xs font-medium text-muted-foreground">
            {formatTime(m.kickoff_at)}
          </span>
        ) : (
          <RowClock label={liveLabel(m.status, m.elapsed, m.extra)} />
        )}
        {picks > 0 ? <PicksMark count={picks} /> : null}
      </span>
      <FixtureLine
        home={{ name: m.home.name, logo: m.home.logo_url }}
        away={{ name: m.away.name, logo: m.away.logo_url }}
        score={score}
        live={!pre}
      />
      <span className="flex w-4 shrink-0 justify-end">
        {m.data_status === "stale" ? (
          <span title={t("live.stale")} className="text-subtle-foreground">
            <Clock aria-hidden className="h-3.5 w-3.5" />
            <span className="sr-only">{t("live.stale")}</span>
          </span>
        ) : null}
      </span>
    </Link>
  );
}
