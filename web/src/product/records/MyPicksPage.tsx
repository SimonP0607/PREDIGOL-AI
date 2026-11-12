/**
 * Mis picks: how it went (today, 7 days, 30 days, everything - PrediGol's picks and parlays
 * next to the user's own), the user's recap in animated charts (REVIEW point 19), the picks the
 * user saved, and the parlays they built. Profit is in units of one stake: PrediGol handles no
 * money.
 */
import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { keepPreviousData, useInfiniteQuery, useMutation, useQuery } from "@tanstack/react-query";
import { Bookmark, Download, Layers, LineChart, Pencil, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { DASH, fmtInt, formatOdds, fmtPct, localFixed } from "@/lib/i18n/format";
import {
  dayKey,
  formatDateLong,
  formatDateYear,
  formatKickoff,
  formatRelative,
  relativeDay,
  todayKey,
  zoneName,
} from "@/lib/time";
import { exportUrl, v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type { HistoryGroup, HistoryPeriod, UserParlay, UserPick } from "@/lib/api/v1/types_records";
import { useAuth, usePreviewParam } from "@/lib/auth/AuthProvider";
import { CompetitionTag, Matchup } from "@/components/football/Logos";
import { GlossaryTerm } from "@/components/system/GlossaryTerm";
import { OddsPill } from "@/product/shared/Bits";
import { PriceNowLine } from "@/product/shared/PriceNowLine";
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
import { ConfirmAction } from "@/product/shared/Confirm";
import { EvaluationBadge, OriginLabel, ParlayStatusBadge, RecordState, Units } from "./Badges";
import { CorrectionNote } from "./CorrectionNote";
import { useRefreshMine } from "./hooks";
import { HISTORY_GROUPS, hasStarted } from "./model";
import { useSlip } from "./slipContext";
import { Recap } from "./Recap";
import { CONCLUSIVE, MIN_SAMPLE, sampleLine } from "./sample";
import { NO_FILTER, activeCount, toApiFilter, type PicksFilterState } from "./myPicksFilter";
import { PicksFilters, PicksSearch } from "./PicksFilters";
import { PicksSummaryBlock } from "./PicksSummary";
import { lineValueText } from "./picksText";
import { track } from "@/lib/track";
import { useUsefulMoment } from "@/product/feedback/moments";
import { useGuideScreen } from "@/product/guides/context";

const PERIODS: readonly HistoryPeriod[] = ["today", "7d", "30d", "all"];

function Stat({
  label,
  value,
  tone,
}: {
  label: ReactNode;
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

/**
 * A group of «Mis resultados» with its sample (plan UX, B5, section 30): the counts always; the hit rate, the units and the
 * return only from the server's min_sample settled records, the return with its margin, and below `conclusive` the
 * notice that the sample does not allow a conclusion yet.
 */
function GroupCard({
  name,
  group,
  min,
  conclusive,
}: {
  name: string;
  group: HistoryGroup;
  min: number;
  conclusive: number;
}) {
  const roi = group.roi;
  const n = Number(group.staked_units);
  return (
    <Card className="p-4" as="article">
      <h3 className="font-display text-sm font-semibold" data-testid={`history-group-title`}>
        {t(`records.mine.results.group.${name}`)}
      </h3>
      <div className="mt-2 flex items-baseline justify-between gap-2">
        <span className="numeric text-2xl font-semibold" data-testid={`history-${name}-total`}>
          {fmtInt(group.total)}
        </span>
        <span data-testid={`history-${name}-profit`}>
          {group.profit_units === null ? (
            <span className="numeric text-sm text-subtle-foreground">{DASH}</span>
          ) : (
            <Units value={group.profit_units} className="text-sm" />
          )}
        </span>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2.5">
        <Stat
          label={t("records.labels.result")}
          value={t("records.mine.results.record", { won: group.won, lost: group.lost })}
        />
        <Stat label={t("records.mine.results.pending")} value={fmtInt(group.pending)} />
        <Stat label={t("records.mine.results.hitRate")} value={fmtPct(group.hit_rate, 0)} />
        <Stat
          label={<GlossaryTerm term="roi">{t("records.mine.results.roi")}</GlossaryTerm>}
          value={
            <>
              <span data-testid={`history-${name}-roi`}>
                {roi === null ? DASH : fmtPct(roi, 1)}
              </span>
              {n > 0 ? (
                <span
                  className="block text-caption font-normal text-subtle-foreground"
                  data-testid={`history-${name}-roi-sample`}
                >
                  <GlossaryTerm term="sample">
                    {sampleLine({ n, margin: group.margin ?? null, min, conclusive })}
                  </GlossaryTerm>
                </span>
              ) : null}
            </>
          }
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
    <section className="space-y-3" data-testid="my-results" data-guide="mine-results">
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
              <GroupCard
                key={g}
                name={g}
                group={history.groups[g]}
                min={history.min_sample ?? MIN_SAMPLE}
                conclusive={history.conclusive ?? CONCLUSIVE}
              />
            ))}
          </div>
          {q.data?.status === "empty" ? (
            <p className="text-xs text-muted-foreground" data-testid="history-empty">
              {t("records.mine.results.empty")}
            </p>
          ) : null}
          <p className="text-caption text-subtle-foreground">
            {t("records.mine.results.note", { zone: zoneName(auth.timeZone) })}{" "}
            <GlossaryTerm term="units">{t("records.unitsLink")}</GlossaryTerm>
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
          className="numeric mt-1 h-9 w-full rounded-lg border border-border bg-background px-3 text-sm focus:border-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-ring aria-[invalid=true]:border-negative pointer-coarse:h-11"
        />
      </label>
      <button
        type="submit"
        disabled={save.isPending}
        data-testid="user-odds-save"
        className="tap-y relative h-9 rounded-full bg-primary px-4 text-xs font-semibold text-primary-foreground disabled:opacity-50"
      >
        {t("records.mine.picks.saveOdds")}
      </button>
      {pick.user_odds ? (
        <ConfirmAction
          testId="clear-odds"
          title={t("records.mine.picks.confirmClearOdds.title")}
          body={t("records.mine.picks.confirmClearOdds.body")}
          confirm={t("records.mine.picks.confirmClearOdds.ok")}
          onConfirm={() => save.mutate(null)}
          trigger={
            <button
              type="button"
              disabled={save.isPending}
              data-testid="user-odds-clear"
              className="tap-y relative h-9 rounded-full border border-border-strong px-3 text-xs font-medium text-muted-foreground hover:bg-elevated"
            >
              {t("records.mine.picks.clearOdds")}
            </button>
          }
        />
      ) : null}
      <button
        type="button"
        onClick={onDone}
        className="tap-y relative h-9 rounded-full px-3 text-xs font-medium text-muted-foreground hover:bg-elevated"
      >
        {t("records.mine.picks.cancel")}
      </button>
      {invalid ? (
        <p className="w-full text-xs text-negative">{t("records.mine.picks.oddsInvalid")}</p>
      ) : null}
    </form>
  );
}

/** A limited account reads its records and changes none of them (plan UX, A8): the server refuses the writes too. */
function useReadOnly(): boolean {
  return useAuth().user?.membership?.limited ?? false;
}

function SavedPickRow({ pick }: { pick: UserPick }) {
  const refresh = useRefreshMine();
  const [editing, setEditing] = useState(false);
  const readOnly = useReadOnly();
  const m = pick.match;
  const started = hasStarted(m);
  const open = pick.status === "PENDING" && !started && !readOnly;
  const remove = useMutation({
    mutationFn: () => v1.removePick(pick.id),
    onSuccess: () => {
      track("pick_removed");
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
    <li
      className="px-4 py-3.5 sm:px-5"
      data-testid="saved-pick"
      data-status={pick.status}
      data-fixture-id={m.fixture_id}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        {/* Plan UX, A1: the user's own selection says so, and a PrediGol pick they saved stays PrediGol's - never mixed. */}
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
          {pick.origin === "predigol_pick" ? (
            <>
              <OriginLabel origin="predigol" />
              <span className="text-caption text-subtle-foreground">
                {t("records.labels.savedPredigol")}
              </span>
            </>
          ) : (
            <OriginLabel origin="mine" />
          )}
        </div>
        <span className="text-caption text-subtle-foreground">
          {t("records.mine.picks.savedAt", { when: formatRelative(pick.saved_at) })}
        </span>
      </div>
      <div className="mt-2 grid grid-cols-[minmax(0,1fr)_auto] items-start gap-x-4 gap-y-2">
        <Link
          to="/matches/$fixtureId"
          params={{ fixtureId: String(m.fixture_id) }}
          // a settled pick opens its match's Postpartido: how it ended and why (plan UX, B4) - the link a result notice will use
          {...(pick.status !== "PENDING" ? { hash: "postmatch" } : {})}
          data-testid="my-pick-match"
          className="min-w-0 rounded-md focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          <CompetitionTag
            name={m.competition.name}
            logo={m.competition.logo_url}
            flag={m.competition.flag_url}
            country={m.competition.country}
            className="min-w-0"
          />
          {/* Home above away, every name whole (mobile UX audit: "Atlético Nac…"). */}
          <Matchup
            home={{ name: m.home.name, logo: m.home.logo_url }}
            away={{ name: m.away.name, logo: m.away.logo_url }}
            score={
              m.score_home !== null && m.score_away !== null
                ? { home: m.score_home, away: m.score_away }
                : null
            }
            size={18}
            className="mt-1.5"
          />
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
              <span className="numeric font-semibold">{formatOdds(pick.user_odds)}</span>
            </span>
          ) : null}
          <PriceNowLine now={pick.price_now} />
        </div>
      </div>
      <div className="mt-2.5 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-caption text-subtle-foreground">{t("records.labels.result")}</span>
          <RecordState status={pick.status} match={m} />
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
              className="inline-flex min-h-8 items-center gap-1 rounded-full border border-border-strong px-3 text-xs font-medium hover:bg-elevated pointer-coarse:min-h-11"
            >
              <Pencil aria-hidden className="h-3 w-3" />
              {pick.user_odds
                ? t("records.mine.picks.editYours")
                : t("records.mine.picks.addYours")}
            </button>
            <ConfirmAction
              testId="remove-pick"
              title={t("records.mine.picks.confirmRemove.title")}
              body={t("records.mine.picks.confirmRemove.body")}
              confirm={t("records.mine.picks.confirmRemove.ok")}
              onConfirm={() => remove.mutate()}
              trigger={
                <button
                  type="button"
                  disabled={remove.isPending}
                  data-testid="saved-pick-remove"
                  className="inline-flex min-h-8 items-center gap-1 rounded-full border border-border-strong px-3 text-xs font-medium text-muted-foreground hover:bg-elevated hover:text-foreground disabled:opacity-50 pointer-coarse:min-h-11"
                >
                  <Trash2 aria-hidden className="h-3 w-3" />
                  {t("records.mine.picks.remove")}
                </button>
              }
            />
          </div>
        ) : null}
      </div>
      {lineValueText(pick.line_value) ? (
        <p
          className="mt-1.5 text-caption text-muted-foreground"
          data-testid="saved-pick-line-value"
        >
          <GlossaryTerm term="lineValue">{lineValueText(pick.line_value)}</GlossaryTerm>
        </p>
      ) : null}
      <CorrectionNote corrections={pick.corrections} record="result" className="mt-2" />
      {open && editing ? <UserOddsForm pick={pick} onDone={() => setEditing(false)} /> : null}
    </li>
  );
}

/** "Ver más": the next page of a list read page by page, with how many of how many are shown. */
function MoreButton({
  shown,
  total,
  busy,
  onMore,
  label,
  countLabel,
  testId,
}: {
  shown: number;
  total: number;
  busy: boolean;
  onMore: () => void;
  label: string;
  countLabel: string;
  testId: string;
}) {
  return (
    <div className="flex flex-wrap items-center justify-center gap-3">
      <span className="numeric text-caption text-subtle-foreground" data-testid={`${testId}-count`}>
        {t(countLabel, { shown: fmtInt(shown), total: fmtInt(total) })}
      </span>
      <button
        type="button"
        onClick={onMore}
        disabled={busy}
        data-testid={testId}
        className="inline-flex min-h-9 items-center rounded-full border border-border-strong px-4 text-xs font-semibold hover:bg-elevated disabled:opacity-50 pointer-coarse:min-h-11"
      >
        {label}
      </button>
    </div>
  );
}

/** Plan UX, A1: every saved pick, a page of 25 at a time - "Todo" was cut at 500 and called everything. */
const PICKS_PAGE = 25;
const PARLAYS_PAGE = 10;

function SavedPicks() {
  const [filter, setFilter] = useState<PicksFilterState>(NO_FILTER);
  // the search waits for the reader to stop typing before it asks the server
  const q = useDebounced(filter.q, 300);
  const api = useMemo(() => toApiFilter({ ...filter, q }), [filter, q]);
  const pages = useInfiniteQuery({
    ...live.myPicksPages(PICKS_PAGE, api),
    placeholderData: keepPreviousData,
  });
  const summary = useQuery({ ...live.myPicksSummary(api), placeholderData: keepPreviousData });
  const picks = pages.data?.pages.flatMap((p) => p.data) ?? [];
  // a result of one's own seen: a useful moment, after which the monthly survey may come (plan UX, B6)
  useUsefulMoment(
    "result_seen",
    picks.some((p) => p.status !== "PENDING"),
  );
  const total = pages.data?.pages[0]?.meta.total ?? picks.length;
  const filtered = activeCount(filter) > 0;
  const options = summary.data?.data.options;
  const everything = (options?.markets.length ?? 0) > 0 || filtered || picks.length > 0;
  return (
    <section className="space-y-3" data-testid="saved-picks" data-guide="mine-saved">
      <SectionHeader
        title={t("records.mine.picks.title")}
        subtitle={picks.length > 0 ? t("records.mine.picks.settlesAt") : undefined}
        icon={<Bookmark aria-hidden className="h-4 w-4 text-primary" />}
      />
      {everything ? (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <PicksSearch
              value={filter.q}
              onChange={(value) => setFilter({ ...filter, q: value })}
            />
          </div>
          <PicksFilters
            value={filter}
            onChange={setFilter}
            markets={options?.markets ?? []}
            competitions={options?.competitions ?? []}
            showLabel={t("records.mine.filters.show", { count: total, n: fmtInt(total) })}
          />
          {summary.data ? (
            <PicksSummaryBlock
              summary={summary.data.data}
              exportHref={exportUrl("picks", api)}
              busy={summary.isFetching}
            />
          ) : summary.isError ? null : (
            <SkeletonBlock className="h-28" />
          )}
        </>
      ) : null}
      {pages.isPending ? (
        <SkeletonBlock className="h-40" />
      ) : pages.isError ? (
        <Card>
          <ErrorState error={pages.error} onRetry={() => void pages.refetch()} />
        </Card>
      ) : picks.length === 0 ? (
        <Card>
          {filtered ? (
            <EmptyState
              compact
              icon={<Bookmark aria-hidden className="h-5 w-5" />}
              title={t("records.mine.filters.empty")}
              action={
                <button
                  type="button"
                  onClick={() => setFilter(NO_FILTER)}
                  data-testid="mypicks-empty-reset"
                  className="tap-y relative mt-1 inline-flex h-9 items-center rounded-full border border-border-strong px-4 text-xs font-semibold hover:bg-elevated"
                >
                  {t("common.filters.reset")}
                </button>
              }
            />
          ) : (
            <EmptyState
              compact
              icon={<Bookmark aria-hidden className="h-5 w-5" />}
              title={t("records.mine.picks.empty")}
              body={t("records.mine.picks.emptyBody")}
            />
          )}
        </Card>
      ) : (
        <>
          <Card className={cn("transition-opacity", pages.isPlaceholderData && "opacity-70")}>
            <ul className="divide-y divide-border/70" data-testid="saved-picks-list">
              {byDay(picks).map(([day, rows]) => (
                <li key={day} data-testid="saved-picks-day" data-day={day}>
                  <h4 className="px-4 pb-1.5 pt-3 text-label text-subtle-foreground sm:px-5">
                    {dayHeading(day, rows[0]!.match.kickoff_at)}
                  </h4>
                  <ul className="divide-y divide-border/70">
                    {rows.map((p) => (
                      <SavedPickRow key={p.id} pick={p} />
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          </Card>
          {pages.hasNextPage || total > picks.length ? (
            <MoreButton
              shown={picks.length}
              total={total}
              busy={pages.isFetchingNextPage || !pages.hasNextPage}
              onMore={() => void pages.fetchNextPage()}
              label={t("records.mine.picks.more")}
              countLabel="records.mine.picks.count"
              testId="saved-picks-more"
            />
          ) : (
            <p
              className="numeric text-center text-caption text-subtle-foreground"
              data-testid="saved-picks-all"
            >
              {t("records.mine.picks.allShown", { count: total, n: fmtInt(total) })}
            </p>
          )}
        </>
      )}
    </section>
  );
}

/**
 * The list goes by the day of the match, newest first, and is read page by page in that order (plan UX, B5: «paginación por
 * fecha»): each day under its own heading in the reader's time zone, so a long record is walked by date.
 */
function byDay(picks: readonly UserPick[]): Array<[string, UserPick[]]> {
  const days: Array<[string, UserPick[]]> = [];
  for (const p of picks) {
    const day = dayKey(p.match.kickoff_at);
    const last = days[days.length - 1];
    if (last && last[0] === day) last[1].push(p);
    else days.push([day, [p]]);
  }
  return days;
}

/** «Hoy» · «Ayer» · «sábado, 4 de octubre» · «4 oct 2025» for another year. */
function dayHeading(day: string, at: string): string {
  const rel = relativeDay(at);
  if (rel) return t(`common.day.${rel}`);
  return day.slice(0, 4) === todayKey().slice(0, 4) ? formatDateLong(at) : formatDateYear(at);
}

/** A value that follows another after it has stood still for `ms` (the search, while the reader types). */
function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setSettled(value), ms);
    return () => window.clearTimeout(id);
  }, [value, ms]);
  return settled;
}

function UserParlayCard({ parlay }: { parlay: UserParlay }) {
  const readOnly = useReadOnly();
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
            <OriginLabel origin="mine" kind="parlay" />
            <h3
              className="mt-1 break-words font-display text-base font-semibold leading-snug"
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
            // The selection keeps 11 rem (UX-094): when the odds, their time and the state do not fit beside it, they
            // wrap to a line of their own under it. Beside it they left the selection 66 px on a 320 px phone («Gana
            // Sandefjord» a few letters a line) and 26 px on a desk next to «Terminado · liquidando».
            <li
              key={leg.leg_no}
              className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-4 py-2.5 sm:px-5"
            >
              <span className="numeric flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-gold/40 bg-gold-soft text-micro font-semibold text-gold-strong">
                {leg.leg_no}
              </span>
              <div className="min-w-[min(100%,11rem)] flex-1 basis-0">
                <div className="break-words text-sm font-semibold leading-snug">
                  {selectionLabel({
                    market_key: leg.market_key,
                    selection: leg.selection,
                    line: leg.line,
                    home: leg.match.home.name,
                    away: leg.match.away.name,
                  })}
                </div>
                <div className="break-words text-caption text-muted-foreground">
                  <span className="numeric">{formatKickoff(leg.match.kickoff_at)}</span> ·{" "}
                  {leg.match.home.name} – {leg.match.away.name}
                </div>
              </div>
              <div className="ml-auto flex max-w-full flex-wrap items-center justify-end gap-x-3 gap-y-1">
                <div className="flex shrink-0 flex-col items-end gap-0.5">
                  <OddsPill odds={leg.odds} size="sm" />
                  {leg.odds_captured_at ? (
                    <span
                      className="numeric whitespace-nowrap text-micro text-subtle-foreground"
                      data-testid="parlay-leg-odds-at"
                    >
                      {t("records.mine.parlays.oddsAt", {
                        when: formatKickoff(leg.odds_captured_at),
                      })}
                    </span>
                  ) : null}
                </div>
                <RecordState status={leg.status} match={leg.match} hidePending />
              </div>
            </li>
          ))}
        </ol>
        <CorrectionNote
          corrections={parlay.corrections}
          record="parlay"
          className="border-t border-border/60 px-4 py-2.5 sm:px-5"
        />
        <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-border/60 bg-elevated/30 px-4 py-3 sm:px-5">
          <div className="flex items-center gap-3">
            <span className="text-label text-subtle-foreground">{t("parlays.combinedOdds")}</span>
            <span className="numeric text-lg font-semibold text-gold-strong">
              {formatOdds(parlay.combined_odds)}
            </span>
            {settled ? <Units value={parlay.profit_units} className="text-sm" /> : null}
          </div>
          {removable && !readOnly ? (
            <ConfirmAction
              testId="remove-parlay"
              title={t("records.mine.parlays.confirmRemove.title")}
              body={t("records.mine.parlays.confirmRemove.body")}
              confirm={t("records.mine.parlays.confirmRemove.ok")}
              onConfirm={() => remove.mutate()}
              trigger={
                <button
                  type="button"
                  disabled={remove.isPending}
                  data-testid="my-parlay-remove"
                  className="inline-flex min-h-8 items-center gap-1 rounded-full border border-border-strong px-3 text-xs font-medium text-muted-foreground hover:bg-elevated hover:text-foreground disabled:opacity-50 pointer-coarse:min-h-11"
                >
                  <Trash2 aria-hidden className="h-3 w-3" />
                  {t("records.mine.parlays.remove")}
                </button>
              }
            />
          ) : null}
        </footer>
      </div>
    </Card>
  );
}

function MyParlays() {
  const q = useInfiniteQuery(live.myParlaysPages(PARLAYS_PAGE));
  const slip = useSlip();
  const parlays = q.data?.pages.flatMap((p) => p.data) ?? [];
  const total = q.data?.pages[0]?.meta.total ?? parlays.length;
  const build = (
    <button
      type="button"
      onClick={() => slip.setOpen(true)}
      data-testid="build-parlay"
      className="tap-y relative inline-flex min-h-9 items-center gap-1.5 rounded-full border border-gold/50 bg-gold-soft px-3.5 text-xs font-semibold text-gold-strong transition-colors hover:bg-gold-soft/70"
    >
      <Layers aria-hidden className="h-3.5 w-3.5" />
      {t("records.mine.parlays.build")}
      {slip.legs.length > 0 ? <span className="numeric">· {slip.legs.length}</span> : null}
    </button>
  );
  return (
    <section
      id="my-parlays"
      className="scroll-mt-24 space-y-3"
      data-testid="my-parlays"
      data-guide="mine-parlays"
    >
      <div className="flex flex-wrap items-end justify-between gap-2">
        <SectionHeader
          title={t("records.mine.parlays.title")}
          icon={<Layers aria-hidden className="h-4 w-4 text-gold" />}
        />
        <div className="flex flex-wrap items-center gap-2">
          {total > 0 ? (
            <a
              href={exportUrl("parlays")}
              download
              data-testid="my-parlays-export"
              className="tap-y relative inline-flex min-h-9 items-center gap-1.5 rounded-full border border-border-strong px-3.5 text-xs font-semibold hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <Download aria-hidden className="h-3.5 w-3.5" />
              {t("records.mine.parlays.export")}
            </a>
          ) : null}
          {build}
        </div>
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
        <>
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            {parlays.map((p) => (
              <UserParlayCard key={p.id} parlay={p} />
            ))}
          </div>
          {q.hasNextPage || total > parlays.length ? (
            <MoreButton
              shown={parlays.length}
              total={total}
              busy={q.isFetchingNextPage || !q.hasNextPage}
              onMore={() => void q.fetchNextPage()}
              label={t("records.mine.parlays.more")}
              countLabel="records.mine.parlays.count"
              testId="my-parlays-more"
            />
          ) : null}
        </>
      )}
    </section>
  );
}

export function MyPicksPage() {
  const readOnly = useReadOnly();
  useGuideScreen("my_picks", { ready: true });
  return (
    <div className="space-y-9" data-testid="my-picks-page">
      <PageTitle
        guide="my_picks"
        title={t("records.mine.title")}
        subtitle={t("records.mine.subtitle")}
      />
      {readOnly ? (
        <p className="text-xs text-muted-foreground" data-testid="my-picks-read-only">
          {t("profile.membership.limited.readOnly")}
        </p>
      ) : null}
      <Results />
      <Recap />
      <SavedPicks />
      <MyParlays />
    </div>
  );
}
