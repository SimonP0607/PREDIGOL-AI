/** Formations on a pitch, then each side's starting XI and substitutes. */
import { Shirt } from "lucide-react";
import { cn } from "@/lib/utils";
import { t, translateOr } from "@/lib/i18n";
import { toNumber } from "@/lib/i18n/format";
import type {
  LineupPlayer,
  MatchEvent,
  PlayerLine,
  Side,
  TeamLineup,
} from "@/lib/api/v1/types_center";
import type { TeamRef } from "@/lib/api/v1/types";
import { PlayerPhoto, TeamName } from "@/components/football/Logos";
import { sectionCodeText } from "@/components/system/sectionCode";
import { Card, EmptyState } from "@/product/shared/States";
import type { MatchCtx } from "./context";
import { AbsencesBlock } from "./ContextBlocks";
import {
  bench,
  eventKind,
  fmtDecimal,
  minuteText,
  pitchName,
  pitchSpots,
  starters,
  subDirection,
  type PitchSpot,
} from "./model";
import { PlayerSummary } from "./PlayerSummary";
import { BallIcon, Block, CardIcon, CenterSection, RatingBadge } from "./ui";

function position(code: string | null): string {
  return code ? translateOr(`match.lineups.position.${code}`, code) : "—";
}

// ── Pitch ───────────────────────────────────────────────────────────────────

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

function Marker({ spot, side, rating }: { spot: PitchSpot; side: Side; rating: number | null }) {
  const p = spot.player;
  const name = pitchName(p.name);
  return (
    <div
      className="absolute flex w-[4.1rem] -translate-x-1/2 -translate-y-1/2 flex-col items-center gap-0.5 sm:w-20"
      style={{ left: `${spot.x}%`, top: `${spot.y}%` }}
      title={`${p.number ?? ""} ${p.name ?? ""} · ${position(p.position)}`.trim()}
    >
      <span
        className={cn(
          "numeric relative flex h-7 w-7 items-center justify-center rounded-full border-2 text-[0.7rem] font-bold shadow-sm sm:h-8 sm:w-8 sm:text-xs",
          side === "home"
            ? "border-primary/60 bg-primary text-primary-foreground"
            : "border-info/60 bg-info text-background",
        )}
      >
        {p.number ?? ""}
        {rating !== null ? (
          <span className="absolute -right-3.5 -top-2 rounded bg-background/90 px-0.5 text-[0.55rem] font-semibold text-foreground ring-1 ring-border-strong">
            {fmtDecimal(rating, 1)}
          </span>
        ) : null}
      </span>
      <span className="max-w-full truncate rounded bg-background/70 px-1 text-[0.62rem] font-medium leading-4 text-foreground sm:text-[0.68rem]">
        {name}
      </span>
    </div>
  );
}

function Pitch({
  home,
  away,
  teams,
  ratings,
}: {
  home: TeamLineup;
  away: TeamLineup;
  teams: { home: TeamRef; away: TeamRef };
  ratings: Map<number, number>;
}) {
  const homeSpots = pitchSpots(home, "bottom");
  const awaySpots = pitchSpots(away, "top");
  if (!homeSpots || !awaySpots) return null;
  const rate = (p: LineupPlayer) => ratings.get(p.provider_player_id) ?? null;
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
      <span className="absolute left-2 top-2 z-10 flex items-center gap-1 rounded bg-background/75 px-1.5 py-0.5 text-[0.65rem] font-semibold text-info">
        {teams.away.name} · {away.formation ?? "—"}
      </span>
      <span className="absolute bottom-2 left-2 z-10 flex items-center gap-1 rounded bg-background/75 px-1.5 py-0.5 text-[0.65rem] font-semibold text-primary">
        {teams.home.name} · {home.formation ?? "—"}
      </span>
      {awaySpots.map((s) => (
        <Marker
          key={`a-${s.player.provider_player_id}`}
          spot={s}
          side="away"
          rating={rate(s.player)}
        />
      ))}
      {homeSpots.map((s) => (
        <Marker
          key={`h-${s.player.provider_player_id}`}
          spot={s}
          side="home"
          rating={rate(s.player)}
        />
      ))}
    </div>
  );
}

// ── Lists ───────────────────────────────────────────────────────────────────

interface PlayerMarks {
  goals: number;
  ownGoals: number;
  yellow: boolean;
  red: boolean;
  subIn: string | null;
  subOut: string | null;
}

/** Goals, cards and substitutions per player, from the events that name him by id. */
function marksByPlayer(events: MatchEvent[], lineups: TeamLineup[]): Map<number, PlayerMarks> {
  const out = new Map<number, PlayerMarks>();
  const get = (id: number) => {
    const m = out.get(id) ?? {
      goals: 0,
      ownGoals: 0,
      yellow: false,
      red: false,
      subIn: null,
      subOut: null,
    };
    out.set(id, m);
    return m;
  };
  for (const e of events) {
    if (e.player_id === null) continue;
    const kind = eventKind(e);
    const m = get(e.player_id);
    if (kind === "goal" || kind === "penalty") m.goals += 1;
    else if (kind === "ownGoal") m.ownGoals += 1;
    else if (kind === "yellow") m.yellow = true;
    else if (kind === "red" || kind === "secondYellow") m.red = true;
    else if (kind === "sub") {
      const dir = subDirection(e, lineups);
      if (dir === "playerIn") m.subIn = minuteText(e.minute, e.extra_minute);
      if (dir === "playerOut") m.subOut = minuteText(e.minute, e.extra_minute);
    }
  }
  return out;
}

function Marks({ m }: { m: PlayerMarks | undefined }) {
  if (!m) return null;
  return (
    <span className="flex shrink-0 items-center gap-1 text-caption">
      {Array.from({ length: m.goals }, (_, i) => (
        <BallIcon key={`g${i}`} className="h-3.5 w-3.5 text-primary" />
      ))}
      {Array.from({ length: m.ownGoals }, (_, i) => (
        <BallIcon key={`o${i}`} className="h-3.5 w-3.5 text-negative" />
      ))}
      {m.yellow && !m.red ? <CardIcon tone="yellow" className="h-3 w-2" /> : null}
      {m.red ? (
        <CardIcon tone={m.yellow ? "second" : "red"} className={m.yellow ? "" : "h-3 w-2"} />
      ) : null}
      {m.subIn ? (
        <span className="numeric text-positive" title={t("match.events.subIn")}>
          ↑{m.subIn}
        </span>
      ) : null}
      {m.subOut ? (
        <span className="numeric text-negative" title={t("match.events.subOut")}>
          ↓{m.subOut}
        </span>
      ) : null}
      {m.goals || m.ownGoals || m.yellow || m.red || m.subIn || m.subOut ? (
        <span className="sr-only">
          {[
            m.goals ? t("match.players.goals", { count: m.goals }) : "",
            m.ownGoals ? t("match.events.ownGoal") : "",
            m.yellow && !m.red ? t("match.events.yellow") : "",
            m.red ? t("match.events.red") : "",
            m.subIn ? `${t("match.events.subIn")} ${m.subIn}` : "",
            m.subOut ? `${t("match.events.subOut")} ${m.subOut}` : "",
          ]
            .filter(Boolean)
            .join(", ")}
        </span>
      ) : null}
    </span>
  );
}

function PlayerRows({
  players,
  marks,
  ratings,
  lines,
  competition,
  admin,
}: {
  players: LineupPlayer[];
  marks: Map<number, PlayerMarks>;
  ratings: Map<number, number>;
  lines: Map<number, PlayerLine>;
  competition: string;
  admin: boolean;
}) {
  return (
    <ul className="divide-y divide-border/50">
      {players.map((p) => {
        const rating = ratings.get(p.provider_player_id) ?? null;
        return (
          <li
            key={p.provider_player_id}
            className="flex min-h-9 items-center gap-2.5 py-1.5 text-sm pointer-coarse:min-h-[2.8125rem] pointer-coarse:py-0"
          >
            <span className="numeric w-6 shrink-0 text-right text-xs text-subtle-foreground">
              {p.number ?? "—"}
            </span>
            <PlayerPhoto src={p.photo_url} name={p.name ?? "?"} size={22} />
            <PlayerSummary
              name={p.name}
              photo={p.photo_url}
              position={p.position}
              season={p.season}
              competition={competition}
              line={lines.get(p.provider_player_id)}
              playerId={p.player_id}
              admin={admin}
              // Touch: the whole row's height answers (44 px); the name truncates inside, never the button.
              className="flex min-w-0 flex-1 items-center self-stretch"
            >
              <span className="block min-w-0 truncate">
                {p.name ?? t("match.events.unknownPlayer")}
              </span>
            </PlayerSummary>
            <Marks m={p.player_id !== null ? marks.get(p.player_id) : undefined} />
            {rating !== null ? (
              <RatingBadge value={rating} className="min-w-[2.2rem] text-[0.7rem]" />
            ) : null}
            <span className="w-9 shrink-0 text-right text-caption font-medium text-muted-foreground">
              {position(p.position)}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function TeamSheet({
  lineup,
  team,
  side,
  marks,
  ratings,
  lines,
  competition,
  admin,
}: {
  lineup: TeamLineup | undefined;
  team: TeamRef;
  side: Side;
  marks: Map<number, PlayerMarks>;
  ratings: Map<number, number>;
  lines: Map<number, PlayerLine>;
  competition: string;
  admin: boolean;
}) {
  const xi = lineup ? starters(lineup) : [];
  const subs = lineup ? bench(lineup) : [];
  return (
    <Block
      title={<TeamName name={team.name} logo={team.logo_url} size={22} strong />}
      right={
        lineup?.formation ? (
          <span
            className={cn(
              "numeric rounded-md border px-1.5 py-0.5 text-xs font-semibold",
              side === "home"
                ? "border-primary/40 bg-primary/10 text-primary"
                : "border-info/40 bg-info-soft text-info",
            )}
          >
            {lineup.formation}
          </span>
        ) : null
      }
    >
      {!lineup ? (
        <p className="text-sm text-muted-foreground">{t("match.lineups.unavailable")}</p>
      ) : (
        <div className="space-y-3">
          {lineup.coach ? (
            <p
              className="flex items-center gap-2 text-caption text-muted-foreground"
              data-testid="lineup-coach"
            >
              <PlayerPhoto src={lineup.coach_photo_url} name={lineup.coach} size={22} />
              {t("match.lineups.coach", { name: lineup.coach })}
            </p>
          ) : null}
          <div>
            <h3 className="mb-0.5 text-label text-subtle-foreground">
              {t("match.lineups.starters", { count: xi.length })}
            </h3>
            <PlayerRows
              players={xi}
              marks={marks}
              ratings={ratings}
              lines={lines}
              competition={competition}
              admin={admin}
            />
          </div>
          <div>
            <h3 className="mb-0.5 text-label text-subtle-foreground">
              {t("match.lineups.bench", { count: subs.length })}
            </h3>
            {subs.length ? (
              <PlayerRows
                players={subs}
                marks={marks}
                ratings={ratings}
                lines={lines}
                competition={competition}
                admin={admin}
              />
            ) : (
              <p className="py-1.5 text-xs text-muted-foreground">{t("match.lineups.noBench")}</p>
            )}
          </div>
        </div>
      )}
    </Block>
  );
}

function ratingMap(players: PlayerLine[]): Map<number, number> {
  const out = new Map<number, number>();
  for (const p of players) {
    const r = toNumber(p.rating);
    if (r !== null && r > 0 && (p.minutes ?? 0) > 0) out.set(p.provider_player_id, r);
  }
  return out;
}

export function LineupsTab({ ctx }: { ctx: MatchCtx }) {
  const { match: m, center } = ctx;
  const c = center.data;
  const events = c?.events.status === "ok" ? c.events.data : [];
  const players = c?.players.status === "ok" ? c.players.data : [];
  const hasAbsences = c?.absences.status === "ok" && c.absences.data.length > 0;

  return (
    <div className="space-y-4">
      <CenterSection
        center={center}
        pick={(x) => x.lineups}
        skeleton={<div className="h-96 animate-pulse rounded-xl bg-muted/70" aria-hidden />}
        empty={(_, code) => (
          <Card>
            <EmptyState
              icon={<Shirt aria-hidden className="h-6 w-6" />}
              title={t("match.lineups.unavailable")}
              // The API says why for this moment: "about an hour before" is wrong 13 minutes before (REVIEW pt 7).
              body={sectionCodeText(code) ?? undefined}
            />
          </Card>
        )}
      >
        {(lineups) => {
          const home = lineups.find((l) => l.side === "home");
          const away = lineups.find((l) => l.side === "away");
          const marks = marksByPlayer(events, lineups);
          const ratings = ratingMap(players);
          const lines = new Map(players.map((pl) => [pl.provider_player_id, pl]));
          const sheet = (side: Side) => (
            <TeamSheet
              lineup={side === "home" ? home : away}
              team={side === "home" ? m.home : m.away}
              side={side}
              marks={marks}
              ratings={ratings}
              lines={lines}
              competition={m.competition.name}
              admin={ctx.showAdmin}
            />
          );
          const canDraw =
            home !== undefined &&
            away !== undefined &&
            pitchSpots(home, "bottom") !== null &&
            pitchSpots(away, "top") !== null;
          if (!canDraw || !home || !away) {
            return (
              <div className="grid items-start gap-4 md:grid-cols-2">
                <div className="min-w-0">{sheet("home")}</div>
                <div className="min-w-0">{sheet("away")}</div>
              </div>
            );
          }
          return (
            <div className="grid items-start gap-4 md:grid-cols-2 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)_minmax(0,1fr)] xl:grid-cols-[minmax(0,1fr)_minmax(0,25rem)_minmax(0,1fr)]">
              <div className="min-w-0 md:col-span-2 lg:order-2 lg:col-span-1">
                <Pitch
                  home={home}
                  away={away}
                  teams={{ home: m.home, away: m.away }}
                  ratings={ratings}
                />
              </div>
              <div className="min-w-0 lg:order-1">{sheet("home")}</div>
              <div className="min-w-0 lg:order-3">{sheet("away")}</div>
            </div>
          );
        }}
      </CenterSection>
      {hasAbsences ? <AbsencesBlock ctx={ctx} /> : null}
    </div>
  );
}
