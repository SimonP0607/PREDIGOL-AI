/**
 * The three pieces of sheets T01 and T07 the page did not draw (plan maestro unificado, UX-144; data from BE-044):
 *
 * - «Unidades acumuladas»: the running units of the published picks, day by day, as a line over the zero - its lowest point
 *   marked and said in words as well as its last one, and the same points as a table for whoever does not read charts.
 * - «¿Estima bien?»: for each range of what PrediGol said when it published, a bar to what it said and a white mark where
 *   it landed, with the picks of the range. The probability is the one stored when the pick was published: drawn, never
 *   computed here.
 * - «Por mercado»: the kinds of bet as one table - picks, won and lost, units, return.
 *
 * Every piece keeps the page's rule: below the minimum sample, the counts and the sentence that says why, never a figure.
 */
import { BarChart3, Gauge } from "lucide-react";
import { useEffect, useId, useRef, useState, type RefObject } from "react";
import { t } from "@/lib/i18n";
import { toNumber } from "@/lib/i18n/format";
import { cn } from "@/lib/utils";
import { fmtUnits } from "@/product/records/units";
import type {
  PicksCalibration,
  Transparency,
  TransparencyMarketTally,
  UnitsPoint,
} from "@/lib/api/v1/types_transparency";
import { Block, Note } from "./parts";
import { dayText, intText, percentOf, roiText } from "./model";

// ---- the running units ------------------------------------------------------------------------------------------------

const WIDE = 640;
const PAD = { top: 22, right: 18, bottom: 26, left: 40 };

/** The ticks of the units' axis: whole units, the zero always among them, at most five. */
export function unitTicks(lo: number, hi: number): number[] {
  const low = Math.min(0, Math.floor(lo));
  const high = Math.max(0, Math.ceil(hi));
  const span = Math.max(1, high - low);
  const step = Math.max(1, Math.ceil(span / 4));
  const out: number[] = [];
  for (let v = Math.floor(low / step) * step; v <= high + step / 2; v += step) out.push(v);
  if (!out.includes(0)) out.push(0);
  return out.sort((a, b) => a - b);
}

export interface ChartGeometry {
  points: { x: number; y: number; units: number; day: string }[];
  ticks: { y: number; value: number }[];
  zero: number;
  lowest: number;
}

/** Where each point of the series sits in the chart (pure). The days are spread by their date, not by their index. */
export function geometry(
  series: readonly UnitsPoint[],
  W: number = WIDE,
  H: number = chartHeight(W),
): ChartGeometry | null {
  if (series.length === 0) return null;
  const values = series.map((p) => toNumber(p.units) ?? 0);
  const ticks = unitTicks(Math.min(...values), Math.max(...values));
  const yLo = ticks[0]!;
  const yHi = ticks[ticks.length - 1]!;
  const times = series.map((p) => Date.parse(`${p.day}T12:00:00Z`));
  const t0 = times[0]!;
  const t1 = times[times.length - 1]!;
  const x = (tm: number) =>
    PAD.left +
    (t1 === t0
      ? (W - PAD.left - PAD.right) / 2
      : ((tm - t0) / (t1 - t0)) * (W - PAD.left - PAD.right));
  const y = (v: number) => PAD.top + ((yHi - v) / (yHi - yLo || 1)) * (H - PAD.top - PAD.bottom);
  const points = series.map((p, i) => ({
    x: x(times[i]!),
    y: y(values[i]!),
    units: values[i]!,
    day: p.day,
  }));
  let lowest = 0;
  values.forEach((v, i) => {
    if (v < values[lowest]!) lowest = i;
  });
  return { points, ticks: ticks.map((v) => ({ y: y(v), value: v })), zero: y(0), lowest };
}

/** A phone's chart is a little shorter; the type stays at its size because the drawing is as wide as its box. */
export function chartHeight(width: number): number {
  return width < 480 ? 190 : 220;
}

/** The width the chart's box has, so the drawing is made at that size and its 11 px labels stay 11 px. */
function useBoxWidth(): [RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(WIDE);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([entry]) => {
      const w = Math.round(entry?.contentRect.width ?? WIDE);
      if (w > 0) setWidth(Math.max(260, w));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

function axisUnits(v: number): string {
  return v === 0
    ? "0"
    : t("transparency.units.axis", { value: `${v > 0 ? "+" : "−"}${Math.abs(v)}` });
}

export function UnitsBlock({ data }: { data: Transparency }) {
  const tableId = useId();
  const [box, W] = useBoxWidth();
  const H = chartHeight(W);
  const series = data.series;
  if (series === undefined) return null; // an older API: the block is not drawn
  const all = data.periods.find((p) => p.period === "all");
  const settled = all?.settled ?? 0;
  const g = series ? geometry(series, W, H) : null;
  return (
    <Block
      id="units"
      title={t("transparency.units.title")}
      subtitle={t("transparency.units.subtitle")}
      icon={<BarChart3 className="h-4 w-4" />}
    >
      {!g ? (
        <Note testId="transparency-units-small">
          {t("transparency.units.small", { min: data.min_sample, count: settled })}
        </Note>
      ) : (
        <>
          <figure className="m-0" ref={box}>
            <svg
              viewBox={`0 0 ${W} ${H}`}
              className="h-auto w-full"
              role="img"
              aria-label={t("transparency.units.summary", {
                from: dayText(series[0]!.day),
                to: dayText(series[series.length - 1]!.day),
                last: fmtUnits(g.points[g.points.length - 1]!.units),
                low: fmtUnits(g.points[g.lowest]!.units),
                lowDay: dayText(g.points[g.lowest]!.day),
              })}
              data-testid="transparency-units-chart"
            >
              {g.ticks.map((tk) => (
                <g key={tk.value}>
                  <line
                    x1={PAD.left}
                    x2={W - PAD.right}
                    y1={tk.y}
                    y2={tk.y}
                    className={tk.value === 0 ? "stroke-muted-foreground/60" : "stroke-border"}
                    strokeWidth={1}
                  />
                  <text
                    x={PAD.left - 8}
                    y={tk.y + 4}
                    textAnchor="end"
                    className="fill-subtle-foreground text-[11px]"
                  >
                    {axisUnits(tk.value)}
                  </text>
                </g>
              ))}
              <path
                d={`M ${g.points.map((p) => `${p.x} ${p.y}`).join(" L ")} L ${g.points[g.points.length - 1]!.x} ${g.zero} L ${g.points[0]!.x} ${g.zero} Z`}
                className="fill-positive/10"
              />
              <polyline
                points={g.points.map((p) => `${p.x},${p.y}`).join(" ")}
                fill="none"
                className="stroke-positive"
                strokeWidth={2.5}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
              {g.points[g.lowest]!.units < 0 ? (
                <circle
                  cx={g.points[g.lowest]!.x}
                  cy={g.points[g.lowest]!.y}
                  r={5}
                  className="fill-negative"
                />
              ) : null}
              <circle
                cx={g.points[g.points.length - 1]!.x}
                cy={g.points[g.points.length - 1]!.y}
                r={5}
                className="fill-positive"
              />
              {[0, Math.floor((g.points.length - 1) / 2), g.points.length - 1]
                .filter((i, k, arr) => arr.indexOf(i) === k)
                .map((i) => (
                  <text
                    key={i}
                    x={g.points[i]!.x}
                    y={H - 6}
                    textAnchor={i === 0 ? "start" : i === g.points.length - 1 ? "end" : "middle"}
                    className="fill-subtle-foreground text-[11px]"
                  >
                    {dayText(g.points[i]!.day)}
                  </text>
                ))}
            </svg>
            <figcaption className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm">
              <span>
                {t("transparency.units.now")}{" "}
                <strong className="numeric" data-testid="transparency-units-last">
                  {fmtUnits(g.points[g.points.length - 1]!.units)}
                </strong>
              </span>
              {g.points[g.lowest]!.units < 0 ? (
                <span className="text-muted-foreground">
                  {t("transparency.units.lowest", {
                    value: fmtUnits(g.points[g.lowest]!.units),
                    day: dayText(g.points[g.lowest]!.day),
                  })}
                </span>
              ) : null}
            </figcaption>
          </figure>
          <Note>{t("transparency.units.same")}</Note>
          <details className="group">
            <summary className="tap-y relative w-fit cursor-pointer text-sm font-semibold text-primary">
              {t("transparency.units.asTable")}
            </summary>
            <table
              id={tableId}
              className="mt-2 w-full text-sm"
              data-testid="transparency-units-table"
            >
              <thead>
                <tr className="text-left text-caption text-subtle-foreground">
                  <th scope="col" className="py-1 font-medium">
                    {t("transparency.units.day")}
                  </th>
                  <th scope="col" className="py-1 text-right font-medium">
                    {t("transparency.units.settled")}
                  </th>
                  <th scope="col" className="py-1 text-right font-medium">
                    {t("transparency.units.total")}
                  </th>
                </tr>
              </thead>
              <tbody className="numeric">
                {series.map((p) => (
                  <tr key={p.day} className="border-t border-border">
                    <th scope="row" className="py-1 font-normal">
                      {dayText(p.day)}
                    </th>
                    <td className="py-1 text-right">{intText(p.settled)}</td>
                    <td className="py-1 text-right">{fmtUnits(p.units)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </>
      )}
    </Block>
  );
}

// ---- «¿Estima bien?» --------------------------------------------------------------------------------------------------

function share(v: string | number | null | undefined): number {
  return Math.max(0, Math.min(1, toNumber(v) ?? 0));
}

export function CalibrationBars({ cal, data }: { cal: PicksCalibration; data: Transparency }) {
  return (
    <ul className="space-y-3" data-testid="transparency-estimate-bins">
      {cal.bins.map((b) => (
        <li key={b.low} className="space-y-1.5">
          <p className="flex flex-wrap items-baseline justify-between gap-x-3 text-sm">
            <span>
              {t("transparency.estimate.said")}{" "}
              <strong className="numeric">{percentOf(b.predicted)} %</strong>
            </span>
            <span className="text-muted-foreground">
              {t("transparency.estimate.picks", { count: b.n })} · {t("transparency.estimate.hit")}{" "}
              <strong className="numeric text-foreground">{percentOf(b.observed)} %</strong>
            </span>
          </p>
          <div aria-hidden className="relative h-2 rounded-full bg-elevated">
            <span
              className="absolute inset-y-0 left-0 rounded-full bg-muted-foreground/70"
              style={{ width: `${share(b.predicted) * 100}%` }}
            />
            <span
              className="absolute -top-1 h-4 w-[3px] -translate-x-1/2 rounded-full bg-foreground"
              style={{ left: `${share(b.observed) * 100}%` }}
            />
          </div>
        </li>
      ))}
      {cal.omitted > 0 ? (
        <li>
          <Note>
            {t("transparency.forecast.omitted", { count: intText(cal.omitted), min: data.min_bin })}
          </Note>
        </li>
      ) : null}
    </ul>
  );
}

export function EstimateBlock({ data }: { data: Transparency }) {
  const cal = data.picks_calibration;
  if (cal === undefined || cal === null) return null; // an older API
  return (
    <Block
      id="estimate"
      title={t("transparency.estimate.title")}
      subtitle={t("transparency.estimate.subtitle")}
      icon={<Gauge className="h-4 w-4" />}
    >
      {cal.bins.length === 0 ? (
        <Note testId="transparency-estimate-small">
          {cal.n < data.min_sample
            ? t("transparency.estimate.small", { min: data.min_sample, count: cal.n })
            : t("transparency.estimate.noRange", { min: data.min_bin })}
        </Note>
      ) : (
        <>
          <CalibrationBars cal={cal} data={data} />
          <Note>{t("transparency.estimate.legend")}</Note>
        </>
      )}
    </Block>
  );
}

// ---- «Por mercado» ----------------------------------------------------------------------------------------------------

function unitsTone(m: TransparencyMarketTally): string {
  const n = toNumber(m.units);
  return n === null || n === 0 ? "" : n > 0 ? "text-positive" : "text-negative";
}

export function MarketsTable({
  data,
  name,
}: {
  data: Transparency;
  name: (key: string) => string;
}) {
  return (
    <div className="@container -mx-1 overflow-x-auto px-1">
      <table className="w-full min-w-[17rem] text-sm" data-testid="transparency-markets-table">
        <thead>
          <tr className="text-left text-label text-subtle-foreground">
            <th scope="col" className="py-1.5 font-medium">
              {t("transparency.marketsTable.market")}
            </th>
            <th scope="col" className="py-1.5 pl-3 text-right font-medium">
              {t("transparency.marketsTable.picks")}
            </th>
            <th scope="col" className="py-1.5 pl-3 text-right font-medium">
              {t("transparency.marketsTable.wonLost")}
            </th>
            <th scope="col" className="py-1.5 pl-3 text-right font-medium">
              {t("transparency.marketsTable.units")}
            </th>
            <th
              scope="col"
              className="hidden py-1.5 pl-3 text-right font-medium @[26rem]:table-cell"
            >
              {t("transparency.marketsTable.roi")}
            </th>
          </tr>
        </thead>
        <tbody className="numeric">
          {data.markets.map((m) => (
            <tr
              key={m.market}
              className="border-t border-border"
              data-testid={`transparency-market-${m.market}`}
            >
              <th scope="row" className="py-2 pr-2 text-left font-sans font-semibold">
                {name(m.market)}
                {m.pending > 0 ? (
                  <span className="block text-caption font-normal text-muted-foreground">
                    {t("transparency.marketsTable.pending", { count: m.pending })}
                  </span>
                ) : null}
              </th>
              <td className="py-2 pl-3 text-right">{intText(m.published)}</td>
              <td className="whitespace-nowrap py-2 pl-3 text-right">
                {intText(m.won + m.half_won)} – {intText(m.lost + m.half_lost)}
              </td>
              <td
                className={cn("whitespace-nowrap py-2 pl-3 text-right font-semibold", unitsTone(m))}
              >
                {fmtUnits(m.units)}
              </td>
              <td className="hidden py-2 pl-3 text-right @[26rem]:table-cell">{roiText(m)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
