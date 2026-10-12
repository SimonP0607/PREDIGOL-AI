/** Goals, cards, substitutions and VAR: home on the left, away on the right, minute between. */
import type { ReactNode } from "react";
import { ArrowDown, ArrowLeftRight, ArrowUp, CircleDot, MonitorPlay, Timer } from "lucide-react";
import { cn } from "@/lib/utils";
import { t, translateOr } from "@/lib/i18n";
import type { MatchEvent, TeamLineup } from "@/lib/api/v1/types_center";
import type { MatchCtx } from "./context";
import {
  eventKind,
  halfTimeFromStates,
  minuteText,
  reachedExtraTime,
  reachedHalfTime,
  subDirection,
  timeline,
  type EventKind,
  type Goals,
  type TimelineItem,
} from "./model";
import { BallIcon, Block, CardIcon, CenterSection, PlayerName } from "./ui";

function slug(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "");
}

function Glyph({ kind }: { kind: EventKind }) {
  switch (kind) {
    case "goal":
    case "penalty":
      return <BallIcon className="text-primary" />;
    case "ownGoal":
      return <BallIcon className="text-negative" />;
    case "missedPenalty":
      return <BallIcon className="text-subtle-foreground opacity-70" />;
    case "yellow":
      return <CardIcon tone="yellow" />;
    case "red":
      return <CardIcon tone="red" />;
    case "secondYellow":
      return <CardIcon tone="second" />;
    case "sub":
      return <ArrowLeftRight aria-hidden className="h-4 w-4 shrink-0 text-info" />;
    case "var":
      return <MonitorPlay aria-hidden className="h-4 w-4 shrink-0 text-info" />;
    default:
      return <CircleDot aria-hidden className="h-4 w-4 shrink-0 text-subtle-foreground" />;
  }
}

/** A card's reason, only when we know how to say it in the reader's language. */
function cardReason(e: MatchEvent): string {
  return e.comments ? translateOr(`match.events.comment.${slug(e.comments)}`, "") : "";
}

function varDetail(e: MatchEvent): string {
  return e.detail
    ? translateOr(`match.events.varDetail.${slug(e.detail)}`, t("match.events.varReview"))
    : t("match.events.varReview");
}

function Line({
  icon,
  label,
  children,
  muted = false,
  align,
}: {
  icon: ReactNode;
  /** Read out instead of the arrow. */
  label: string;
  children: ReactNode;
  muted?: boolean;
  align: "left" | "right";
}) {
  return (
    <span
      className={cn(
        "flex min-w-0 items-center gap-1",
        align === "right" && "flex-row-reverse",
        // text-caption is not merge-safe in cn(): spelled out here.
        muted ? "text-[0.6875rem] leading-4 text-muted-foreground" : "text-sm font-medium",
      )}
    >
      {icon}
      <span className="min-w-0 break-words leading-tight">
        <span className="sr-only">{label}: </span>
        {children}
      </span>
    </span>
  );
}

function EventContent({
  e,
  running,
  align,
  lineups,
  admin,
}: {
  e: MatchEvent;
  running: Goals | null;
  align: "left" | "right";
  lineups: TeamLineup[] | null;
  admin: boolean;
}) {
  const kind = eventKind(e);
  const player = <PlayerName name={e.player} id={e.player_id} admin={admin} />;
  let main: ReactNode = player;
  let sub: ReactNode = null;

  if (kind === "goal") {
    sub = e.assist ? t("match.events.assist", { name: e.assist }) : t("match.events.goal");
  } else if (kind === "penalty") {
    sub = t("match.events.penalty");
  } else if (kind === "ownGoal") {
    sub = t("match.events.ownGoal");
  } else if (kind === "missedPenalty") {
    sub = t("match.events.missedPenalty");
  } else if (kind === "yellow" || kind === "red" || kind === "secondYellow") {
    const reason = cardReason(e);
    sub = `${t(`match.events.${kind}`)}${reason ? ` · ${reason}` : ""}`;
  } else if (kind === "var") {
    main = e.player ? player : t("match.events.var");
    sub = e.player ? `${t("match.events.var")} · ${varDetail(e)}` : varDetail(e);
  } else if (kind === "sub") {
    const dir = subDirection(e, lineups);
    const inName = dir === "playerOut" ? e.assist : e.player;
    const outName = dir === "playerOut" ? e.player : e.assist;
    if (dir === null) {
      sub = e.assist ? t("match.events.subWith", { name: e.assist }) : t("match.events.sub");
    } else {
      const inNode =
        dir === "playerIn" ? player : <span>{inName ?? t("match.events.unknownPlayer")}</span>;
      const outNode =
        dir === "playerOut" ? player : <span>{outName ?? t("match.events.unknownPlayer")}</span>;
      return (
        <div className={cn("min-w-0", align === "right" && "text-right")}>
          <span className="sr-only">{t("match.events.sub")}. </span>
          <Line
            align={align}
            label={t("match.events.subIn")}
            icon={<ArrowUp aria-hidden className="h-3.5 w-3.5 shrink-0 text-positive" />}
          >
            {inNode}
          </Line>
          <Line
            align={align}
            muted
            label={t("match.events.subOut")}
            icon={<ArrowDown aria-hidden className="h-3.5 w-3.5 shrink-0 text-negative" />}
          >
            {outNode}
          </Line>
        </div>
      );
    }
  } else {
    main = e.player ? player : e.type;
    sub = e.detail;
  }

  return (
    <div
      className={cn(
        "flex min-w-0 items-center gap-2",
        align === "right" && "flex-row-reverse text-right",
      )}
    >
      <Glyph kind={kind} />
      <div className="min-w-0">
        <div
          className={cn(
            "flex min-w-0 items-center gap-1.5",
            align === "right" && "flex-row-reverse",
          )}
        >
          <span className="min-w-0 break-words text-[0.8125rem] font-medium leading-tight sm:text-sm">
            {main}
          </span>
          {running ? (
            <span className="numeric shrink-0 rounded bg-primary/15 px-1 text-[0.7rem] font-semibold text-primary">
              {running.home}–{running.away}
            </span>
          ) : null}
        </div>
        {sub ? (
          <div className="mt-0.5 break-words text-caption text-muted-foreground">{sub}</div>
        ) : null}
      </div>
    </div>
  );
}

function Divider({ item }: { item: Extract<TimelineItem, { kind: "divider" }> }) {
  return (
    <li className="relative flex items-center gap-3 py-2.5">
      <span aria-hidden className="h-px flex-1 bg-border" />
      <span className="numeric relative z-10 rounded-full border border-border-strong bg-elevated px-2.5 py-0.5 text-[0.7rem] font-semibold uppercase tracking-wider text-muted-foreground">
        {t(`match.events.divider.${item.label}`)}
        {item.score ? ` · ${item.score.home}–${item.score.away}` : ""}
      </span>
      <span aria-hidden className="h-px flex-1 bg-border" />
    </li>
  );
}

function Timeline({
  ctx,
  events,
  newestFirst,
}: {
  ctx: MatchCtx;
  events: MatchEvent[];
  newestFirst: boolean;
}) {
  const { match: m, phase, center } = ctx;
  const c = center.data;
  const lineups = c?.lineups.status === "ok" ? c.lineups.data : null;
  const states = c?.live_states.status === "ok" ? c.live_states.data : [];
  const status = ctx.live?.status ?? m.status_short;
  const halfTime: Goals | null =
    m.score && m.score.ht_home !== null && m.score.ht_away !== null
      ? { home: m.score.ht_home, away: m.score.ht_away }
      : halfTimeFromStates(states);
  const items = timeline(events, {
    score: ctx.score,
    halfTime,
    reachedHalfTime: reachedHalfTime(phase, status),
    reachedExtraTime: reachedExtraTime(m, status),
    finished: phase === "finished",
    newestFirst,
  });

  return (
    <ol className="relative" aria-label={t("match.events.title")}>
      <span
        aria-hidden
        className="absolute bottom-3 left-1/2 top-3 w-px -translate-x-1/2 bg-border/80"
      />
      {items.map((it) => {
        if (it.kind === "divider") return <Divider key={`div-${it.label}`} item={it} />;
        const e = it.event;
        const minute = (
          <span className="numeric relative z-10 whitespace-nowrap rounded-full border border-border-strong bg-card px-1.5 py-0.5 text-[0.7rem] font-semibold text-muted-foreground">
            {minuteText(e.minute, e.extra_minute)}
          </span>
        );
        const content = (align: "left" | "right") => (
          <EventContent
            e={e}
            running={it.running}
            align={align}
            lineups={lineups}
            admin={ctx.showAdmin}
          />
        );
        if (e.side === null) {
          return (
            <li key={e.seq} className="relative flex flex-col items-center gap-1 py-2 text-center">
              {minute}
              <div className="rounded-lg bg-card px-2">{content("left")}</div>
            </li>
          );
        }
        return (
          <li
            key={e.seq}
            className="relative grid grid-cols-[minmax(0,1fr)_3rem_minmax(0,1fr)] items-center gap-1 py-1.5 sm:grid-cols-[minmax(0,1fr)_3.5rem_minmax(0,1fr)] sm:gap-3"
          >
            <div className="min-w-0">{e.side === "home" ? content("right") : null}</div>
            <div className="flex justify-center">{minute}</div>
            <div className="min-w-0">{e.side === "away" ? content("left") : null}</div>
          </li>
        );
      })}
    </ol>
  );
}

export function EventsBlock({ ctx }: { ctx: MatchCtx }) {
  const newestFirst = ctx.phase === "live";
  return (
    <Block
      title={t("match.events.title")}
      icon={<Timer />}
      right={
        newestFirst ? (
          <span className="text-caption text-subtle-foreground">
            {t("match.events.newestFirst")}
          </span>
        ) : null
      }
    >
      <CenterSection center={ctx.center} pick={(c) => c.events}>
        {(events) => <Timeline ctx={ctx} events={events} newestFirst={newestFirst} />}
      </CenterSection>
    </Block>
  );
}
