/**
 * "Tu recapitulación" (REVIEW PREDIGOL, point 19): the user's own settled picks - or parlays - over time: how many, how
 * they went, the average odds, and - from the sample the plan asks (plan UX, B5, section 30: «con menos de 25 liquidados
 * solo se muestran los conteos») - the hit rate, the units, the return with its margin and the two charts of units, day by
 * day. No streaks (section 30: «rachas que inviten a apostar», never); the breakdown by kind of bet, league and odds
 * range is the server's, under the filter of «Picks guardados» (PicksSummary). Figures count up and charts draw in;
 * nothing moves with reduced motion. One unit per record, at the profit each was settled at: PrediGol handles no money.
 */
import { useEffect, useId, useMemo, useState, type ReactNode } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { BarChart3 } from "lucide-react";
import { cn } from "@/lib/utils";
import { intlTag, t } from "@/lib/i18n";
import { DASH, fmtInt, formatOdds, fmtPct, localFixed } from "@/lib/i18n/format";
import { getTimeZone, zonedInstant } from "@/lib/time";
import { live } from "@/lib/api/v1/queries";
import { GlossaryTerm } from "@/components/system/GlossaryTerm";
import { EvidenceChart } from "@/components/analytics/EvidenceChart";
import type { TextReading } from "@/components/analytics/evidence";
import { READER_REVIEW } from "@/components/analytics/readerReview";
import { t as rt } from "@/components/analytics/stats/readText";
import { Card, ErrorState, SectionHeader, SkeletonBlock } from "@/product/shared/States";
import { useReducedMotion } from "@/product/shared/motion";
import { ChipGroup } from "@/product/picks/Controls";
import { fromParlays, fromPicks, recap, within, type Recap as RecapData } from "./recapData";
import { fmtUnits } from "./units";
import { MIN_SAMPLE, enough, marginOf, sampleLine } from "./sample";

type Scope = "picks" | "parlays";
const PERIODS: readonly number[] = [30, 90, 0];
const POSITIVE = "var(--color-positive)";
const NEGATIVE = "var(--color-negative)";
const GRID = "var(--color-border)";
const TICK = { fill: "var(--color-subtle-foreground)", fontSize: 12 };
const TOOLTIP = {
  contentStyle: {
    background: "var(--color-card)",
    border: "1px solid var(--color-border-strong)",
    borderRadius: 8,
    fontSize: 12,
  },
  labelStyle: { color: "var(--color-muted-foreground)" },
  itemStyle: { color: "var(--color-foreground)" },
  cursor: { fill: "var(--color-elevated)", opacity: 0.4 },
};
const DRAW_MS = 900;

const DAY_FMT = new Map<string, Intl.DateTimeFormat>();
/** "3 oct": a day of the axis, in the reader's zone and language. */
function shortDay(day: string): string {
  const key = `${intlTag()}|${getTimeZone()}`;
  let f = DAY_FMT.get(key);
  if (!f) {
    f = new Intl.DateTimeFormat(intlTag(), {
      timeZone: getTimeZone(),
      day: "numeric",
      month: "short",
    });
    DAY_FMT.set(key, f);
  }
  return f.format(new Date(zonedInstant(day, 12)));
}

/** The reading sentence of a recap chart: its sample is the settled records (the page shows charts from `MIN_SAMPLE`). */
const sentence = (text: string, settled: number): TextReading => ({
  kind: "text",
  sentence: text,
  n: settled,
  minSample: MIN_SAMPLE,
});

const units = (n: number) => fmtUnits(Math.round(n * 100) / 100);

function Kpi({
  label,
  value,
  tone,
  hint,
  testId,
}: {
  label: ReactNode;
  value: ReactNode;
  tone?: string | undefined;
  hint?: ReactNode;
  testId: string;
}) {
  return (
    <div className="min-w-0 rounded-xl border border-border bg-card px-4 py-3">
      <div className="text-label leading-tight text-subtle-foreground">{label}</div>
      <div
        className={cn("numeric mt-1.5 text-xl font-semibold leading-none", tone)}
        data-testid={`recap-kpi-${testId}`}
      >
        {value}
      </div>
      {hint ? <div className="mt-1 text-caption text-muted-foreground">{hint}</div> : null}
    </div>
  );
}

function Counted({ value, format }: { value: number | null; format: (n: number) => string }) {
  return <>{value === null ? DASH : format(value)}</>;
}

/** A chart of the recap: the evidence card with its reading sentence, its axes in words and a table for a screen reader. */
function RecapChart({
  title,
  axes,
  reading,
  caption,
  rows,
  children,
  testId,
}: {
  title: string;
  axes: string;
  reading: TextReading;
  caption: string;
  rows: ReadonlyArray<{ day: string; value: string }>;
  children: ReactNode;
  testId: string;
}) {
  return (
    <EvidenceChart
      evidence="E1"
      review={READER_REVIEW}
      title={title}
      axes={axes}
      reading={reading}
      terms={["units"]}
    >
      <div className="h-52" data-testid={testId}>
        {children}
      </div>
      <table className="sr-only">
        <caption>{caption}</caption>
        <tbody>
          {rows.map((x) => (
            <tr key={x.day}>
              <th scope="row">{shortDay(x.day)}</th>
              <td>{x.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </EvidenceChart>
  );
}

function tone(n: number | null): string | undefined {
  if (n === null || n === 0) return undefined;
  return n > 0 ? "text-positive" : "text-negative";
}

function Kpis({ r }: { r: RecapData }) {
  const shown = enough(r.staked);
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5" data-testid="recap-kpis">
      <Kpi
        label={<GlossaryTerm term="settlement">{t("records.recap.kpi.settled")}</GlossaryTerm>}
        testId="settled"
        value={<Counted value={r.settled} format={(n) => fmtInt(Math.round(n))} />}
        hint={t("records.recap.kpi.record", { won: r.wins, lost: r.losses, void: r.voids })}
      />
      <Kpi
        label={t("records.recap.kpi.hitRate")}
        testId="hit-rate"
        value={<Counted value={shown ? r.hitRate : null} format={(n) => fmtPct(n, 0)} />}
      />
      <Kpi
        label={t("records.recap.kpi.profit")}
        testId="profit"
        value={<Counted value={shown ? r.profit : null} format={units} />}
        tone={shown ? tone(r.profit) : undefined}
      />
      <Kpi
        label={<GlossaryTerm term="roi">{t("records.recap.kpi.roi")}</GlossaryTerm>}
        testId="roi"
        value={<Counted value={shown ? r.roi : null} format={(n) => fmtPct(n, 1)} />}
        tone={shown ? tone(r.roi) : undefined}
        hint={
          r.staked > 0 ? (
            <span data-testid="recap-roi-sample">
              <GlossaryTerm term="sample">
                {sampleLine({ n: r.staked, margin: shown ? marginOf(r.staked) : null })}
              </GlossaryTerm>
            </span>
          ) : undefined
        }
      />
      <Kpi
        label={t("records.recap.kpi.avgOdds")}
        testId="avg-odds"
        value={<Counted value={r.avgOdds} format={(n) => formatOdds(n)} />}
        hint={
          r.avgOddsWon !== null
            ? t("records.recap.kpi.avgOddsWon", { odds: formatOdds(r.avgOddsWon) })
            : undefined
        }
      />
    </div>
  );
}

function Cumulative({ r, animate }: { r: RecapData; animate: boolean }) {
  const id = useId().replace(/:/g, "");
  const last = r.days[r.days.length - 1]?.total ?? 0;
  const color = last >= 0 ? POSITIVE : NEGATIVE;
  const data = r.days.map((d) => ({ ...d, label: shortDay(d.day) }));
  return (
    <RecapChart
      title={rt("readchart.recap.cumulative.title")}
      axes={rt("readchart.recap.cumulative.axis")}
      reading={sentence(
        rt("readchart.recap.cumulative.read", {
          total: units(last),
          n: fmtInt(r.settled),
          days: fmtInt(r.days.length),
        }),
        r.settled,
      )}
      caption={t("records.recap.cumulative.title")}
      rows={r.days.map((d) => ({ day: d.day, value: units(d.total) }))}
      testId="recap-cumulative"
    >
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id={`cum-${id}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.35} />
              <stop offset="100%" stopColor={color} stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke={GRID} />
          <XAxis dataKey="label" tick={TICK} tickLine={false} axisLine={false} minTickGap={16} />
          <YAxis
            tick={TICK}
            tickLine={false}
            axisLine={false}
            width={38}
            tickFormatter={(v: number) => localFixed(v, 1)}
          />
          <ReferenceLine y={0} stroke="var(--color-border-strong)" />
          <Tooltip
            {...TOOLTIP}
            formatter={(v) => [units(Number(v)), t("records.recap.cumulative.total")]}
          />
          <Area
            type="monotone"
            dataKey="total"
            stroke={color}
            strokeWidth={2}
            fill={`url(#cum-${id})`}
            isAnimationActive={animate}
            animationDuration={DRAW_MS}
            animationEasing="ease-out"
          />
        </AreaChart>
      </ResponsiveContainer>
    </RecapChart>
  );
}

function PerDay({ r, animate }: { r: RecapData; animate: boolean }) {
  const data = r.days.map((d) => ({ ...d, label: shortDay(d.day) }));
  return (
    <RecapChart
      title={rt("readchart.recap.daily.title")}
      axes={rt("readchart.recap.daily.axis")}
      reading={sentence(
        r.bestDay && r.worstDay
          ? rt("readchart.recap.daily.read", {
              best: shortDay(r.bestDay.day),
              bestProfit: units(r.bestDay.profit),
              worst: shortDay(r.worstDay.day),
              worstProfit: units(r.worstDay.profit),
              days: fmtInt(r.days.length),
            })
          : rt("readchart.recap.daily.one", { days: fmtInt(r.days.length) }),
        r.settled,
      )}
      caption={t("records.recap.daily.title")}
      rows={r.days.map((d) => ({ day: d.day, value: units(d.profit) }))}
      testId="recap-daily"
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke={GRID} />
          <XAxis dataKey="label" tick={TICK} tickLine={false} axisLine={false} minTickGap={16} />
          <YAxis
            tick={TICK}
            tickLine={false}
            axisLine={false}
            width={38}
            tickFormatter={(v: number) => localFixed(v, 1)}
          />
          <ReferenceLine y={0} stroke="var(--color-border-strong)" />
          <Tooltip
            {...TOOLTIP}
            formatter={(v, _n, item) => [
              `${units(Number(v))} · ${t("records.recap.daily.count", { count: item.payload?.count ?? 0 })}`,
              t("records.recap.daily.profit"),
            ]}
          />
          <Bar
            dataKey="profit"
            radius={[3, 3, 0, 0]}
            isAnimationActive={animate}
            animationDuration={DRAW_MS}
            animationEasing="ease-out"
          >
            {data.map((d) => (
              <Cell key={d.day} fill={d.profit >= 0 ? POSITIVE : NEGATIVE} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </RecapChart>
  );
}

/**
 * The recap reads every record, page after page - the largest pages the API serves, 500 picks or 200 parlays (plan
 * UX, A1, defect F53: it read the first 500 picks and the first 200 parlays and added those up as if they were all).
 * Until the last page is in, it says how many it has read of how many there are, and shows no figure: a figure over
 * part of the records would not be the user's.
 */
const PICKS_PAGE = 500;
const PARLAYS_PAGE = 200;

function loadedOf(pages: ReadonlyArray<{ data: readonly unknown[] }> | undefined): number {
  return pages?.reduce((n, p) => n + p.data.length, 0) ?? 0;
}

export function Recap() {
  const picks = useInfiniteQuery(live.myPicksPages(PICKS_PAGE));
  const parlays = useInfiniteQuery(live.myParlaysPages(PARLAYS_PAGE));
  const [scope, setScope] = useState<Scope>("picks");
  const [period, setPeriod] = useState<number>(30);
  const reduced = useReducedMotion();
  const query = scope === "picks" ? picks : parlays;
  const { hasNextPage, isFetchingNextPage, isError, fetchNextPage } = query;
  useEffect(() => {
    if (hasNextPage && !isFetchingNextPage && !isError) void fetchNextPage();
  }, [hasNextPage, isFetchingNextPage, isError, fetchNextPage]);
  const loaded = loadedOf(query.data?.pages);
  const total = query.data?.pages[0]?.meta.total ?? loaded;
  const records = useMemo(
    () =>
      scope === "picks"
        ? fromPicks(picks.data?.pages.flatMap((p) => p.data) ?? [])
        : fromParlays(parlays.data?.pages.flatMap((p) => p.data) ?? []),
    [scope, picks.data, parlays.data],
  );
  const r = useMemo(() => recap(within(records, period || null)), [records, period]);
  const animate = !reduced;

  let body: ReactNode;
  if (query.isPending) {
    body = (
      <div className="grid gap-3 lg:grid-cols-2">
        <SkeletonBlock className="h-64" />
        <SkeletonBlock className="h-64" />
      </div>
    );
  } else if (query.isError) {
    body = (
      <Card>
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      </Card>
    );
  } else if (hasNextPage) {
    body = (
      <div className="space-y-3" data-testid="recap-loading">
        <p className="numeric text-caption text-muted-foreground" role="status">
          {t("records.recap.loading", { loaded: fmtInt(loaded), total: fmtInt(total) })}
        </p>
        <div className="grid gap-3 lg:grid-cols-2">
          <SkeletonBlock className="h-64" />
          <SkeletonBlock className="h-64" />
        </div>
      </div>
    );
  } else if (r.settled === 0) {
    body = (
      <p
        className="rounded-xl border border-border bg-card px-4 py-4 text-sm text-muted-foreground"
        data-testid="recap-empty"
      >
        {t(scope === "picks" ? "records.recap.emptyPicks" : "records.recap.emptyParlays")}
      </p>
    );
  } else {
    // A new scope or period draws everything again.
    const key = `${scope}|${period}`;
    body = (
      <div key={key} className="space-y-3">
        <Kpis r={r} />
        {enough(r.staked) ? (
          <div className="grid gap-3 lg:grid-cols-2">
            <Cumulative r={r} animate={animate} />
            <PerDay r={r} animate={animate} />
          </div>
        ) : (
          <p
            className="rounded-xl border border-border bg-card px-4 py-3 text-sm text-muted-foreground"
            data-testid="recap-sample-note"
          >
            {t("records.recap.sampleNote", {
              count: r.staked,
              n: fmtInt(r.staked),
              min: fmtInt(MIN_SAMPLE),
            })}
          </p>
        )}
        <p className="text-caption text-subtle-foreground">
          {t("records.recap.note")}{" "}
          <GlossaryTerm term="units">{t("records.unitsLink")}</GlossaryTerm>
        </p>
      </div>
    );
  }

  return (
    <section className="space-y-3" data-testid="my-recap">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <SectionHeader
          title={t("records.recap.title")}
          subtitle={t("records.recap.subtitle")}
          icon={<BarChart3 aria-hidden className="h-4 w-4 text-primary" />}
        />
        <div className="flex flex-wrap items-center gap-2">
          <ChipGroup
            label={t("records.recap.scope")}
            value={scope}
            options={[
              { value: "picks" as Scope, label: t("records.recap.scopePicks") },
              { value: "parlays" as Scope, label: t("records.recap.scopeParlays") },
            ]}
            onChange={setScope}
            testId="recap-scope"
          />
          <ChipGroup
            label={t("records.recap.period")}
            value={period}
            options={PERIODS.map((p) => ({
              value: p,
              label: p ? t("records.recap.days", { count: p }) : t("records.recap.all"),
            }))}
            onChange={setPeriod}
            testId="recap-period"
          />
        </div>
      </div>
      {body}
    </section>
  );
}
