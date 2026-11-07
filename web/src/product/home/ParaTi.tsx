/**
 * «Para ti» and the frame of Inicio's two layers (closing plan 3.2; plan UX, A13 and section 38): what the reader chose to
 * follow - the players with the state of the next match of his team, which of the day's published picks are of their matches
 * or markets (or that none is) and their notices - and the bands that tell the two layers apart. Their matches, news, what is at
 * stake and results are Inicio's own blocks (./TodayBlocks, ./NewsBlock), which sit in this layer once the reader's leagues and
 * teams are their own.
 *
 * Every part is a fact of the reader's favourites or of the data, never a number of PrediGol's: the picks are the day's, drawn
 * once by the card Inicio already shows (GET /daily) - here they are only picked out by rank. A part with nothing to tell stays
 * out; a failure shows with its reference and a retry, never as an empty list.
 */
import { Link } from "@tanstack/react-router";
import type { UseQueryResult } from "@tanstack/react-query";
import { Bell, Pencil, Star, Target, User, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { TeamLogo } from "@/components/football/Logos";
import { t } from "@/lib/i18n";
import { formatKickoff, formatTime, getTimeZone, relativeDay } from "@/lib/time";
import { cn } from "@/lib/utils";
import type { Envelope } from "@/lib/api/v1/types";
import type { MeToday, PlayerState, RelatedPick, WatchedPlayer } from "@/lib/api/v1/types_me_today";
import type { DailyBoard, DailyItem } from "@/lib/api/v1/types_records";
import { positionLabel } from "@/live/labels";
import { WhyChip } from "@/product/favorites/WhyChip";
import { DailyItemCard } from "@/product/records/DailyItemCard";
import { marketName } from "@/product/shared/markets";
import { stateText } from "./playerState";
import { relatedCards } from "./related";
import { Card, ErrorState, SectionHeader, SkeletonBlock, StaleNote } from "@/product/shared/States";

export type MeQuery = UseQueryResult<MeToday>;
type BoardQuery = UseQueryResult<Envelope<DailyBoard>>;

/** The favourites page: «Tu fútbol» in the profile. */
function EditLink({ label, testId }: { label: string; testId: string }) {
  return (
    <Link
      to="/profile"
      hash="football"
      data-testid={testId}
      className="tap-y relative inline-flex min-h-9 shrink-0 items-center gap-1 rounded-md px-2 text-xs font-medium text-primary hover:bg-primary/10"
    >
      <Pencil aria-hidden className="h-3.5 w-3.5" />
      {label}
    </Link>
  );
}

/**
 * One of Inicio's two layers: a landmark named by its band (the blocks inside keep their own headings). «Para ti» carries the
 * way to change the favourites; «PrediGol» says it is the same for everyone.
 */
export function Layer({
  id,
  title,
  hint,
  tone,
  action,
  children,
}: {
  id: "for-you" | "predigol";
  title: string;
  hint: string;
  tone: "primary" | "gold";
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section
      aria-labelledby={`layer-${id}`}
      data-testid={`layer-${id}`}
      className="space-y-9 sm:space-y-10"
    >
      <div
        className="flex items-end justify-between gap-3 border-b border-border pb-2"
        data-guide={`layer-${id}`}
      >
        <div className="min-w-0">
          <p
            id={`layer-${id}`}
            className={cn(
              "font-display text-xs font-bold uppercase tracking-[0.14em]",
              tone === "gold" ? "text-gold" : "text-primary",
            )}
          >
            {title}
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

export function ForYouEdit() {
  return <EditLink label={t("home.layers.edit")} testId="layer-edit" />;
}

/** Where a reader's «cerrar» of the line is kept (this browser only): it is a convenience, never state that matters. */
export const CHOOSE_CLOSED_KEY = "predigol.home.chooseClosed";

/**
 * Without favourites: one discreet line to choose them (plan de Inicio, 3.2) - the product is whole without them, so it can be
 * closed, and stays closed on this browser. It shows from the first paint and goes away once the reader's choice is read.
 */
export function ChoosePrompt() {
  const [closed, setClosed] = useState(false);
  useEffect(() => {
    try {
      if (window.localStorage.getItem(CHOOSE_CLOSED_KEY) === "1") setClosed(true);
    } catch {
      /* storage unavailable: the line shows */
    }
  }, []);
  if (closed) return null;
  const close = () => {
    setClosed(true);
    try {
      window.localStorage.setItem(CHOOSE_CLOSED_KEY, "1");
    } catch {
      /* storage unavailable: it closes for this visit only */
    }
  };
  return (
    <aside
      data-testid="choose-prompt"
      className="flex items-center gap-2.5 rounded-xl border border-dashed border-border-strong py-1 pl-3.5 pr-1"
    >
      <Star aria-hidden className="h-4 w-4 shrink-0 text-primary" />
      <p className="min-w-0 flex-1 text-sm leading-snug">
        <span className="font-semibold">{t("home.choose.title")}</span>
        <span className="hidden text-muted-foreground sm:inline"> · {t("home.choose.body")}</span>
      </p>
      <Link
        to="/profile"
        hash="football"
        data-testid="choose-prompt-link"
        className="tap-y relative inline-flex min-h-9 shrink-0 items-center rounded-md px-1.5 text-sm font-medium text-primary hover:underline"
      >
        {t("home.choose.action")}
      </Link>
      <button
        type="button"
        onClick={close}
        data-testid="choose-prompt-close"
        aria-label={t("common.close")}
        className="tap-y relative flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-elevated hover:text-foreground"
      >
        <X aria-hidden className="h-4 w-4" />
      </button>
    </aside>
  );
}

const TONE: Readonly<Record<PlayerState, string>> = {
  starter: "border-positive/40 bg-positive-soft text-positive",
  bench: "border-info/30 bg-info-soft text-info",
  left_out: "border-warning/40 bg-warning-soft text-warning",
  absent: "border-destructive/40 bg-destructive/10 text-destructive",
  doubtful: "border-warning/40 bg-warning-soft text-warning",
  waiting: "border-border bg-elevated/60 text-muted-foreground",
  no_match: "border-border bg-elevated/60 text-muted-foreground",
};

function PlayerRow({ p, now }: { p: WatchedPlayer; now: number }) {
  const body = (
    <>
      <span aria-hidden className="mt-0.5 shrink-0">
        {p.team ? (
          <TeamLogo src={p.team.logo_url} name={p.team.name} size={28} />
        ) : (
          <User className="h-7 w-7 text-subtle-foreground" />
        )}
      </span>
      <div className="min-w-0 flex-1 space-y-1">
        <p className="flex min-w-0 items-baseline gap-2">
          <span className="min-w-0 truncate text-sm font-medium">{p.name}</span>
          {p.position ? (
            <span className="shrink-0 text-caption text-muted-foreground">
              {positionLabel(p.position)}
            </span>
          ) : null}
        </p>
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-caption">
          <span
            data-testid="player-state"
            data-state={p.state}
            className={cn(
              "max-w-full truncate rounded-full border px-2 py-px font-medium",
              TONE[p.state],
            )}
          >
            {stateText(p)}
          </span>
          {p.next ? (
            <span className="min-w-0 truncate text-muted-foreground" data-testid="player-next">
              {t("home.players.next", {
                home: p.next.home.name,
                away: p.next.away.name,
                when: formatKickoff(p.next.kickoff_at, getTimeZone(), now),
              })}
            </span>
          ) : null}
        </div>
      </div>
    </>
  );
  const cls = "flex h-full items-start gap-3 px-4 py-3 sm:px-5";
  return p.next ? (
    <Link
      to="/matches/$fixtureId"
      params={{ fixtureId: String(p.next.fixture_id) }}
      hash="lineups"
      data-testid="player-row"
      data-player={p.id}
      className={cn(
        cls,
        "transition-colors hover:bg-elevated/50 focus-visible:bg-elevated/60 focus-visible:outline-none",
      )}
    >
      {body}
    </Link>
  ) : (
    <div data-testid="player-row" data-player={p.id} className={cls}>
      {body}
    </div>
  );
}

/** Tus jugadores: the players the reader follows, in the order they chose them, each with what his next match says. */
export function PlayersBlock({ players, now }: { players: WatchedPlayer[]; now: number }) {
  if (players.length === 0) return null;
  return (
    <section data-testid="home-players">
      <SectionHeader
        title={t("home.players.title")}
        subtitle={t("home.players.subtitle")}
        icon={<User aria-hidden className="h-4 w-4 shrink-0 text-primary" />}
      />
      <Card className="mt-3 overflow-hidden">
        <ul className="grid grid-cols-1 gap-px bg-border/70 lg:grid-cols-2">
          {players.map((p) => (
            <li key={p.id} className="bg-card">
              <PlayerRow p={p} now={now} />
            </li>
          ))}
          {players.length % 2 === 1 ? <li aria-hidden className="hidden bg-card lg:block" /> : null}
        </ul>
      </Card>
      <p className="mt-2 text-caption text-subtle-foreground">{t("home.players.note")}</p>
    </section>
  );
}

function Note({ children, testId }: { children: ReactNode; testId: string }) {
  return (
    <p
      data-empty-state
      data-testid={testId}
      className="mt-3 flex items-start gap-2.5 rounded-xl border border-border bg-card px-4 py-3 text-sm text-muted-foreground"
    >
      <Target aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-subtle-foreground" />
      <span className="min-w-0">{children}</span>
    </p>
  );
}

/** The card of a pick of the day and why it is the reader's: their team or league, or a market they follow. */
function RelatedPickCard({ related, item }: { related: RelatedPick; item: DailyItem }) {
  return (
    <li
      data-testid="related-pick"
      data-rank={related.rank}
      className="min-w-0 space-y-1.5 text-caption"
    >
      <div className="flex min-w-0 flex-wrap items-center gap-1.5">
        {related.followed ? (
          <WhyChip why={related.followed} testId="related-why" className="max-w-full text-micro" />
        ) : null}
        {related.market_followed ? (
          <span
            data-testid="related-market"
            className="min-w-0 max-w-full truncate rounded-full border border-primary/30 bg-primary/10 px-2 py-px text-micro font-medium text-primary"
          >
            {t("home.related.market", { market: marketName(related.market_key) })}
          </span>
        ) : null}
      </div>
      <DailyItemCard item={item} compact />
    </li>
  );
}

/**
 * Picks de tus partidos: the day's published picks that are of the reader's teams, leagues or markets - the very cards the day's
 * picks show, picked out by rank. None is theirs, or the day has none: it says so, and never fills the place.
 */
export function RelatedPicksBlock({ me, board }: { me: MeToday; board: BoardQuery }) {
  const picks = me.picks;
  if (!picks) return null;
  let body: ReactNode;
  if (picks.published === 0) {
    body = <Note testId="related-none-day">{t("home.related.noDay")}</Note>;
  } else if (picks.items.length === 0) {
    body = <Note testId="related-none">{t("home.related.none", { count: picks.published })}</Note>;
  } else if (board.isError && !board.data) {
    body = (
      <Card className="mt-3">
        <ErrorState error={board.error} onRetry={() => void board.refetch()} />
      </Card>
    );
  } else if (!board.data) {
    body = <SkeletonBlock className="mt-3 h-56 rounded-xl" />;
  } else {
    const shown = relatedCards(picks, board.data?.data?.set?.items ?? []);
    body =
      shown.length === 0 ? (
        <Note testId="related-none">{t("home.related.none", { count: picks.published })}</Note>
      ) : (
        <ul
          data-testid="related-list"
          className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3"
        >
          {shown.map(({ related, item }) => (
            <RelatedPickCard key={related.rank} related={related} item={item} />
          ))}
        </ul>
      );
  }
  return (
    <section data-testid="home-related">
      <SectionHeader
        title={t("home.related.title")}
        subtitle={t("home.related.subtitle")}
        icon={<Target aria-hidden className="h-4 w-4 shrink-0 text-primary" />}
        action={{ label: t("home.picks.seeAll"), to: "/picks" }}
      />
      {board.isError && board.data ? (
        <StaleNote className="mt-1" onRetry={() => void board.refetch()} />
      ) : null}
      {body}
    </section>
  );
}

const BELLS_SHOWN = 3;

/** Tus avisos: the bells the reader rang for matches to come and whether the line-ups of their teams can reach them. */
export function NoticesBlock({
  me,
  teams,
  now,
}: {
  me: MeToday;
  /** The reader follows a team: the line-up notices are about teams. */
  teams: boolean;
  now: number;
}) {
  const n = me.notices;
  if (!n) return null;
  const status =
    !n.available || !teams
      ? null
      : n.devices === 0
        ? "noDevice"
        : n.lineup
          ? "lineupOn"
          : "lineupOff";
  const bells = n.bells.slice(0, BELLS_SHOWN);
  if (bells.length === 0 && status === null) return null;
  return (
    <section data-testid="home-notices">
      <SectionHeader
        title={t("home.notices.title")}
        subtitle={t("home.notices.subtitle")}
        icon={<Bell aria-hidden className="h-4 w-4 shrink-0 text-primary" />}
      />
      {status ? (
        <p
          className="mt-3 text-sm text-muted-foreground"
          data-testid="notices-status"
          data-status={status}
        >
          {t(`home.notices.${status}`)}{" "}
          {status !== "lineupOn" ? (
            <Link
              to="/profile"
              hash="notifications"
              data-testid="notices-link"
              className="tap-y relative inline-flex items-center font-medium text-primary hover:underline"
            >
              {t(status === "noDevice" ? "home.notices.enable" : "home.notices.manage")}
            </Link>
          ) : null}
        </p>
      ) : null}
      {bells.length > 0 ? (
        <Card className="mt-3 overflow-hidden">
          <ul className="divide-y divide-border/70" data-testid="notices-bells">
            {bells.map((b) => (
              <li key={b.fixture_id} className="bg-card">
                <Link
                  to="/matches/$fixtureId"
                  params={{ fixtureId: String(b.fixture_id) }}
                  data-testid="notices-bell"
                  className="flex items-start gap-3 px-4 py-3 text-sm transition-colors hover:bg-elevated/50 focus-visible:bg-elevated/60 focus-visible:outline-none sm:px-5"
                >
                  <Bell aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-subtle-foreground" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">
                      {b.home.name} – {b.away.name}
                    </span>
                    <span className="block text-caption text-muted-foreground">
                      {t("home.notices.bell", {
                        minutes: t(`push.bell.minutes.${b.minutes_before}`),
                        when:
                          relativeDay(b.kickoff_at, getTimeZone(), now) === null
                            ? formatKickoff(b.kickoff_at, getTimeZone(), now)
                            : formatTime(b.kickoff_at),
                      })}
                    </span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
      {n.bells.length > BELLS_SHOWN ? (
        <p className="mt-2 text-caption text-subtle-foreground" data-testid="notices-more">
          {t("home.notices.more", { count: n.bells.length - BELLS_SHOWN })}
        </p>
      ) : null}
    </section>
  );
}

export type ForYouPartName = "players" | "picks" | "notices";

/**
 * One of the parts of «Para ti» that /me/today feeds - players, picks, notices - each placed where Inicio wants it. While the
 * answer loads or fails, the picks part - the one that always has something to say - shows the skeleton or the failure with its
 * reference and a retry; the others stay out (never an empty list standing for a failure).
 */
export function ForYouPart({
  part,
  query,
  board,
  teams,
  now,
}: {
  part: ForYouPartName;
  query: MeQuery;
  board: BoardQuery;
  /** The reader follows a team: the line-up notices are about teams. */
  teams: boolean;
  now: number;
}) {
  const me = query.data;
  if (!me) {
    if (part !== "picks") return null;
    // Not asked for (the query is off for the owner, who has no favourites): nothing to wait for, so no skeleton (plan Inicio, 1.4).
    if (query.isPending && query.fetchStatus === "idle") return null;
    return query.isPending ? (
      <div aria-busy="true" aria-label={t("common.loading")}>
        <SkeletonBlock className="h-24 rounded-xl" />
      </div>
    ) : (
      <Card data-testid="for-you-failed">
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      </Card>
    );
  }
  if (part === "players") return <PlayersBlock players={me.players} now={now} />;
  if (part === "picks") return <RelatedPicksBlock me={me} board={board} />;
  return <NoticesBlock me={me} teams={teams} now={now} />;
}
