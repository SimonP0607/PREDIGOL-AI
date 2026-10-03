/**
 * "Movimiento": how the best available price of each selection moved before kick-off.
 *
 * One small chart per selection, on a shared time axis: a favourite at 1,20 and an
 * outsider at 19,50 cannot share a y-scale without flattening the favourite, so each
 * gets its own range (never narrower than ±2,5 %, so a tiny move is not inflated).
 */
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
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
import { Minus, TrendingDown, TrendingUp } from "lucide-react";
import { live } from "@/lib/api/v1/queries";
import type { BestMarket, TeamBadge } from "@/lib/api/v1/types_product";
import { t } from "@/lib/i18n";
import { fmtOdds, fmtSignedPct } from "@/lib/i18n/format";
import { dayKey, formatDate, formatTime } from "@/lib/time";
import { cn } from "@/lib/utils";
import { ErrorState, SkeletonBlock } from "@/product/shared/States";
import { selectionLabel } from "@/product/shared/markets";
import { boardSelections } from "./board";
import { bestPriceLines, oddsDomain, oddsTicks, timeExtent, type MovePoint } from "./movement";

/** One series per chart, so one hue for all of them; the caption names the selection. */
const LINE = "var(--color-info)";
const SURFACE = "var(--color-card)";
const MINUTE = 60_000;
/** Up to this many captures every point gets a marker; beyond it, only the latest. */
const ALL_DOTS_MAX = 8;

const stamp = (t: number) => `${formatDate(t)} ${formatTime(t)}`;

export function MovementPanel({
  id,
  fixtureId,
  market,
  home,
  away,
}: {
  id: string;
  fixtureId: number;
  market: BestMarket;
  home: TeamBadge;
  away: TeamBadge;
}) {
  const query = useQuery({
    ...live.fixtureOdds(String(fixtureId), market.market_key),
    staleTime: 5 * MINUTE,
  });
  const selections = useMemo(() => boardSelections(market), [market]);
  const lines = useMemo(
    () =>
      bestPriceLines(query.data?.data.series.data ?? [], {
        market: market.market_key,
        line: market.line,
        selections,
      }).filter((l) => l.points.length > 0),
    [query.data, market.market_key, market.line, selections],
  );
  const extent = timeExtent(lines);

  let body;
  if (query.isPending) {
    body = <SkeletonBlock className="mt-3 h-32" />;
  } else if (query.isError) {
    body = <ErrorState error={query.error} onRetry={() => void query.refetch()} className="py-4" />;
  } else if (!extent) {
    body = <p className="mt-2 text-xs text-muted-foreground">{t("odds.movement.empty")}</p>;
  } else {
    body = (
      <div
        className={cn(
          "mt-3 grid gap-2.5",
          lines.length >= 3 ? "sm:grid-cols-3" : lines.length === 2 && "sm:grid-cols-2",
        )}
      >
        {lines.map((l) => (
          <SelectionChart
            key={l.selection}
            title={selectionLabel({
              market_key: market.market_key,
              selection: l.selection,
              line: market.line,
              home: home.name,
              away: away.name,
            })}
            points={l.points}
            extent={extent}
          />
        ))}
      </div>
    );
  }

  return (
    <div
      id={id}
      data-testid="odds-movement"
      className="mt-3 rounded-lg border border-border bg-background/50 p-3"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
        <h4 className="font-display text-xs font-semibold">{t("odds.movement.title")}</h4>
        <p className="text-caption text-subtle-foreground">{t("odds.movement.help")}</p>
      </div>
      {body}
    </div>
  );
}

function SelectionChart({
  title,
  points,
  extent,
}: {
  title: string;
  points: MovePoint[];
  extent: [number, number];
}) {
  const first = points[0];
  const last = points[points.length - 1];
  const domain = oddsDomain(points.map((p) => p.odds));
  const sameDay = dayKey(extent[0]) === dayKey(extent[1]);
  if (!first || !last) return null;
  const change = points.length > 1 ? last.odds / first.odds - 1 : null;
  const Trend = change === null || change === 0 ? Minus : change > 0 ? TrendingUp : TrendingDown;
  const allDots = points.length <= ALL_DOTS_MAX;

  return (
    <figure className="relative min-w-0 rounded-md border border-border/70 bg-card px-2.5 pb-1 pt-2">
      <figcaption className="flex items-start justify-between gap-2">
        <span className="min-w-0 truncate pt-0.5 text-xs font-semibold">{title}</span>
        <span className="flex shrink-0 flex-col items-end">
          <span className="numeric text-sm font-semibold">{fmtOdds(last.odds)}</span>
          {change !== null ? (
            <span className="numeric inline-flex items-center gap-1 text-caption text-muted-foreground">
              <Trend aria-hidden className="h-3 w-3" />
              {t("odds.movement.from", { odds: fmtOdds(first.odds) })} · {fmtSignedPct(change)}
            </span>
          ) : null}
        </span>
      </figcaption>
      <div aria-hidden className="mt-1 h-24">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 8, right: 6, bottom: 0, left: 0 }}>
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
              tick={(props: TickProps) => <TimeTick {...props} extent={extent} sameDay={sameDay} />}
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
              content={<MoveTooltip />}
              cursor={{ stroke: "var(--color-border-strong)", strokeWidth: 1 }}
              isAnimationActive={false}
              wrapperStyle={{ zIndex: 20 }}
            />
            <Line
              type="linear"
              dataKey="odds"
              stroke={LINE}
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
              isAnimationActive={false}
              dot={({ key, cx, cy, index }: DotRenderProps) => (
                <Dot key={key} cx={cx} cy={cy} show={allDots || index === points.length - 1} />
              )}
              activeDot={{ r: 4, fill: LINE, stroke: SURFACE, strokeWidth: 2 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <table className="sr-only">
        <caption>{title}</caption>
        <thead>
          <tr>
            <th scope="col">{t("odds.movement.time")}</th>
            <th scope="col">{t("common.bestOdds")}</th>
            <th scope="col">{t("common.bookmaker")}</th>
          </tr>
        </thead>
        <tbody>
          {points.map((p) => (
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
}

interface TickProps {
  x?: number;
  y?: number;
  payload?: { value: number };
}

/** The first and last capture, anchored inside the plot so neither label is cut. */
function TimeTick({
  x,
  y,
  payload,
  extent,
  sameDay,
}: TickProps & { extent: [number, number]; sameDay: boolean }) {
  if (x === undefined || y === undefined || !payload) return <g />;
  const v = payload.value;
  const anchor = v <= extent[0] ? "start" : v >= extent[1] ? "end" : "middle";
  return (
    <text
      x={x}
      y={y}
      dy="0.71em"
      textAnchor={anchor}
      fill="var(--color-subtle-foreground)"
      fontSize={10}
      className="numeric"
    >
      {sameDay ? formatTime(v) : stamp(v)}
    </text>
  );
}

/** What recharts hands a custom dot renderer (the key included: it must be set by hand). */
interface DotRenderProps {
  cx?: number | undefined;
  cy?: number | undefined;
  index?: number | undefined;
  key?: string | undefined;
}

/** A marker with a ring of the card colour, so it stays legible on the line. */
function Dot({
  cx,
  cy,
  show,
}: {
  cx?: number | undefined;
  cy?: number | undefined;
  show: boolean;
}) {
  if (!show || cx === undefined || cy === undefined) return <g />;
  return <circle cx={cx} cy={cy} r={4} fill={LINE} stroke={SURFACE} strokeWidth={2} />;
}

/** The price leads; where and when follow. */
function MoveTooltip({ active, payload }: TooltipProps<number, string>) {
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
