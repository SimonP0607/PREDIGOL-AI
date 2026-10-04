/**
 * Mis picks: how it went (today, 7 days, 30 days, everything - PrediGol's picks and parlays
 * next to the user's own), the picks the user saved, and the parlays they built. Profit is
 * in units of one stake: PrediGol handles no money.
 */
import { useState, type FormEvent, type ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Bookmark, Layers, LineChart, Pencil, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { fmtInt, fmtOdds, fmtPct, localFixed, toNumber } from "@/lib/i18n/format";
import { formatKickoff, formatRelative } from "@/lib/time";
import { v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type { HistoryGroup, HistoryPeriod, UserParlay, UserPick } from "@/lib/api/v1/types_records";
import { useAuth, usePreviewParam } from "@/lib/auth/AuthProvider";
import { CompetitionTag, TeamName } from "@/components/football/Logos";
import { OddsPill } from "@/product/shared/Bits";
import {
  Card,
  EmptyState,
  ErrorState,
  PageTitle,
  SectionHeader,
  SkeletonBlock,
  errorMessage,
} from "@/product/shared/States";
import { marketName, selectionLabel } from "@/product/shared/markets";
import { ChipGroup } from "@/product/picks/Controls";
import { EvaluationBadge, OriginLabel, ParlayStatusBadge, ResultBadge, Units } from "./Badges";
import { MatchScore } from "./DailyItemCard";
import { useRefreshMine } from "./hooks";
import { HISTORY_GROUPS, hasStarted } from "./model";
import { useSlip } from "./slipContext";

const PERIODS: readonly HistoryPeriod[] = ["today", "7d", "30d", "all"];

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: ReactNode;
  tone?: string | undefined;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-label leading-tight text-subtle-foreground">{label}</dt>
      <dd className={cn("numeric mt-1 text-sm font-semibold", tone)}>{value}</dd>
    </div>
  );
}

function GroupCard({ name, group }: { name: string; group: HistoryGroup }) {
  const roi = group.roi;
  return (
    <Card className="p-4" as="article">
      <h3 className="font-display text-sm font-semibold" data-testid={`history-group-title`}>
        {t(`records.mine.results.group.${name}`)}
      </h3>
      <div className="mt-2 flex items-baseline justify-between gap-2">
        <span className="numeric text-2xl font-semibold" data-testid={`history-${name}-total`}>
          {fmtInt(group.total)}
        </span>
        <Units value={group.profit_units} className="text-sm" />
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2.5">
        <Stat
          label={t("records.labels.result")}
          value={t("records.mine.results.record", { won: group.won, lost: group.lost })}
        />
        <Stat label={t("records.mine.results.pending")} value={fmtInt(group.pending)} />
        <Stat label={t("records.mine.results.hitRate")} value={fmtPct(group.hit_rate, 0)} />
        <Stat
          label={t("records.mine.results.roi")}
          value={roi === null ? "—" : fmtPct(roi, 1)}
          tone={roi === null || roi === 0 ? undefined : roi > 0 ? "text-positive" : "text-negative"}
        />
      </dl>
    </Card>
  );
}

function Results() {
  const auth = useAuth();
  const preview = usePreviewParam();
  const [period, setPeriod] = useState<HistoryPeriod>("7d");
  const q = useQuery(live.history(period, preview));
  const history = q.data?.data;
  return (
    <section className="space-y-3" data-testid="my-results">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <SectionHeader
          title={t("records.mine.results.title")}
          icon={<LineChart aria-hidden className="h-4 w-4 text-primary" />}
        />
        <ChipGroup
          label={t("records.mine.results.periods")}
          value={period}
          options={PERIODS.map((p) => ({ value: p, label: t(`records.mine.results.period.${p}`) }))}
          onChange={setPeriod}
          testId="history-period"
        />
      </div>
      {history?.evaluation_mode ? <EvaluationBadge /> : null}
      {q.isPending ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {HISTORY_GROUPS.map((g) => (
            <SkeletonBlock key={g} className="h-40" />
          ))}
        </div>
      ) : q.isError ? (
        <Card>
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        </Card>
      ) : history ? (
        <>
          <div
            className={cn(
              "grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4",
              q.isFetching && "opacity-70",
            )}
          >
            {HISTORY_GROUPS.map((g) => (
              <GroupCard key={g} name={g} group={history.groups[g]} />
            ))}
          </div>
          {q.data?.status === "empty" ? (
            <p className="text-xs text-muted-foreground" data-testid="history-empty">
              {t("records.mine.results.empty")}
            </p>
          ) : null}
          <p className="text-caption text-subtle-foreground">
            {t("records.mine.results.note", { zone: auth.timeZone })}
          </p>
        </>
      ) : null}
    </section>
  );
}

/** The price the user got at their own bookmaker: added, changed or cleared before kick-off. */
function UserOddsForm({ pick, onDone }: { pick: UserPick; onDone: () => void }) {
  const refresh = useRefreshMine();
  const [text, setText] = useState(pick.user_odds ? localFixed(Number(pick.user_odds), 2) : "");
  const [invalid, setInvalid] = useState(false);
  const save = useMutation({
    mutationFn: (value: string | null) => v1.setPickOdds(pick.id, value),
    onSuccess: (_, value) => {
      toast.success(value === null ? t("records.toast.oddsCleared") : t("records.toast.oddsSaved"));
      void refresh();
      onDone();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const n = Number(text.replace(",", ".").trim());
    if (!Number.isFinite(n) || n <= 1 || n >= 1000) {
      setInvalid(true);
      return;
    }
    save.mutate(n.toFixed(3));
  };
  return (
    <form
      onSubmit={submit}
      className="mt-2 flex flex-wrap items-end gap-2"
      data-testid="user-odds-form"
    >
      <label className="min-w-[8rem] flex-1">
        <span className="text-label text-subtle-foreground">
          {t("records.mine.picks.oddsLabel")}
        </span>
        <input
          inputMode="decimal"
          value={text}
          autoFocus
          onChange={(e) => {
            setText(e.target.value);
            setInvalid(false);
          }}
          placeholder={t("records.mine.picks.oddsPlaceholder")}
          aria-invalid={invalid}
          data-testid="user-odds-input"
          className="numeric mt-1 h-9 w-full rounded-lg border border-border bg-background px-3 text-sm focus:border-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-ring aria-[invalid=true]:border-negative"
        />
      </label>
      <button
        type="submit"
        disabled={save.isPending}
        data-testid="user-odds-save"
        className="h-9 rounded-full bg-primary px-4 text-xs font-semibold text-primary-foreground disabled:opacity-50"
      >
        {t("records.mine.picks.saveOdds")}
      </button>
      {pick.user_odds ? (
        <button
          type="button"
          disabled={save.isPending}
          onClick={() => save.mutate(null)}
          className="h-9 rounded-full border border-border-strong px-3 text-xs font-medium text-muted-foreground hover:bg-elevated"
        >
          {t("records.mine.picks.clearOdds")}
        </button>
      ) : null}
      <button
        type="button"
        onClick={onDone}
        className="h-9 rounded-full px-3 text-xs font-medium text-muted-foreground hover:bg-elevated"
      >
        {t("records.mine.picks.cancel")}
      </button>
      {invalid ? (
        <p className="w-full text-xs text-negative">{t("records.mine.picks.oddsInvalid")}</p>
      ) : null}
    </form>
  );
}

function SavedPickRow({ pick }: { pick: UserPick }) {
  const refresh = useRefreshMine();
  const [editing, setEditing] = useState(false);
  const m = pick.match;
  const started = hasStarted(m);
  const open = pick.status === "PENDING" && !started;
  const remove = useMutation({
    mutationFn: () => v1.removePick(pick.id),
    onSuccess: () => {
      toast(t("records.toast.unsaved"));
      void refresh();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const label = selectionLabel({
    market_key: pick.market_key,
    selection: pick.selection,
    line: pick.line,
    home: m.home.name,
    away: m.away.name,
  });
  return (
    <li className="px-4 py-3.5 sm:px-5" data-testid="saved-pick" data-status={pick.status}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
          <OriginLabel origin="mine" />
          {pick.origin === "predigol_pick" ? <OriginLabel origin="predigol" /> : null}
        </div>
        <span className="text-caption text-subtle-foreground">
          {t("records.mine.picks.savedAt", { when: formatRelative(pick.saved_at) })}
        </span>
      </div>
      <div className="mt-2 grid grid-cols-[minmax(0,1fr)_auto] items-start gap-x-4 gap-y-2">
        <Link
          to="/matches/$fixtureId"
          params={{ fixtureId: String(m.fixture_id) }}
          className="min-w-0 rounded-md focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          <CompetitionTag
            name={m.competition.name}
            logo={m.competition.logo_url}
            flag={m.competition.flag_url}
            country={m.competition.country}
            className="min-w-0"
          />
          <div className="mt-1.5 flex min-w-0 items-center gap-2 text-sm">
            <TeamName
              name={m.home.name}
              logo={m.home.logo_url}
              size={18}
              strong
              className="min-w-0"
            />
            {m.score_home !== null && m.score_away !== null ? (
              <MatchScore home={m.score_home} away={m.score_away} />
            ) : (
              <span className="text-caption text-subtle-foreground">{t("common.vs")}</span>
            )}
            <TeamName
              name={m.away.name}
              logo={m.away.logo_url}
              size={18}
              strong
              className="min-w-0"
            />
          </div>
          <div className="mt-1 text-caption text-muted-foreground">
            <span className="numeric">{formatKickoff(m.kickoff_at)}</span> ·{" "}
            {marketName(pick.market_key)}
          </div>
          <div
            className="mt-0.5 font-display text-[0.95rem] font-semibold"
            data-testid="saved-pick-selection"
          >
            {label}
          </div>
        </Link>
        <div className="flex flex-col items-end gap-1 text-right">
          <span className="text-caption text-subtle-foreground">
            {t("records.mine.picks.shown")}
          </span>
          <OddsPill odds={pick.odds} size="sm" />
          {pick.bookmaker ? (
            <span className="max-w-[7rem] truncate text-caption text-muted-foreground">
              {pick.bookmaker}
            </span>
          ) : null}
          {pick.user_odds ? (
            <span className="text-caption text-primary" data-testid="saved-pick-user-odds">
              {t("records.mine.picks.yours")}{" "}
              <span className="numeric font-semibold">{fmtOdds(pick.user_odds)}</span>
            </span>
          ) : null}
        </div>
      </div>
      <div className="mt-2.5 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-caption text-subtle-foreground">{t("records.labels.result")}</span>
          <ResultBadge status={pick.status} />
          {pick.status !== "PENDING" ? (
            <Units value={pick.profit_units} className="text-xs" />
          ) : null}
        </div>
        {open && !editing ? (
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => setEditing(true)}
              data-testid="saved-pick-odds"
              className="inline-flex min-h-8 items-center gap-1 rounded-full border border-border-strong px-3 text-xs font-medium hover:bg-elevated"
            >
              <Pencil aria-hidden className="h-3 w-3" />
              {pick.user_odds
                ? t("records.mine.picks.editYours")
                : t("records.mine.picks.addYours")}
            </button>
            <button
              type="button"
              disabled={remove.isPending}
              onClick={() => remove.mutate()}
              data-testid="saved-pick-remove"
              className="inline-flex min-h-8 items-center gap-1 rounded-full border border-border-strong px-3 text-xs font-medium text-muted-foreground hover:bg-elevated hover:text-foreground disabled:opacity-50"
            >
              <Trash2 aria-hidden className="h-3 w-3" />
              {t("records.mine.picks.remove")}
            </button>
          </div>
        ) : null}
      </div>
      {open && editing ? <UserOddsForm pick={pick} onDone={() => setEditing(false)} /> : null}
    </li>
  );
}

function SavedPicks() {
  const q = useQuery(live.myPicks);
  const picks = q.data?.data ?? [];
  return (
    <section className="space-y-3" data-testid="saved-picks">
      <SectionHeader
        title={t("records.mine.picks.title")}
        subtitle={picks.length > 0 ? t("records.mine.picks.settlesAt") : undefined}
        icon={<Bookmark aria-hidden className="h-4 w-4 text-primary" />}
      />
      {q.isPending ? (
        <SkeletonBlock className="h-40" />
      ) : q.isError ? (
        <Card>
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        </Card>
      ) : picks.length === 0 ? (
        <Card>
          <EmptyState
            compact
            icon={<Bookmark aria-hidden className="h-5 w-5" />}
            title={t("records.mine.picks.empty")}
            body={t("records.mine.picks.emptyBody")}
          />
        </Card>
      ) : (
        <Card>
          <ul className="divide-y divide-border/70">
            {picks.map((p) => (
              <SavedPickRow key={p.id} pick={p} />
            ))}
          </ul>
        </Card>
      )}
    </section>
  );
}

function UserParlayCard({ parlay }: { parlay: UserParlay }) {
  const refresh = useRefreshMine();
  const settled = ["WON", "LOST", "VOID", "PARTIAL_VOID"].includes(parlay.status);
  const removable = parlay.status === "READY" && !parlay.legs.some((l) => hasStarted(l.match));
  const remove = useMutation({
    mutationFn: () => v1.removeParlay(parlay.id),
    onSuccess: () => {
      toast(t("records.toast.parlayRemoved"));
      void refresh();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Card as="article" className="overflow-hidden">
      <div data-testid="my-parlay" data-status={parlay.status}>
        <header className="flex flex-wrap items-start justify-between gap-2 px-4 pt-4 sm:px-5">
          <div className="min-w-0">
            <OriginLabel origin="mine" />
            <h3
              className="mt-1 truncate font-display text-base font-semibold"
              data-testid="my-parlay-name"
            >
              {parlay.name ?? t("records.mine.parlays.unnamed")}
            </h3>
            <p className="text-caption text-muted-foreground">
              {t("parlays.legs", { count: parlay.legs.length })} ·{" "}
              {t("records.mine.parlays.createdAt", { when: formatRelative(parlay.created_at) })}
            </p>
          </div>
          <ParlayStatusBadge status={parlay.status} />
        </header>
        <ol className="mt-3 divide-y divide-border/60 border-t border-border/60">
          {parlay.legs.map((leg) => (
            <li key={leg.leg_no} className="flex items-center gap-3 px-4 py-2.5 sm:px-5">
              <span className="numeric flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-gold/40 bg-gold-soft text-[0.65rem] font-semibold text-gold-strong">
                {leg.leg_no}
              </span>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-semibold">
                  {selectionLabel({
                    market_key: leg.market_key,
                    selection: leg.selection,
                    line: leg.line,
                    home: leg.match.home.name,
                    away: leg.match.away.name,
                  })}
                </div>
                <div className="truncate text-caption text-muted-foreground">
                  <span className="numeric">{formatKickoff(leg.match.kickoff_at)}</span> ·{" "}
                  {leg.match.home.name} – {leg.match.away.name}
                </div>
              </div>
              <OddsPill odds={leg.odds} size="sm" />
              {leg.status !== "PENDING" ? <ResultBadge status={leg.status} /> : null}
            </li>
          ))}
        </ol>
        <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-border/60 bg-elevated/30 px-4 py-3 sm:px-5">
          <div className="flex items-center gap-3">
            <span className="text-label text-subtle-foreground">{t("parlays.combinedOdds")}</span>
            <span className="numeric text-lg font-semibold text-gold-strong">
              {fmtOdds(parlay.combined_odds)}
            </span>
            {settled ? <Units value={parlay.profit_units} className="text-sm" /> : null}
          </div>
          {removable ? (
            <button
              type="button"
              disabled={remove.isPending}
              onClick={() => remove.mutate()}
              data-testid="my-parlay-remove"
              className="inline-flex min-h-8 items-center gap-1 rounded-full border border-border-strong px-3 text-xs font-medium text-muted-foreground hover:bg-elevated hover:text-foreground disabled:opacity-50"
            >
              <Trash2 aria-hidden className="h-3 w-3" />
              {t("records.mine.parlays.remove")}
            </button>
          ) : null}
        </footer>
      </div>
    </Card>
  );
}

function MyParlays() {
  const q = useQuery(live.myParlays);
  const slip = useSlip();
  const parlays = q.data?.data ?? [];
  const build = (
    <button
      type="button"
      onClick={() => slip.setOpen(true)}
      data-testid="build-parlay"
      className="inline-flex min-h-9 items-center gap-1.5 rounded-full border border-gold/50 bg-gold-soft px-3.5 text-xs font-semibold text-gold-strong transition-colors hover:bg-gold-soft/70"
    >
      <Layers aria-hidden className="h-3.5 w-3.5" />
      {t("records.mine.parlays.build")}
      {slip.legs.length > 0 ? <span className="numeric">· {slip.legs.length}</span> : null}
    </button>
  );
  return (
    <section className="space-y-3" data-testid="my-parlays">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <SectionHeader
          title={t("records.mine.parlays.title")}
          icon={<Layers aria-hidden className="h-4 w-4 text-gold" />}
        />
        {build}
      </div>
      {q.isPending ? (
        <SkeletonBlock className="h-40" />
      ) : q.isError ? (
        <Card>
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        </Card>
      ) : parlays.length === 0 ? (
        <Card>
          <EmptyState
            compact
            icon={<Layers aria-hidden className="h-5 w-5" />}
            title={t("records.mine.parlays.empty")}
            body={t("records.mine.parlays.emptyBody")}
          />
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {parlays.map((p) => (
            <UserParlayCard key={p.id} parlay={p} />
          ))}
        </div>
      )}
    </section>
  );
}

export function MyPicksPage() {
  return (
    <div className="space-y-9" data-testid="my-picks-page">
      <PageTitle title={t("records.mine.title")} subtitle={t("records.mine.subtitle")} />
      <Results />
      <SavedPicks />
      <MyParlays />
      <p className="text-center text-caption text-subtle-foreground lg:hidden">
        {t("common.disclaimer")}
      </p>
    </div>
  );
}
