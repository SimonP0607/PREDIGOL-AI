/**
 * Two teams and the score, sized for a list row.
 *
 * It follows the room the row gives it, not the screen (mobile UX plan, UX-094): a container query on the line.
 * Narrow (under 30 rem, 480 px - every phone, and a 640 px window whose row keeps the time and the bookmakers at its
 * sides): one team per line with its goals on the right; a long name wraps rather than being cut.
 * From 30 rem: one line, "Home [crest] 1 – 0 [crest] Away", the score in a fixed centre column so crests and scores
 * line up from row to row; each side has 160 px or more. A name is cut with an ellipsis only from 40 rem (each side
 * 240 px or more), where a cut is rare; below it a name wraps (UX-076). Before UX-094 the one-line layout started at
 * the screen's `sm` (640 px) and left 114 px a side, so «Mönchengladbach» broke in the middle of the word.
 */
import { GoalDigit } from "@/product/shared/GoalDigit";
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
      <TeamLogo src={side.logo} name={side.name} size={22} />
      {/* A phone: one team per line and the whole name, on two lines if need be (mobile UX audit: "Omonia …"). */}
      <span
        className={cn(
          // «Noche de partido» (the system's sheet 4): a team's name in Archivo, a step narrower; the side that
          // lost steps back in weight and in colour, never the winner in colour alone
          "min-w-0 break-words font-display leading-snug [font-stretch:92%] [overflow-wrap:anywhere] @min-[40rem]:truncate",
          outcome === "lose" ? "font-medium text-muted-foreground" : "font-bold text-foreground",
        )}
        data-testid="team-name"
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
    <GoalDigit
      value={value}
      className={cn(
        "numeric min-w-[1.25rem] text-right text-lg font-extrabold leading-none tabular-nums",
        live ? "text-primary" : outcome === "lose" ? "text-muted-foreground" : "text-foreground",
        className,
      )}
    />
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
    // The container the line's layout asks (UX-094): the room the row leaves it, not the screen's width.
    <div className={cn("@container min-w-0 flex-1", className)}>
      <div
        className={cn(
          "grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-2 gap-y-1.5 text-[0.9375rem]",
          "@min-[30rem]:grid-cols-[minmax(0,1fr)_4.75rem_minmax(0,1fr)] @min-[30rem]:gap-x-2.5",
        )}
      >
        <Team
          side={home}
          outcome={homeTone}
          className="col-start-1 row-start-1 @min-[30rem]:flex-row-reverse @min-[30rem]:text-right"
        />
        <Goals
          value={score?.home ?? null}
          outcome={homeTone}
          live={live}
          className="col-start-2 row-start-1 @min-[30rem]:hidden"
        />
        <span
          className={cn(
            "numeric hidden items-center justify-center gap-1.5 text-lg font-extrabold leading-none tabular-nums @min-[30rem]:col-start-2 @min-[30rem]:row-start-1 @min-[30rem]:flex",
            live && "text-primary",
          )}
        >
          {score ? (
            <>
              <GoalDigit
                value={score.home}
                className={cn(!live && homeTone === "lose" && "text-muted-foreground")}
              />
              <span aria-hidden className="text-subtle-foreground">
                –
              </span>
              <GoalDigit
                value={score.away}
                className={cn(!live && awayTone === "lose" && "text-muted-foreground")}
              />
            </>
          ) : (
            <span className="font-sans text-xs font-normal text-subtle-foreground">
              {t("common.vs")}
            </span>
          )}
        </span>
        <Team
          side={away}
          outcome={awayTone}
          className="col-start-1 row-start-2 @min-[30rem]:col-start-3 @min-[30rem]:row-start-1"
        />
        <Goals
          value={score?.away ?? null}
          outcome={awayTone}
          live={live}
          className="col-start-2 row-start-2 @min-[30rem]:hidden"
        />
      </div>
    </div>
  );
}
