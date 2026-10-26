/**
 * CALENDARIO Y DESCANSO (plan F4) - how much each team rested before this match and what it plays after it, in EVERY
 * competition it plays and not only the one of this match: a cup tie or a continental night three days ago weighs on
 * the legs as much as a league match does, and PrediGol follows only some of those competitions.
 *
 * The block says how sure it is. A side is "Completo" when the list the provider gives for the team was read lately and
 * no match is left unconfirmed; otherwise it is "Parcial", its rest is shown as "como máximo" and its matches as
 * "al menos", and a sentence names why (never read, read too long ago, a match nobody confirmed).
 *
 * It is context: days and matches, no price, no probability and no pick. The opponent and the score of a match already
 * played are shown here - facts of the past for a reader - which the AI's packet deliberately does not carry. Whether
 * users see the block at all is the owner's decision (the API answers `not_available` until then, and the block renders
 * nothing for them); the Admin Console's preview sees it either way.
 */
import { useId, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { CalendarDays, CircleCheck } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { formatDate, formatRelative } from "@/lib/time";
import { live } from "@/lib/api/v1/queries";
import { usePreviewParam } from "@/lib/auth/AuthProvider";
import type { CalendarMatch, MatchCalendar, TeamCalendar } from "@/lib/api/v1/types_calendar";
import { ShadowBadge } from "@/product/shared/Bits";
import { ErrorState, SkeletonBlock } from "@/product/shared/States";
import type { MatchCtx } from "./context";
import {
  CALENDAR_ID,
  calendarScreen,
  distanceText,
  fortnightText,
  incompleteNote,
  kindLabel,
  matchTitle,
  opponentText,
  outsideText,
  restText,
  type CalendarLoad,
} from "./calendar";

const COMPLETE_TAG = "border-positive/40 bg-positive-soft text-positive";
const PARTIAL_TAG = "border-border-strong bg-elevated text-muted-foreground";

function Tag({ tone, children }: { tone: string; children: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[0.7rem] font-semibold leading-tight",
        tone,
      )}
    >
      {children}
    </span>
  );
}

/** One match of a team: the competition and its kind, the rival and, for a match played, the score; how far from the page's match. */
function MatchRow({ match, ahead }: { match: CalendarMatch; ahead: boolean }) {
  const kind = kindLabel(match.competition_type);
  const rival = opponentText(match);
  return (
    <li
      data-testid={ahead ? "calendar-upcoming" : "calendar-recent"}
      data-followed={match.followed ? "true" : "false"}
      className="min-w-0 rounded-md border border-border/60 bg-card/60 px-2.5 py-1.5"
      title={formatDate(match.kickoff_at)}
    >
      <p className="flex flex-wrap items-baseline justify-between gap-x-3 text-xs">
        <span className="min-w-0 break-words font-medium">{matchTitle(match)}</span>
        <span className="numeric shrink-0 text-caption font-semibold text-muted-foreground">
          {distanceText(match, ahead)}
        </span>
      </p>
      <p className="mt-0.5 flex flex-wrap gap-x-2 text-caption text-muted-foreground">
        {kind ? <span data-testid="calendar-kind">{kind}</span> : null}
        {rival ? <span className="min-w-0 break-words">{rival}</span> : null}
        {match.result ? (
          <span data-testid="calendar-result" className="numeric font-semibold text-foreground">
            {match.result}
          </span>
        ) : null}
      </p>
    </li>
  );
}

function SideView({ side, which }: { side: TeamCalendar; which: "home" | "away" }) {
  const outside = outsideText(side);
  const note = incompleteNote(side);
  return (
    <section
      data-testid="calendar-side"
      data-side={which}
      data-complete={side.complete ? "true" : "false"}
      className="min-w-0 space-y-2.5 rounded-lg border border-border/70 bg-elevated/30 p-3"
    >
      <header className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <h3 className="min-w-0 break-words text-sm font-semibold">{side.team}</h3>
        <Tag tone={side.complete ? COMPLETE_TAG : PARTIAL_TAG}>
          {side.complete ? <CircleCheck aria-hidden className="h-3 w-3" /> : null}
          {side.complete ? t("match.calendar.complete") : t("match.calendar.partial")}
        </Tag>
      </header>
      <dl className="space-y-1 text-xs">
        <div className="flex flex-wrap gap-x-2">
          <dt className="text-muted-foreground">{t("match.calendar.rest")}</dt>
          <dd data-testid="calendar-rest" className="numeric min-w-0 break-words font-semibold">
            {restText(side)}
          </dd>
        </div>
        <div className="flex flex-wrap gap-x-2">
          <dt className="text-muted-foreground">{t("match.calendar.last14")}</dt>
          <dd
            data-testid="calendar-fortnight"
            className="numeric min-w-0 break-words font-semibold"
          >
            {fortnightText(side)}
            {outside ? (
              <span className="font-normal text-muted-foreground"> · {outside}</span>
            ) : null}
          </dd>
        </div>
      </dl>
      <div className="space-y-1.5">
        <h4 className="text-caption font-semibold text-muted-foreground">
          {t("match.calendar.playedTitle")}
        </h4>
        {side.recent.length === 0 ? (
          <p className="text-caption text-subtle-foreground">{t("match.calendar.playedNone")}</p>
        ) : (
          <ul className="space-y-1.5">
            {side.recent.map((m) => (
              <MatchRow key={m.provider_fixture_id} match={m} ahead={false} />
            ))}
          </ul>
        )}
      </div>
      <div className="space-y-1.5">
        <h4 className="text-caption font-semibold text-muted-foreground">
          {t("match.calendar.nextTitle")}
        </h4>
        {side.upcoming.length === 0 ? (
          <p className="text-caption text-subtle-foreground" data-testid="calendar-next-none">
            {side.complete ? t("match.calendar.nextNone") : t("match.calendar.nextNoneUnknown")}
          </p>
        ) : (
          <ul className="space-y-1.5">
            {side.upcoming.map((m) => (
              <MatchRow key={m.provider_fixture_id} match={m} ahead />
            ))}
          </ul>
        )}
      </div>
      {note ? (
        <p data-testid="calendar-note" className="text-caption leading-snug text-subtle-foreground">
          {note}
        </p>
      ) : null}
    </section>
  );
}

function Footnote({ data }: { data: MatchCalendar }) {
  const read = [data.home.fetched_at, data.away.fetched_at].filter((x): x is string => !!x).sort();
  const oldest = read[0];
  return (
    <p className="text-caption leading-snug text-subtle-foreground">
      {t(data.complete ? "match.calendar.footnote" : "match.calendar.footnotePartial")}
      {oldest ? <span> · {t("match.calendar.read", { when: formatRelative(oldest) })}</span> : null}
    </p>
  );
}

// ── the block ───────────────────────────────────────────────────────────────

/**
 * The block from an answer of the API. Apart from the query so that it can be rendered from a fixture: `preview` is
 * the Admin Console's shadow preview, the only view that sees the states a user is spared (loading, error, nothing yet).
 */
export function CalendarView({ load, preview }: { load: CalendarLoad; preview: boolean }) {
  const titleId = useId();
  const screen = calendarScreen(load, preview);
  if (screen.kind === "nothing") return null;
  return (
    <section
      id={CALENDAR_ID}
      aria-labelledby={titleId}
      data-testid="calendar-block"
      data-screen={screen.kind}
      data-preview={preview ? "true" : "false"}
      className={cn(
        "min-w-0 scroll-mt-20 rounded-xl border border-border bg-card",
        preview && "border-info/40",
      )}
    >
      <header className="flex items-start justify-between gap-3 px-4 pt-3.5">
        <div className="min-w-0">
          <h2
            id={titleId}
            className="flex items-center gap-2 font-display text-[0.95rem] font-bold uppercase tracking-[0.08em]"
          >
            <CalendarDays aria-hidden className="h-4 w-4 shrink-0 text-primary" />
            <span className="min-w-0 break-words">{t("match.calendar.title")}</span>
          </h2>
          <p className="mt-0.5 text-xs text-muted-foreground">{t("match.calendar.subtitle")}</p>
        </div>
        {preview ? <ShadowBadge compact /> : null}
      </header>
      <div className="space-y-3 px-4 pb-4 pt-3">
        {screen.kind === "loading" ? <SkeletonBlock className="h-40" /> : null}
        {screen.kind === "error" ? (
          <ErrorState error={screen.error} onRetry={screen.retry} className="py-5" />
        ) : null}
        {screen.kind === "none" ? (
          <p className="text-sm text-muted-foreground" data-empty-state data-testid="calendar-none">
            {t("match.note.notAvailable")}
          </p>
        ) : null}
        {screen.kind === "calendar" ? (
          <>
            <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-1">
              <SideView side={screen.data.home} which="home" />
              <SideView side={screen.data.away} which="away" />
            </div>
            <Footnote data={screen.data} />
          </>
        ) : null}
      </div>
    </section>
  );
}

/** The Resumen's block: loads the calendar for the signed-in view (a user's, or the Admin Console's preview). */
export function CalendarBlock({ ctx }: { ctx: MatchCtx }) {
  const shadow = usePreviewParam();
  const q = useQuery(live.matchCalendar(ctx.fixtureId, shadow));
  const load: CalendarLoad = q.isPending
    ? { status: "pending" }
    : q.isError
      ? { status: "error", error: q.error, retry: () => void q.refetch() }
      : { status: "success", envelope: q.data };
  return <CalendarView load={load} preview={shadow === "shadow"} />;
}
