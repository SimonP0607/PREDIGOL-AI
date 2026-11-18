/**
 * The small figures of plan EA: the xG line with its moving mean (catalogue n.º 11), the game-state bar (n.º 4), the last-five
 * strip of a player (V2·2) and his minutes of the last ten, the volume x accuracy scatter of a position (n.º 8) and the halves.
 */
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { t } from "@/lib/i18n";
import { localFixed } from "@/lib/i18n/format";
import { isMissing } from "@/lib/api/v1/types_intelligence";
import type {
  GameStates,
  HalfSplit,
  MatchPoint,
  ScatterPoint,
  StripItem,
} from "@/lib/api/v1/types_stats";
import { cn } from "@/lib/utils";
import { figName, num } from "./format";

const tooltipStyle = {
  contentStyle: {
    background: "var(--color-card)",
    border: "1px solid var(--color-border-strong)",
    borderRadius: 8,
    fontSize: 12,
  },
  labelStyle: { color: "var(--color-muted-foreground)" },
} as const;

export function XgLine({ series, testId }: { series: MatchPoint[]; testId?: string }) {
  const data = series.map((p, i) => ({
    i: i + 1,
    opponent: p.opponent.name,
    f: isMissing(p.xg_for_avg5) ? null : p.xg_for_avg5,
    a: isMissing(p.xg_against_avg5) ? null : p.xg_against_avg5,
  }));
  return (
    <div className="h-44 w-full" data-testid={testId}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart
          data={data}
          margin={{ top: 6, right: 8, left: -18, bottom: 0 }}
          accessibilityLayer
        >
          <CartesianGrid stroke="var(--color-border)" vertical={false} />
          <XAxis
            dataKey="i"
            tick={{ fill: "var(--color-subtle-foreground)", fontSize: 10 }}
            tickLine={false}
          />
          <YAxis
            tick={{ fill: "var(--color-subtle-foreground)", fontSize: 10 }}
            tickLine={false}
            width={40}
          />
          <Tooltip
            {...tooltipStyle}
            labelFormatter={(_, p) => String(p?.[0]?.payload?.opponent ?? "")}
            formatter={(v: unknown, name: unknown) => [localFixed(Number(v), 2), String(name)]}
          />
          <Line
            type="monotone"
            dataKey="f"
            name={t("stats.xgFor")}
            stroke="var(--color-primary)"
            strokeWidth={2.5}
            dot={false}
            connectNulls
          />
          <Line
            type="monotone"
            dataKey="a"
            name={t("stats.xgAgainst")}
            stroke="var(--color-negative)"
            strokeWidth={2}
            dot={false}
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function StateBar({ states }: { states: GameStates }) {
  const total = Math.max(
    1,
    states.minutes_leading + states.minutes_level + states.minutes_trailing,
  );
  const share = (v: number) => (100 * v) / total;
  const p = (v: number) => `${Math.round(share(v))} %`;
  return (
    <div className="space-y-2">
      <div className="flex h-4 overflow-hidden rounded-full" aria-hidden>
        <span className="bg-positive" style={{ width: `${share(states.minutes_leading)}%` }} />
        <span className="bg-border-strong" style={{ width: `${share(states.minutes_level)}%` }} />
        <span className="bg-negative" style={{ width: `${share(states.minutes_trailing)}%` }} />
      </div>
      <p className="flex flex-wrap gap-3 text-caption text-muted-foreground">
        <span>
          <span aria-hidden className="text-positive">
            ●
          </span>{" "}
          {t("stats.leading", { pct: p(states.minutes_leading) })}
        </span>
        <span>
          <span aria-hidden className="text-subtle-foreground">
            ●
          </span>{" "}
          {t("stats.level", { pct: p(states.minutes_level) })}
        </span>
        <span>
          <span aria-hidden className="text-negative">
            ●
          </span>{" "}
          {t("stats.trailing", { pct: p(states.minutes_trailing) })}
        </span>
      </p>
      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-xl bg-elevated p-3">
          <div className="numeric-lg text-positive">{states.points_rescued}</div>
          <div className="text-caption text-muted-foreground">{t("stats.rescued")}</div>
        </div>
        <div className="rounded-xl bg-elevated p-3">
          <div className="numeric-lg text-negative">{states.points_ceded}</div>
          <div className="text-caption text-muted-foreground">{t("stats.ceded")}</div>
        </div>
      </div>
    </div>
  );
}

export function Halves({ halves }: { halves: HalfSplit }) {
  const rows = [
    {
      label: t("stats.halvesFor"),
      a: halves.goals_for_1h,
      b: halves.goals_for_2h,
      tone: "bg-primary",
    },
    {
      label: t("stats.halvesAgainst"),
      a: halves.goals_against_1h,
      b: halves.goals_against_2h,
      tone: "bg-negative",
    },
  ];
  const max = Math.max(0.5, ...rows.flatMap((r) => [r.a, r.b]));
  return (
    <div className="space-y-2">
      {rows.map((r) => (
        <div key={r.label} className="grid grid-cols-[5rem_1fr] items-center gap-2 text-caption">
          <span className="text-muted-foreground">{r.label}</span>
          <div className="space-y-1">
            {[
              [t("stats.half1"), r.a],
              [t("stats.half2"), r.b],
            ].map(([h, v]) => (
              <div key={String(h)} className="flex items-center gap-2">
                <span className="w-6 text-subtle-foreground">{h}</span>
                <span className="h-2.5 flex-1 rounded-full bg-elevated">
                  <span
                    className={cn("block h-full rounded-full", r.tone)}
                    style={{ width: `${(100 * Number(v)) / max}%` }}
                  />
                </span>
                <span className="numeric w-10 text-right">{num(Number(v), 2)}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

/** The last five appearances of one metric, with their mean - the strip the bookmakers show beside a prop. */
export function LastFive({ strip, metric }: { strip: StripItem[]; metric: string }) {
  const values = strip.map((s) => s.values.find((v) => v.key === metric)?.value);
  const known = values.filter((v): v is number => typeof v === "number");
  const mean = known.length ? known.reduce((a, b) => a + b, 0) / known.length : null;
  const max = Math.max(1, ...known);
  return (
    <div className="space-y-2">
      <div
        className="flex items-end gap-2"
        aria-label={`${figName(metric)}: ${values.map((v) => (typeof v === "number" ? v : "—")).join(", ")}`}
      >
        {strip.map((s, i) => {
          const v = values[i];
          return (
            <div key={s.fixture_id} className="flex flex-1 flex-col items-center gap-1">
              <span className="numeric text-sm font-semibold">
                {typeof v === "number" ? v : "—"}
              </span>
              <span className="flex h-12 w-full items-end rounded-md bg-elevated">
                <span
                  className="block w-full rounded-md bg-primary-dim"
                  style={{ height: `${typeof v === "number" ? (100 * v) / max : 0}%` }}
                />
              </span>
              <span className="w-full truncate text-center text-[11px] text-subtle-foreground">
                {s.opponent.name}
              </span>
            </div>
          );
        })}
      </div>
      <p className="text-caption text-muted-foreground">
        {t("stats.last5Mean")}:{" "}
        <span className="numeric">{mean === null ? "—" : localFixed(mean, 1)}</span>
      </p>
    </div>
  );
}

export function MinutesBars({
  items,
}: {
  items: { fixture_id: number; minutes: number; starter: boolean }[];
}) {
  return (
    <div className="flex h-16 items-end gap-1" aria-hidden>
      {items.map((m) => (
        <span
          key={m.fixture_id}
          className={cn("flex-1 rounded-t-md", m.starter ? "bg-primary" : "bg-primary-dim/60")}
          style={{ height: `${Math.max(6, (100 * Math.min(m.minutes, 95)) / 95)}%` }}
          title={`${m.minutes}'`}
        />
      ))}
    </div>
  );
}

export function VolumeAccuracy({
  background,
  players,
  testId,
}: {
  background: ScatterPoint[];
  players: { name: string; point: ScatterPoint | null; color: string }[];
  testId?: string;
}) {
  return (
    <div className="h-56 w-full" data-testid={testId}>
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 8, right: 10, left: -12, bottom: 4 }} accessibilityLayer>
          <CartesianGrid stroke="var(--color-border)" />
          <XAxis
            type="number"
            dataKey="shots_per90"
            name={t("stats.scatterX")}
            tick={{ fill: "var(--color-subtle-foreground)", fontSize: 10 }}
          />
          <YAxis
            type="number"
            dataKey="on_target_pct"
            name={t("stats.scatterY")}
            domain={[0, 100]}
            tick={{ fill: "var(--color-subtle-foreground)", fontSize: 10 }}
          />
          <ZAxis range={[28, 28]} />
          <Tooltip {...tooltipStyle} />
          <Scatter data={background} fill="var(--color-border-strong)" />
          {players.map((p) =>
            p.point ? (
              <Scatter key={p.name} name={p.name} data={[p.point]} fill={p.color} shape="circle" />
            ) : null,
          )}
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}
