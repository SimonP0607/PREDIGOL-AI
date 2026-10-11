/**
 * A player's summary from the line-ups or the absences (REVIEW PREDIGOL, point 7): who he is for his team -
 * his season in this competition, as the provider aggregates it ("started 7 of 8") - and what he did in this
 * match. A tap on the name opens it; the admin also gets the link to the full research page.
 */
import type { ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { t, translateOr } from "@/lib/i18n";
import { formatRelative } from "@/lib/time";
import type { MatchPlayerSeason, PlayerLine } from "@/lib/api/v1/types_center";
import { PlayerPhoto } from "@/components/football/Logos";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { fmtDecimal } from "./model";

function Stat({ label, value }: { label: string; value: number | null | undefined }) {
  return (
    <div className="min-w-0 rounded-md border border-border/70 bg-elevated/40 px-2 py-1.5 text-center">
      <dt className="truncate text-[0.65rem] text-subtle-foreground">{label}</dt>
      <dd className="numeric text-sm font-semibold">{value ?? "—"}</dd>
    </div>
  );
}

/** "3 PJ · 2 de titular · 1 goles" under an absent player's name; null without a season. */
export function SeasonLine({ season }: { season: MatchPlayerSeason | null | undefined }) {
  if (!season) return null;
  return (
    <span className="numeric block truncate text-caption text-muted-foreground">
      {t("match.absences.seasonLine", {
        apps: season.appearances ?? 0,
        starts: season.lineups ?? 0,
        goals: season.goals ?? 0,
      })}
      {season.team_matches
        ? ` · ${t("match.absences.seasonShare", { starts: season.lineups ?? 0, team: season.team_matches })}`
        : ""}
    </span>
  );
}

export function PlayerSummary({
  name,
  photo,
  position,
  season,
  competition,
  line,
  playerId,
  admin,
  className,
  children,
}: {
  name: string | null;
  photo?: string | null | undefined;
  position?: string | null | undefined;
  season: MatchPlayerSeason | null | undefined;
  competition?: string | null | undefined;
  /** His numbers in this match, once played. */
  line?: PlayerLine | null | undefined;
  playerId: number | null;
  admin: boolean;
  className?: string | undefined;
  children: ReactNode;
}) {
  const label = name ?? t("match.events.unknownPlayer");
  const pos = position ? translateOr(`match.lineups.position.${position}`, position) : null;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={t("match.playerCard.open", { name: label })}
          data-testid="player-summary"
          className={cn(
            "min-w-0 rounded text-left hover:text-primary focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
            className,
          )}
        >
          {children}
        </button>
      </PopoverTrigger>
      <PopoverContent
        className="w-72 space-y-3 p-3"
        align="start"
        data-testid="player-summary-card"
      >
        <div className="flex items-center gap-2.5">
          <PlayerPhoto src={photo ?? null} name={label} size={40} />
          <div className="min-w-0">
            <p className="truncate font-display text-sm font-semibold">{label}</p>
            {pos ? <p className="text-caption text-muted-foreground">{pos}</p> : null}
          </div>
        </div>
        <div>
          <h4 className="mb-1.5 text-label text-subtle-foreground">
            {competition
              ? t("match.playerCard.title", { competition })
              : t("match.playerCard.titleGeneric")}
          </h4>
          {season ? (
            <>
              <dl className="grid grid-cols-3 gap-1.5">
                <Stat label={t("match.playerCard.apps")} value={season.appearances} />
                <Stat label={t("match.playerCard.starts")} value={season.lineups} />
                <Stat label={t("match.playerCard.minutes")} value={season.minutes} />
                <Stat label={t("match.playerCard.goals")} value={season.goals} />
                <Stat label={t("match.playerCard.assists")} value={season.assists} />
                <Stat
                  label={t("match.playerCard.cards")}
                  value={
                    season.yellow_cards === null && season.red_cards === null
                      ? null
                      : (season.yellow_cards ?? 0) + (season.red_cards ?? 0)
                  }
                />
              </dl>
              {season.team_matches ? (
                <p className="numeric mt-1.5 text-caption text-muted-foreground">
                  {t("match.absences.seasonShare", {
                    starts: season.lineups ?? 0,
                    team: season.team_matches,
                  })}
                </p>
              ) : null}
              <p className="mt-1 text-[0.65rem] text-subtle-foreground">
                {t("match.playerCard.source", { when: formatRelative(season.observed_at) })}
              </p>
            </>
          ) : (
            <p className="text-caption text-muted-foreground">{t("match.playerCard.none")}</p>
          )}
        </div>
        {line ? (
          <div>
            <h4 className="mb-1.5 text-label text-subtle-foreground">
              {t("match.playerCard.thisMatch")}
            </h4>
            <dl className="grid grid-cols-3 gap-1.5">
              <Stat label={t("match.playerCard.minutes")} value={line.minutes} />
              <Stat label={t("match.playerCard.goals")} value={line.goals} />
              <Stat label={t("match.playerCard.assists")} value={line.assists} />
            </dl>
            {line.rating ? (
              <p className="numeric mt-1 text-caption text-muted-foreground">
                {t("match.playerCard.rating", { value: fmtDecimal(Number(line.rating), 1) })}
              </p>
            ) : null}
          </div>
        ) : null}
        {admin && playerId !== null ? (
          <Link
            to="/admin/players/$playerId"
            params={{ playerId: String(playerId) }}
            className="inline-flex items-center gap-0.5 text-xs font-medium text-primary hover:underline"
          >
            {t("match.playerCard.fullPage")}
            <ChevronRight aria-hidden className="h-3.5 w-3.5" />
          </Link>
        ) : null}
      </PopoverContent>
    </Popover>
  );
}
