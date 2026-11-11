/**
 * One match in the day list: kick-off (or the live minute, or "Final"), the two teams with
 * the score, and on the right its state when unusual plus how many bookmakers price it.
 * The whole row opens the match; the bookmakers' chip opens its Mercados.
 */
import { memo } from "react";
import { Link } from "@tanstack/react-router";
import { t } from "@/lib/i18n";
import { formatTime } from "@/lib/time";
import { cn } from "@/lib/utils";
import { WhyChip } from "@/product/favorites/WhyChip";
import type { Why } from "@/product/home/why";
import { FixtureLine } from "./FixtureLine";
import { rowScore, rowWinner, sameItem, type MatchItem } from "./model";
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
        <span className="font-display text-[0.8125rem] font-bold text-muted-foreground">
          {t("matches.clock.FT")}
        </span>
        {pens ? (
          <span className="numeric text-micro text-subtle-foreground">
            {t("matches.row.pens", pens)}
          </span>
        ) : match.status_short === "AET" ? (
          <span className="text-micro text-subtle-foreground">{t("matches.row.aet")}</span>
        ) : null}
      </span>
    );
  }
  const off = group === "postponed" || group === "cancelled";
  const tbd = match.status_short === "TBD";
  return (
    <span
      className={cn(
        "numeric",
        // «Noche de partido» (the system's sheet 4): the hour of a match to come, 15 px in Archivo; words («Por
        // definir») and an hour that no longer holds stay small
        group === "scheduled" && !tbd
          ? "text-[0.9375rem] font-bold leading-tight text-foreground"
          : "text-xs",
        group === "scheduled" ? "text-foreground" : "text-subtle-foreground",
        tbd && "font-medium",
        off && "line-through",
      )}
    >
      {tbd ? t("matches.clock.TBD") : formatTime(match.kickoff_at)}
    </span>
  );
}

function statusTagLabel(group: MatchItem["group"]): string | null {
  return group === "postponed"
    ? t("common.status.postponed")
    : group === "cancelled"
      ? t("common.status.cancelled")
      : group === "awaiting"
        ? t("common.status.awaiting")
        : null;
}

/** Drawn beside the row's link and read inside it (sr-only there), so the link still says the match is postponed. */
function StatusTag({ group }: { group: MatchItem["group"] }) {
  const label = statusTagLabel(group);
  if (!label) return null;
  return (
    <span
      aria-hidden
      className={cn(
        "max-w-full rounded-md border px-1.5 py-0.5 text-right text-micro font-medium leading-tight",
        group === "awaiting"
          ? "border-border-strong bg-elevated text-muted-foreground"
          : "border-warning/30 bg-warning-soft text-warning",
      )}
    >
      {label}
    </span>
  );
}

/**
 * «N casas» (plan Partidos, P6): how many bookmakers price the match, counted as before. It is its own link - to the
 * match's Mercados - beside the row's link, never inside it (a link in a link is not valid HTML). Its words are
 * written, not only in a hover text a phone never shows: the screen reader hears what it counts and where it goes.
 */
function OddsChip({ fixtureId, count }: { fixtureId: number; count: number }) {
  return (
    <Link
      to="/matches/$fixtureId"
      params={{ fixtureId: String(fixtureId) }}
      hash="markets"
      title={t("matches.row.oddsHelp", { count })}
      data-testid="match-odds"
      data-fixture-id={fixtureId}
      className="tap relative z-10 inline-flex min-h-6 items-center whitespace-nowrap rounded-md border border-border bg-card px-1.5 py-0.5 text-micro font-medium tabular-nums text-muted-foreground transition-colors hover:border-border-strong hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
    >
      {t("matches.row.bookmakers", { count })}
      <span className="sr-only">
        {" - "}
        {t("matches.row.oddsHelp", { count })}. {t("matches.row.oddsOpen")}
      </span>
    </Link>
  );
}

function MatchRowView({ item, why = null }: { item: MatchItem; why?: Why | null }) {
  const { match, group } = item;
  const off = group === "postponed" || group === "cancelled";
  const tag = statusTagLabel(group);
  const line = (
    <FixtureLine
      home={{ name: match.home.name, logo: match.home.logo_url }}
      away={{ name: match.away.name, logo: match.away.logo_url }}
      score={rowScore(item)}
      winner={rowWinner(item)}
      live={group === "live"}
      className={cn(off && "opacity-70")}
    />
  );
  return (
    // The row's link reaches over the whole row (its ::after); the bookmakers' chip sits above it, a link of its own.
    // A container (UX-094): under 21 rem of row (a phone under 375 px) the state and the bookmakers go under the
    // teams instead of beside them, so the names keep about 140 px instead of 67 px («Tecnico Universitario» on three
    // lines, «Berkhamsted» cut in two on a 320 px phone).
    <div
      className={cn(
        "@container relative flex min-h-[3.25rem] flex-wrap items-center gap-x-2 gap-y-1 px-3 py-2.5 transition-colors hover:bg-elevated/60 sm:min-h-11 sm:gap-x-3 sm:py-2",
        group === "live" && "shadow-[inset_2px_0_0_var(--color-primary)]",
      )}
    >
      <Link
        to="/matches/$fixtureId"
        params={{ fixtureId: String(match.id) }}
        data-testid="match-row"
        data-fixture-id={match.id}
        className="flex min-w-0 flex-1 items-center gap-2 after:absolute after:inset-0 focus-visible:outline-none focus-visible:after:ring-1 focus-visible:after:ring-inset focus-visible:after:ring-ring sm:gap-3"
      >
        <span className="w-[3.25rem] shrink-0 sm:w-14">
          <TimeCell item={item} />
        </span>
        {why ? (
          // A match shown because of a team the reader follows says so under its teams, on one line (plan UX, B2).
          <span className="flex min-w-0 flex-1 flex-col gap-1">
            {line}
            <span className="flex min-w-0">
              <WhyChip why={why} testId="match-why" className="text-micro" />
            </span>
          </span>
        ) : (
          line
        )}
        {tag ? <span className="sr-only">{tag}</span> : null}
      </Link>
      <span
        className={cn(
          // narrow: a line of its own under the teams, after the time's column (3.25 rem + the gap)
          "flex basis-full flex-wrap items-center justify-end gap-1 empty:hidden",
          // beside the teams once the row has the room
          "@min-[21rem]:max-w-[4.5rem] @min-[21rem]:shrink-0 @min-[21rem]:basis-auto @min-[21rem]:flex-col @min-[21rem]:items-end sm:@min-[21rem]:w-28 sm:@min-[21rem]:max-w-none",
        )}
      >
        <StatusTag group={group} />
        {match.odds.bookmakers > 0 ? (
          <OddsChip fixtureId={match.id} count={match.odds.bookmakers} />
        ) : null}
      </span>
    </div>
  );
}

function whyKey(why: Why | null): string {
  if (!why) return "";
  return why.kind === "suggested" ? why.kind : `${why.kind}:${why.names.join("|")}`;
}

/**
 * One row, drawn again only when what it shows changes (plan Partidos, P5): a poll of /live every 15 seconds, or a
 * keystroke that leaves a row in the list, does not repaint the rows whose match, state, score and minute stay put.
 */
export const MatchRow = memo(
  MatchRowView,
  (a, b) => sameItem(a.item, b.item) && whyKey(a.why ?? null) === whyKey(b.why ?? null),
);
