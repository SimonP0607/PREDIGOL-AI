import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import type { CalibrationBin, LineMovementSeries, SeriesPoint } from "@/types/domain";
import { timeOf } from "@/lib/format";
import { sized, type ChartSize } from "./chartSize";

const axis = {
  stroke: "var(--color-border-strong)",
  tick: { fill: "var(--color-subtle-foreground)", fontSize: 10 },
  tickLine: false,
};

const tooltipStyle = {
  contentStyle: {
    background: "var(--color-card)",
    border: "1px solid var(--color-border-strong)",
    borderRadius: 6,
    fontSize: 11,
  },
  labelStyle: { color: "var(--color-muted-foreground)", fontSize: 11 },
  itemStyle: { color: "var(--color-foreground)", fontSize: 11 },
} as const;

const seriesColors = [
  "var(--color-primary)",
  "var(--color-info)",
  "var(--color-warning)",
  "var(--color-muted-foreground)",
];

export function ChartContainer({
  title,
  subtitle,
  demo = false,
  height = 220,
  actions,
  children,
  className,
}: {
  title: string;
  subtitle?: string;
  demo?: boolean;
  height?: number;
  actions?: React.ReactNode;
  children: React.ReactElement;
  className?: string;
}) {
  return (
    <section className={cn("surface-panel overflow-hidden", className)}>
      <header className="flex flex-wrap items-start justify-between gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <h3 className="text-title">{title}</h3>
          {subtitle ? (
            <p className="mt-0.5 text-caption text-muted-foreground">{subtitle}</p>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {actions}
          {demo ? <StatusBadge tone="warning">{t("admin.shell.demoData")}</StatusBadge> : null}
        </div>
      </header>
      <div className="px-2 py-3" style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          {children}
        </ResponsiveContainer>
      </div>
    </section>
  );
}

export function LineMovementChart({
  series,
  width,
  height,
}: { series: LineMovementSeries[] } & ChartSize) {
  const times = series[0]?.points.map((p) => p.at) ?? [];
  const data = times.map((at, i) => {
    const row: Record<string, number | string> = { at: timeOf(at) };
    for (const s of series) row[s.bookmaker] = s.points[i]?.odds ?? Number.NaN;
    return row;
  });
  return (
    <LineChart
      {...sized({ width, height })}
      data={data}
      margin={{ top: 6, right: 12, bottom: 0, left: -18 }}
    >
      <CartesianGrid stroke="var(--color-border)" strokeDasharray="2 4" vertical={false} />
      <XAxis dataKey="at" {...axis} />
      <YAxis domain={["dataMin - 0.06", "dataMax + 0.06"]} {...axis} width={46} />
      <Tooltip {...tooltipStyle} />
      {series.map((s, i) => (
        <Line
          key={s.bookmaker}
          type="monotone"
          dataKey={s.bookmaker}
          stroke={seriesColors[i % seriesColors.length]}
          strokeWidth={s.bookmaker === "Consensus" ? 2 : 1.4}
          strokeDasharray={s.bookmaker === "Consensus" ? "4 3" : undefined}
          dot={false}
          isAnimationActive={false}
        />
      ))}
    </LineChart>
  );
}

export function CalibrationChart({ bins, width, height }: { bins: CalibrationBin[] } & ChartSize) {
  const data = bins.map((b) => ({
    predicted: Number((b.predicted * 100).toFixed(1)),
    observed: Number((b.observed * 100).toFixed(1)),
    sample: b.sample,
  }));
  return (
    <ScatterChart {...sized({ width, height })} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
      <CartesianGrid stroke="var(--color-border)" strokeDasharray="2 4" />
      <XAxis
        type="number"
        dataKey="predicted"
        domain={[0, 100]}
        name={t("admin.ui.predicted")}
        unit="%"
        {...axis}
      />
      <YAxis
        type="number"
        dataKey="observed"
        domain={[0, 100]}
        name={t("admin.ui.observed")}
        unit="%"
        width={46}
        {...axis}
      />
      <Tooltip {...tooltipStyle} cursor={{ strokeDasharray: "3 3" }} />
      <ReferenceLine
        segment={[
          { x: 0, y: 0 },
          { x: 100, y: 100 },
        ]}
        stroke="var(--color-border-strong)"
        strokeDasharray="4 4"
      />
      <Scatter data={data} fill="var(--color-primary)" isAnimationActive={false} />
    </ScatterChart>
  );
}

export function EquityCurve({ points, width, height }: { points: SeriesPoint[] } & ChartSize) {
  return (
    <AreaChart
      {...sized({ width, height })}
      data={points}
      margin={{ top: 6, right: 12, bottom: 0, left: -18 }}
    >
      <defs>
        <linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--color-primary)" stopOpacity={0.28} />
          <stop offset="100%" stopColor="var(--color-primary)" stopOpacity={0} />
        </linearGradient>
      </defs>
      <CartesianGrid stroke="var(--color-border)" strokeDasharray="2 4" vertical={false} />
      <XAxis dataKey="at" {...axis} />
      <YAxis width={46} {...axis} />
      <Tooltip {...tooltipStyle} />
      <Area
        type="monotone"
        dataKey="value"
        stroke="var(--color-primary)"
        strokeWidth={1.6}
        fill="url(#equityFill)"
        isAnimationActive={false}
      />
    </AreaChart>
  );
}

export function DrawdownChart({ points, width, height }: { points: SeriesPoint[] } & ChartSize) {
  return (
    <AreaChart
      {...sized({ width, height })}
      data={points}
      margin={{ top: 6, right: 12, bottom: 0, left: -18 }}
    >
      <CartesianGrid stroke="var(--color-border)" strokeDasharray="2 4" vertical={false} />
      <XAxis dataKey="at" {...axis} />
      <YAxis width={46} {...axis} />
      <Tooltip {...tooltipStyle} />
      <Area
        type="monotone"
        dataKey="value"
        stroke="var(--color-negative)"
        strokeWidth={1.4}
        fill="var(--color-negative)"
        fillOpacity={0.12}
        isAnimationActive={false}
      />
    </AreaChart>
  );
}

export function MonthlyBars({
  data,
  dataKey = "value",
  xKey = "month",
  width,
  height,
}: {
  data: Array<Record<string, string | number>>;
  dataKey?: string;
  xKey?: string;
} & ChartSize) {
  return (
    <BarChart
      {...sized({ width, height })}
      data={data}
      margin={{ top: 6, right: 12, bottom: 0, left: -18 }}
    >
      <CartesianGrid stroke="var(--color-border)" strokeDasharray="2 4" vertical={false} />
      <XAxis dataKey={xKey} {...axis} />
      <YAxis width={46} {...axis} />
      <Tooltip {...tooltipStyle} />
      <ReferenceLine y={0} stroke="var(--color-border-strong)" />
      <Bar
        dataKey={dataKey}
        fill="var(--color-info)"
        isAnimationActive={false}
        radius={[2, 2, 0, 0]}
      />
    </BarChart>
  );
}

export function ProbabilityBuckets({
  bins,
  width,
  height,
}: { bins: CalibrationBin[] } & ChartSize) {
  const data = bins.map((b) => ({
    bucket: `${Math.round(b.predicted * 100)}%`,
    sample: b.sample,
  }));
  return (
    <BarChart
      {...sized({ width, height })}
      data={data}
      margin={{ top: 6, right: 12, bottom: 0, left: -18 }}
    >
      <CartesianGrid stroke="var(--color-border)" strokeDasharray="2 4" vertical={false} />
      <XAxis dataKey="bucket" {...axis} />
      <YAxis width={46} {...axis} />
      <Tooltip {...tooltipStyle} />
      <Bar
        dataKey="sample"
        fill="var(--color-primary)"
        isAnimationActive={false}
        radius={[2, 2, 0, 0]}
      />
    </BarChart>
  );
}
