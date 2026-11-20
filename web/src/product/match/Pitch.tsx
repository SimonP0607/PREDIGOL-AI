/**
 * The formations on a pitch (Alineaciones): each starter at the box the team sheet declares - the nominal position of the formation,
 * not where he played. Moved out of `LineupsTab.tsx` unchanged so the layers of PM-10-04 (UX-176) draw on the same pitch; a marker
 * carries the rating by default or a layer's figure.
 */
import { cn } from "@/lib/utils";
import { t, translateOr } from "@/lib/i18n";
import type { LineupPlayer, Side, TeamLineup } from "@/lib/api/v1/types_center";
import type { TeamRef } from "@/lib/api/v1/types";
import { fmtDecimal, pitchName, pitchSpots, type PitchSpot } from "./model";

function position(code: string | null): string {
  return code ? translateOr(`match.lineups.position.${code}`, code) : "—";
}

function PitchLines() {
  return (
    <svg
      viewBox="0 0 68 105"
      preserveAspectRatio="none"
      aria-hidden
      className="absolute inset-0 h-full w-full text-primary/25"
      fill="none"
      stroke="currentColor"
      strokeWidth={0.35}
    >
      <rect x="1" y="1" width="66" height="103" rx="0.5" />
      <line x1="1" y1="52.5" x2="67" y2="52.5" />
      <circle cx="34" cy="52.5" r="9.15" />
      <circle cx="34" cy="52.5" r="0.5" fill="currentColor" />
      <rect x="13.84" y="1" width="40.32" height="16.5" />
      <rect x="24.84" y="1" width="18.32" height="5.5" />
      <rect x="13.84" y="87.5" width="40.32" height="16.5" />
      <rect x="24.84" y="98.5" width="18.32" height="5.5" />
      <path d="M26.7 17.5a9.15 9.15 0 0 0 14.6 0" />
      <path d="M26.7 87.5a9.15 9.15 0 0 1 14.6 0" />
    </svg>
  );
}

/** What a marker carries beside the shirt number: the rating by default, or a layer's figure (PM-10-04). */
export interface MarkerBadge {
  text: string;
  /** «best»: the gold edge of the side's highest rating; the cards' colours. */
  tone?: "best" | "yellow" | "red" | undefined;
}

const BADGE_TONE: Record<NonNullable<MarkerBadge["tone"]>, string> = {
  best: "gold-ring bg-gold-soft text-gold-strong",
  yellow: "border-warning/60 bg-warning-soft text-warning",
  red: "border-negative/60 bg-negative/18 text-negative",
};

function Marker({
  spot,
  side,
  badge,
  layered,
}: {
  spot: PitchSpot;
  side: Side;
  badge: MarkerBadge | null;
  /** A data layer is on (PM-10-04): its figure is the marker, at a readable size; the shirt number when it has none. */
  layered: boolean;
}) {
  const p = spot.player;
  const name = pitchName(p.name);
  const sideTone =
    side === "home"
      ? "border-primary/60 bg-primary text-primary-foreground"
      : "border-info/60 bg-info text-background";
  return (
    <div
      className="absolute flex w-[4.1rem] -translate-x-1/2 -translate-y-1/2 flex-col items-center gap-0.5 sm:w-20"
      style={{ left: `${spot.x}%`, top: `${spot.y}%` }}
      title={`${p.number ?? ""} ${p.name ?? ""} · ${position(p.position)}`.trim()}
    >
      {layered && badge !== null ? (
        <span
          data-badge={badge.tone ?? "plain"}
          className={cn(
            "numeric flex h-7 min-w-9 items-center justify-center whitespace-nowrap rounded-md border-2 px-1.5 text-xs font-bold shadow-sm",
            badge.tone ? BADGE_TONE[badge.tone] : sideTone,
          )}
        >
          {badge.text}
        </span>
      ) : (
        <span
          className={cn(
            "numeric relative flex h-7 w-7 items-center justify-center rounded-full border-2 text-micro font-bold shadow-sm sm:h-8 sm:w-8 sm:text-xs",
            sideTone,
            layered && "opacity-70",
          )}
        >
          {p.number ?? ""}
          {!layered && badge !== null ? (
            <span className="absolute -right-3.5 -top-2 rounded bg-background/90 px-0.5 text-[0.55rem] font-semibold text-foreground ring-1 ring-border-strong">
              {badge.text}
            </span>
          ) : null}
        </span>
      )}
      <span
        className={cn(
          "max-w-full truncate rounded bg-background/70 px-1 font-medium leading-4 text-foreground",
          layered ? "text-caption" : "text-[0.62rem] sm:text-[0.68rem]",
        )}
      >
        {name}
      </span>
    </div>
  );
}

export function Pitch({
  home,
  away,
  teams,
  ratings,
  badgeOf,
}: {
  home: TeamLineup;
  away: TeamLineup;
  teams: { home: TeamRef; away: TeamRef };
  ratings: Map<number, number>;
  /** A layer's figure for each marker (PM-10-04); without it, the rating as always. */
  badgeOf?: ((p: LineupPlayer, side: Side) => MarkerBadge | null) | undefined;
}) {
  const homeSpots = pitchSpots(home, "bottom");
  const awaySpots = pitchSpots(away, "top");
  if (!homeSpots || !awaySpots) return null;
  const badge = (p: LineupPlayer, side: Side): MarkerBadge | null => {
    if (badgeOf) return badgeOf(p, side);
    const r = ratings.get(p.provider_player_id);
    return r === undefined ? null : { text: fmtDecimal(r, 1) };
  };
  const label = t("match.lineups.pitchLabel", {
    home: teams.home.name,
    homeFormation: home.formation ?? "—",
    away: teams.away.name,
    awayFormation: away.formation ?? "—",
  });
  return (
    <div
      role="img"
      aria-label={label}
      className="relative mx-auto aspect-[68/105] w-full max-w-[25rem] overflow-hidden rounded-xl border border-primary/25"
      style={{
        backgroundColor: "color-mix(in oklch, var(--color-primary) 7%, var(--color-card))",
        backgroundImage:
          "repeating-linear-gradient(0deg, color-mix(in oklch, var(--color-primary) 5%, transparent) 0 9.52%, transparent 9.52% 19.04%)",
      }}
    >
      <PitchLines />
      <span className="absolute left-2 top-2 z-10 flex items-center gap-1 rounded bg-background/75 px-1.5 py-0.5 text-micro font-semibold text-info">
        {teams.away.name} · {away.formation ?? "—"}
      </span>
      <span className="absolute bottom-2 left-2 z-10 flex items-center gap-1 rounded bg-background/75 px-1.5 py-0.5 text-micro font-semibold text-primary">
        {teams.home.name} · {home.formation ?? "—"}
      </span>
      {awaySpots.map((s) => (
        <Marker
          key={`a-${s.player.provider_player_id}`}
          spot={s}
          side="away"
          badge={badge(s.player, "away")}
          layered={badgeOf !== undefined}
        />
      ))}
      {homeSpots.map((s) => (
        <Marker
          key={`h-${s.player.provider_player_id}`}
          spot={s}
          side="home"
          badge={badge(s.player, "home")}
          layered={badgeOf !== undefined}
        />
      ))}
    </div>
  );
}
