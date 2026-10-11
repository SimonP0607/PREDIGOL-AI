/**
 * "Tu recapitulación" (REVIEW PREDIGOL, point 19): the user's own settled picks - or parlays - in animated charts:
 * profit building up day by day, profit per day, the average odds and how each odds range went, the streaks, and
 * each market. Figures count up and charts draw in; nothing moves with reduced motion. One unit per record, at the
 * profit each was settled at: PrediGol handles no money.
 */
import { useId, useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
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
import { BarChart3, Flame, TrendingDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { intlTag, t } from "@/lib/i18n";
import { DASH, fmtInt, fmtOdds, fmtPct, localFixed } from "@/lib/i18n/format";
import { getTimeZone, zonedInstant } from "@/lib/time";
import { live } from "@/lib/api/v1/queries";
import { Card, ErrorState, SectionHeader, SkeletonBlock } from "@/product/shared/States";
import { marketName } from "@/product/shared/markets";
import { useCountUp, useReducedMotion } from "@/product/shared/motion";
import { ChipGroup } from "@/product/picks/Controls";
import { fromParlays, fromPicks, recap, within, type Recap as RecapData } from "./recapData";
import { fmtUnits } from "./units";

type Scope = "picks" | "parlays";
const PERIODS: readonly number[] = [30, 90, 0];
const POSITIVE = "var(--color-positive)";
const NEGATIVE = "var(--color-negative)";
const GOLD = "var(--color-gold)";
const PRIMARY = "var(--color-primary)";
const GRID = "var(--color-border)";
const TICK = { fill: "var(--color-subtle-foreground)", fontSize: 10 };
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

const units = (n: number) => fmtUnits(Math.round(n * 100) / 100);

function Kpi({
  label,
  value,
  tone,
  hint,
}: {
  label: string;
  value: ReactNode;
  tone?: string | undefined;
  hint?: ReactNode;
}) {
  return (
    <div className="min-w-0 rounded-xl border border-border bg-card px-4 py-3">
      <div className="text-label leading-tight text-subtle-foreground">{label}</div>
      <div className={cn("numeric mt-1.5 text-xl font-semibold leading-none", tone)}>{value}</div>
      {hint ? <div className="mt-1 text-caption text-muted-foreground">{hint}</div> : null}
    </div>
  );
}

function Counted({ value, format }: { value: number | null; format: (n: number) => string }) {
  const shown = useCountUp(value);
  return <>{shown === null ? DASH : format(shown)}</>;
}

function ChartCard({
  title,
  subtitle,
  children,
  testId,
}: {
  title: string;
  subtitle?: string | undefined;
  children: ReactNode;
  testId: string;
}) {
  return (
    <Card className="p-4" as="article">
      <h3 className="font-display text-sm font-semibold">{title}</h3>
      {subtitle ? <p className="mt-0.5 text-caption text-muted-foreground">{subtitle}</p> : null}
      <div className="mt-3 h-52" data-testid={testId}>
        {children}
      </div>
    </Card>
  );
}

function tone(n: number | null): string | undefined {
  if (n === null || n === 0) return undefined;
  return n > 0 ? "text-positive" : "text-negative";
}

function Kpis({ r }: { r: RecapData }) {
  const current = r.streaks.current;
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6" data-testid="recap-kpis">
      <Kpi
        label={t("records.recap.kpi.settled")}
        value={<Counted value={r.settled} format={(n) => fmtInt(Math.round(n))} />}
        hint={t("records.recap.kpi.record", { won: r.wins, lost: r.losses, void: r.voids })}
      />
      <Kpi
        label={t("records.recap.kpi.hitRate")}
        value={<Counted value={r.hitRate} format={(n) => fmtPct(n, 0)} />}
      />
      <Kpi
        label={t("records.recap.kpi.profit")}
        value={<Counted value={r.profit} format={units} />}
        tone={tone(r.profit)}
      />
      <Kpi
        label={t("records.recap.kpi.roi")}
        value={<Counted value={r.roi} format={(n) => fmtPct(n, 1)} />}
        tone={tone(r.roi)}
      />
      <Kpi
        label={t("records.recap.kpi.avgOdds")}
        value={<Counted value={r.avgOdds} format={(n) => fmtOdds(n)} />}
        hint={
          r.avgOddsWon !== null
            ? t("records.recap.kpi.avgOddsWon", { odds: fmtOdds(r.avgOddsWon) })
            : undefined
        }
      />
      <Kpi
        label={t("records.recap.kpi.bestStreak")}
        value={<Counted value={r.streaks.bestWin} format={(n) => fmtInt(Math.round(n))} />}
        hint={
          current
            ? t(`records.recap.kpi.current.${current.kind}`, { count: current.length })
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
    <ChartCard
      title={t("records.recap.cumulative.title")}
      subtitle={t("records.recap.cumulative.subtitle")}
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
            formatter={(v: number) => [units(v), t("records.recap.cumulative.total")]}
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
    </ChartCard>
  );
}

function PerDay({ r, animate }: { r: RecapData; animate: boolean }) {
  const data = r.days.map((d) => ({ ...d, label: shortDay(d.day) }));
  return (
    <ChartCard
      title={t("records.recap.daily.title")}
      subtitle={
        r.bestDay && r.worstDay
          ? t("records.recap.daily.subtitle", {
              best: shortDay(r.bestDay.day),
              bestProfit: units(r.bestDay.profit),
              worst: shortDay(r.worstDay.day),
              worstProfit: units(r.worstDay.profit),
            })
          : undefined
      }
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
            formatter={(v: number, _n: string, item: { payload?: { count?: number } }) => [
              `${units(v)} · ${t("records.recap.daily.count", { count: item.payload?.count ?? 0 })}`,
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
    </ChartCard>
  );
}

function OddsRanges({ r, animate }: { r: RecapData; animate: boolean }) {
  const data = r.byOdds.map((b) => ({
    ...b,
    label: t(`records.recap.odds.bucket.${b.key}`),
  }));
  return (
    <ChartCard
      title={t("records.recap.odds.title")}
      subtitle={
        r.avgOdds !== null
          ? t("records.recap.odds.subtitle", { odds: fmtOdds(r.avgOdds) })
          : undefined
      }
      testId="recap-odds"
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke={GRID} />
          <XAxis dataKey="label" tick={TICK} tickLine={false} axisLine={false} />
          <YAxis tick={TICK} tickLine={false} axisLine={false} width={30} allowDecimals={false} />
          <Tooltip
            {...TOOLTIP}
            formatter={(
              v: number,
              _n: string,
              item: { payload?: { hitRate?: number | null; profit?: number } },
            ) => [
              t("records.recap.odds.tooltip", {
                count: v,
                hit: fmtPct(item.payload?.hitRate ?? null, 0),
                profit: units(item.payload?.profit ?? 0),
              }),
              t("records.recap.odds.count"),
            ]}
          />
          <Bar
            dataKey="count"
            fill={GOLD}
            radius={[3, 3, 0, 0]}
            isAnimationActive={animate}
            animationDuration={DRAW_MS}
            animationEasing="ease-out"
          />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

function Markets({ r, animate }: { r: RecapData; animate: boolean }) {
  const data = r.byMarket.map((m) => ({
    ...m,
    label: marketName(m.market),
    pct: m.hitRate === null ? 0 : Math.round(m.hitRate * 100),
  }));
  return (
    <ChartCard
      title={t("records.recap.markets.title")}
      subtitle={t("records.recap.markets.subtitle")}
      testId="recap-markets"
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 0, right: 16, bottom: 0, left: 0 }}>
          <CartesianGrid horizontal={false} stroke={GRID} />
          <XAxis
            type="number"
            domain={[0, 100]}
            tick={TICK}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v: number) => `${v}%`}
          />
          <YAxis
            type="category"
            dataKey="label"
            tick={TICK}
            tickLine={false}
            axisLine={false}
            width={96}
          />
          <Tooltip
            {...TOOLTIP}
            formatter={(
              v: number,
              _n: string,
              item: { payload?: { count?: number; profit?: number } },
            ) => [
              t("records.recap.markets.tooltip", {
                pct: v,
                count: item.payload?.count ?? 0,
                profit: units(item.payload?.profit ?? 0),
              }),
              t("records.recap.markets.hitRate"),
            ]}
          />
          <Bar
            dataKey="pct"
            fill={PRIMARY}
            radius={[0, 3, 3, 0]}
            isAnimationActive={animate}
            animationDuration={DRAW_MS}
            animationEasing="ease-out"
          />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

function Streak({ r, animate }: { r: RecapData; animate: boolean }) {
  const current = r.streaks.current;
  return (
    <Card className="p-4" as="article">
      <h3 className="font-display text-sm font-semibold">{t("records.recap.streak.title")}</h3>
      <p className="mt-0.5 text-caption text-muted-foreground">
        {t("records.recap.streak.subtitle", { count: r.last.length })}
      </p>
      <ol
        className="mt-4 flex flex-wrap gap-1.5"
        data-testid="recap-streak"
        aria-label={t("records.recap.streak.title")}
      >
        {r.last.map((x, i) => (
          <li
            key={i}
            title={t(`records.recap.streak.${x}`)}
            style={animate ? { animationDelay: `${i * 45}ms` } : undefined}
            className={cn(
              "flex h-7 w-7 items-center justify-center rounded-full text-[0.65rem] font-bold",
              x === "win"
                ? "bg-positive-soft text-positive ring-1 ring-positive/40"
                : "bg-negative-soft text-negative ring-1 ring-negative/40",
              animate && "animate-in fade-in zoom-in-50 fill-mode-both duration-300",
            )}
          >
            {x === "win" ? t("records.recap.streak.w") : t("records.recap.streak.l")}
          </li>
        ))}
      </ol>
      <dl className="mt-4 grid grid-cols-3 gap-3 text-center">
        <div>
          <dt className="text-label text-subtle-foreground">{t("records.recap.streak.current")}</dt>
          <dd
            className={cn(
              "numeric mt-1 flex items-center justify-center gap-1 text-lg font-semibold",
              current?.kind === "win" ? "text-positive" : current ? "text-negative" : undefined,
            )}
          >
            {current ? (
              <>
                {current.kind === "win" ? (
                  <Flame aria-hidden className="h-4 w-4" />
                ) : (
                  <TrendingDown aria-hidden className="h-4 w-4" />
                )}
                {current.length}
              </>
            ) : (
              DASH
            )}
          </dd>
        </div>
        <div>
          <dt className="text-label text-subtle-foreground">{t("records.recap.streak.bestWin")}</dt>
          <dd className="numeric mt-1 text-lg font-semibold text-positive">{r.streaks.bestWin}</dd>
        </div>
        <div>
          <dt className="text-label text-subtle-foreground">
            {t("records.recap.streak.worstLoss")}
          </dt>
          <dd className="numeric mt-1 text-lg font-semibold text-negative">
            {r.streaks.worstLoss}
          </dd>
        </div>
      </dl>
    </Card>
  );
}

export function Recap() {
  const picks = useQuery(live.myPicks);
  const parlays = useQuery(live.myParlays);
  const [scope, setScope] = useState<Scope>("picks");
  const [period, setPeriod] = useState<number>(30);
  const reduced = useReducedMotion();
  const query = scope === "picks" ? picks : parlays;
  const records = useMemo(
    () =>
      scope === "picks" ? fromPicks(picks.data?.data ?? []) : fromParlays(parlays.data?.data ?? []),
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
        <div className="grid gap-3 lg:grid-cols-2">
          <Cumulative r={r} animate={animate} />
          <PerDay r={r} animate={animate} />
          <OddsRanges r={r} animate={animate} />
          <Streak r={r} animate={animate} />
          {scope === "picks" && r.byMarket.length ? <Markets r={r} animate={animate} /> : null}
        </div>
        <p className="text-caption text-subtle-foreground">{t("records.recap.note")}</p>
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
