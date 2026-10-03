/**
 * Two teams and the score, sized for a list row.
 *
 * Phone: one team per line with its goals on the right (full names fit at 390 px).
 * From `sm`: one line, "Home [crest] 1 – 0 [crest] Away", the score in a fixed centre
 * column so crests and scores line up from row to row.
 */
import { TeamLogo } from "@/components/football/Logos";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export interface FixtureSide {
  name: string;
  logo: string | null | undefined;
}

type Outcome = "home" | "away" | "draw" | null;

function tone(side: "home" | "away", winner: Outcome): "win" | "lose" | null {
  if (winner === null || winner === "draw") return null;
  return winner === side ? "win" : "lose";
}

function Team({
  side,
  outcome,
  className,
}: {
  side: FixtureSide;
  outcome: "win" | "lose" | null;
  className?: string | undefined;
}) {
  return (
    <span className={cn("flex min-w-0 items-center gap-2", className)}>
      <TeamLogo src={side.logo} name={side.name} size={20} />
      <span
        className={cn(
          "truncate",
          outcome === "win" && "font-semibold text-foreground",
          outcome === "lose" && "text-muted-foreground",
        )}
      >
        {side.name}
      </span>
    </span>
  );
}

function Goals({
  value,
  outcome,
  live,
  className,
}: {
  value: number | null;
  outcome: "win" | "lose" | null;
  live: boolean;
  className?: string | undefined;
}) {
  if (value === null) return null;
  return (
    <span
      className={cn(
        "numeric min-w-[1.25rem] text-right text-sm font-semibold tabular-nums",
        live ? "text-primary" : outcome === "lose" ? "text-muted-foreground" : "text-foreground",
        outcome === "win" && "font-bold",
        className,
      )}
    >
      {value}
    </span>
  );
}

export function FixtureLine({
  home,
  away,
  score,
  winner = null,
  live = false,
  className,
}: {
  home: FixtureSide;
  away: FixtureSide;
  score: { home: number; away: number } | null;
  winner?: Outcome;
  live?: boolean;
  className?: string | undefined;
}) {
  const homeTone = tone("home", winner);
  const awayTone = tone("away", winner);
  return (
    <div
      className={cn(
        "grid min-w-0 flex-1 grid-cols-[minmax(0,1fr)_auto] items-center gap-x-2 gap-y-1.5 text-[0.8125rem]",
        "sm:grid-cols-[minmax(0,1fr)_4.75rem_minmax(0,1fr)] sm:gap-x-2.5 sm:text-sm",
        className,
      )}
    >
      <Team
        side={home}
        outcome={homeTone}
        className="col-start-1 row-start-1 sm:flex-row-reverse sm:text-right"
      />
      <Goals
        value={score?.home ?? null}
        outcome={homeTone}
        live={live}
        className="col-start-2 row-start-1 sm:hidden"
      />
      <span
        className={cn(
          "numeric hidden items-center justify-center gap-1.5 tabular-nums sm:col-start-2 sm:row-start-1 sm:flex",
          live && "text-primary",
        )}
      >
        {score ? (
          <>
            <span className={cn("font-semibold", homeTone === "win" && "font-bold")}>
              {score.home}
            </span>
            <span aria-hidden className="text-subtle-foreground">
              –
            </span>
            <span className={cn("font-semibold", awayTone === "win" && "font-bold")}>
              {score.away}
            </span>
          </>
        ) : (
          <span className="text-xs text-subtle-foreground">{t("common.vs")}</span>
        )}
      </span>
      <Team
        side={away}
        outcome={awayTone}
        className="col-start-1 row-start-2 sm:col-start-3 sm:row-start-1"
      />
      <Goals
        value={score?.away ?? null}
        outcome={awayTone}
        live={live}
        className="col-start-2 row-start-2 sm:hidden"
      />
    </div>
  );
}
