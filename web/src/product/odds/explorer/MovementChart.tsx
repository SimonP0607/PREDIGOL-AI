/**
 * The movement charts, loaded only when a reader opens «Movimiento» (React.lazy): recharts never travels in the explorer's
 * own bundle (plan Cuotas, E17). One small chart per selection on a shared time axis, each with its own price range (a
 * favourite at 1,20 and an outsider at 19,50 cannot share one); the summary with its arrow is drawn by the panel, outside.
 */
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipProps,
} from "recharts";
import { t } from "@/lib/i18n";
import { fmtOdds } from "@/lib/i18n/format";
import { dayKey, formatDate, formatTime } from "@/lib/time";
import { oddsDomain, oddsTicks, type MovePoint } from "../movement";

const LINE = "var(--color-info)";
const SURFACE = "var(--color-card)";

const stamp = (v: number) => `${formatDate(v)} ${formatTime(v)}`;

export interface ChartLine {
  key: string;
  title: string;
  points: MovePoint[];
}

export default function MovementChart({
  lines,
  extent,
}: {
  lines: readonly ChartLine[];
  extent: [number, number];
}) {
  const sameDay = dayKey(extent[0]) === dayKey(extent[1]);
  return (
    <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3" data-testid="explorer-chart">
      {lines.map((l) => {
        const domain = oddsDomain(l.points.map((p) => p.odds));
        return (
          <figure
            key={l.key}
            className="min-w-0 rounded-md border border-border/70 bg-card px-2.5 pb-1 pt-2"
          >
            <figcaption className="truncate text-xs font-semibold">{l.title}</figcaption>
            <div aria-hidden className="mt-1 h-24">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={l.points} margin={{ top: 8, right: 6, bottom: 0, left: 0 }}>
                  <CartesianGrid vertical={false} stroke="var(--color-border)" />
                  <XAxis
                    dataKey="t"
                    type="number"
                    scale="time"
                    domain={extent}
                    ticks={extent}
                    interval={0}
                    height={18}
                    tickLine={false}
                    axisLine={{ stroke: "var(--color-border-strong)" }}
                    tickFormatter={(v: number) => (sameDay ? formatTime(v) : stamp(v))}
                    tick={{ fill: "var(--color-subtle-foreground)", fontSize: 10 }}
                  />
                  <YAxis
                    dataKey="odds"
                    type="number"
                    domain={domain}
                    ticks={oddsTicks(domain)}
                    allowDataOverflow
                    width={38}
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={(v: number) => fmtOdds(v)}
                    tick={{ fill: "var(--color-subtle-foreground)", fontSize: 10 }}
                  />
                  <Tooltip
                    content={<PointTip />}
                    cursor={{ stroke: "var(--color-border-strong)", strokeWidth: 1 }}
                    isAnimationActive={false}
                  />
                  <Line
                    type="linear"
                    dataKey="odds"
                    stroke={LINE}
                    strokeWidth={2}
                    isAnimationActive={false}
                    dot={l.points.length <= 8 ? { r: 3, fill: LINE, stroke: SURFACE } : false}
                    activeDot={{ r: 4, fill: LINE, stroke: SURFACE, strokeWidth: 2 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
            {/* What the chart draws, as a table for a screen reader. */}
            <table className="sr-only">
              <caption>{l.title}</caption>
              <thead>
                <tr>
                  <th scope="col">{t("explorer.movement.time")}</th>
                  <th scope="col">{t("explorer.price.best")}</th>
                  <th scope="col">{t("explorer.price.bookmaker")}</th>
                </tr>
              </thead>
              <tbody>
                {l.points.map((p) => (
                  <tr key={p.t}>
                    <td>{stamp(p.t)}</td>
                    <td>{fmtOdds(p.odds)}</td>
                    <td>{p.bookmaker}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </figure>
        );
      })}
    </div>
  );
}

function PointTip({ active, payload }: TooltipProps<number, string>) {
  const point = payload?.[0]?.payload as MovePoint | undefined;
  if (!active || !point) return null;
  return (
    <div className="rounded-md border border-border-strong bg-popover px-2.5 py-1.5 shadow-lg">
      <div className="numeric text-sm font-semibold text-foreground">{fmtOdds(point.odds)}</div>
      <div className="text-caption text-muted-foreground">{point.bookmaker}</div>
      <div className="numeric text-caption text-subtle-foreground">{stamp(point.t)}</div>
    </div>
  );
}
