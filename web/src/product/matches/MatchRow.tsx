/**
 * One match in the day list: kick-off (or the live minute, or "Final"), the two teams with
 * the score, and on the right its state when unusual plus how many bookmakers price it.
 * The whole row opens the match.
 */
import { Link } from "@tanstack/react-router";
import { t } from "@/lib/i18n";
import { formatTime } from "@/lib/time";
import { cn } from "@/lib/utils";
import { FixtureLine } from "./FixtureLine";
import { rowScore, rowWinner, type MatchItem } from "./model";
import { liveLabel } from "./status";

/** The pulsing live mark of a list row - the compact sibling of the shared LiveMinute pill. */
export function RowClock({ label, className }: { label: string; className?: string | undefined }) {
  return (
    <span
      className={cn(
        "numeric inline-flex items-center gap-1 whitespace-nowrap text-xs font-semibold text-primary",
        className,
      )}
    >
      <span aria-hidden className="relative flex h-1.5 w-1.5 shrink-0">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-60" />
        <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-primary" />
      </span>
      <span className="sr-only">{t("common.status.live")}</span>
      {label}
    </span>
  );
}

function TimeCell({ item }: { item: MatchItem }) {
  const { match, group, live } = item;
  if (group === "live") {
    return (
      <RowClock
        label={
          live
            ? liveLabel(live.status, live.elapsed, live.extra)
            : liveLabel(match.status_short, null, null)
        }
      />
    );
  }
  if (group === "finished") {
    const s = match.score;
    const pens =
      s && s.pen_home !== null && s.pen_away !== null
        ? { home: s.pen_home, away: s.pen_away }
        : null;
    return (
      <span className="flex flex-col leading-tight">
        <span className="text-xs font-medium text-muted-foreground">{t("matches.clock.FT")}</span>
        {pens ? (
          <span className="numeric text-[0.6875rem] text-subtle-foreground">
            {t("matches.row.pens", pens)}
          </span>
        ) : match.status_short === "AET" ? (
          <span className="text-[0.6875rem] text-subtle-foreground">{t("matches.row.aet")}</span>
        ) : null}
      </span>
    );
  }
  const off = group === "postponed" || group === "cancelled";
  return (
    <span
      className={cn(
        "numeric text-xs",
        group === "scheduled" ? "font-medium text-foreground" : "text-subtle-foreground",
        off && "line-through",
      )}
    >
      {match.status_short === "TBD" ? t("matches.clock.TBD") : formatTime(match.kickoff_at)}
    </span>
  );
}

function StatusTag({ group }: { group: MatchItem["group"] }) {
  const label =
    group === "postponed"
      ? t("common.status.postponed")
      : group === "cancelled"
        ? t("common.status.cancelled")
        : group === "awaiting"
          ? t("common.status.awaiting")
          : null;
  if (!label) return null;
  return (
    <span
      className={cn(
        "max-w-full rounded-md border px-1.5 py-0.5 text-right text-[0.6875rem] font-medium leading-tight",
        group === "awaiting"
          ? "border-border-strong bg-elevated text-muted-foreground"
          : "border-warning/30 bg-warning-soft text-warning",
      )}
    >
      {label}
    </span>
  );
}

function OddsChip({ count }: { count: number }) {
  return (
    <span
      title={t("matches.row.oddsHelp", { count })}
      className="whitespace-nowrap rounded-md border border-border px-1.5 py-0.5 text-[0.6875rem] font-medium tabular-nums text-muted-foreground"
    >
      {t("matches.row.bookmakers", { count })}
    </span>
  );
}

export function MatchRow({ item }: { item: MatchItem }) {
  const { match, group } = item;
  const off = group === "postponed" || group === "cancelled";
  return (
    <Link
      to="/matches/$fixtureId"
      params={{ fixtureId: String(match.id) }}
      data-testid="match-row"
      className={cn(
        "flex min-h-[3.25rem] items-center gap-2 px-3 py-2.5 transition-colors hover:bg-elevated/60 focus-visible:bg-elevated focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring sm:min-h-11 sm:gap-3 sm:py-2",
        group === "live" && "shadow-[inset_2px_0_0_var(--color-primary)]",
      )}
    >
      <span className="w-[3.25rem] shrink-0 sm:w-14">
        <TimeCell item={item} />
      </span>
      <FixtureLine
        home={{ name: match.home.name, logo: match.home.logo_url }}
        away={{ name: match.away.name, logo: match.away.logo_url }}
        score={rowScore(item)}
        winner={rowWinner(item)}
        live={group === "live"}
        className={cn(off && "opacity-70")}
      />
      <span className="flex max-w-[4.5rem] shrink-0 flex-col items-end gap-1 sm:w-28 sm:max-w-none">
        <StatusTag group={group} />
        {match.odds.bookmakers > 0 ? <OddsChip count={match.odds.bookmakers} /> : null}
      </span>
    </Link>
  );
}
