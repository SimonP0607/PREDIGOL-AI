/**
 * The goal pulse (plan EA, catalogue n.º 1; V2·5, V2·1, V2·11): ``pulso-v1`` drawn in SVG - the index per 5' bin against the league's
 * 100 (dashed), its bootstrap band (10th-90th percentile) shaded, the added minutes 45+ and 90+ as narrow bins of their own. One or two
 * series. A table with the same numbers sits under it for a screen reader.
 */
import { t } from "@/lib/i18n";
import { isMissing } from "@/lib/api/v1/types_intelligence";
import type { Pulse } from "@/lib/api/v1/types_stats";
import { num } from "./format";

export interface PulseSeries {
  name: string;
  pulse: Pulse;
  color: string;
  band?: boolean;
}

const W = 340;
const H = 120;
const PAD = { left: 30, right: 6, top: 8, bottom: 18 };

/** x of each of the 20 bins: the 18 regular ones share the width, 45+ and 90+ take half a bin each. */
function xs(): number[] {
  const units = [...Array(9).fill(1), 0.5, ...Array(9).fill(1), 0.5] as number[];
  const total = units.reduce((a, b) => a + b, 0);
  const inner = W - PAD.left - PAD.right;
  const out: number[] = [];
  let at = PAD.left;
  for (const u of units) {
    const w = (u / total) * inner;
    out.push(at + w / 2);
    at += w;
  }
  return out;
}

export function PulseChart({
  series,
  label,
  testId,
}: {
  series: PulseSeries[];
  label: string;
  testId?: string;
}) {
  const x = xs();
  const values = series.flatMap((s) =>
    s.pulse.bins.flatMap((b) => [b.index, b.high].filter((v): v is number => !isMissing(v))),
  );
  const top = Math.max(150, Math.min(300, Math.ceil((Math.max(...values, 100) * 1.08) / 50) * 50));
  const y = (v: number) => PAD.top + (1 - Math.min(v, top) / top) * (H - PAD.top - PAD.bottom);
  const path = (pts: Array<[number, number] | null>) =>
    pts
      .reduce<string[]>((acc, p, i) => {
        if (!p) return acc;
        const prev = pts[i - 1];
        acc.push(`${prev ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`);
        return acc;
      }, [])
      .join(" ");
  return (
    <figure className="m-0" data-testid={testId}>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={label}>
        {[0, 100, top].map((v) => (
          <g key={v}>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={y(v)}
              y2={y(v)}
              stroke="var(--color-border)"
              strokeWidth={v === 100 ? 0 : 1}
            />
            <text
              x={PAD.left - 4}
              y={y(v) + 3}
              textAnchor="end"
              fontSize="12"
              fill="var(--color-subtle-foreground)"
            >
              {v}
            </text>
          </g>
        ))}
        <line
          x1={PAD.left}
          x2={W - PAD.right}
          y1={y(100)}
          y2={y(100)}
          stroke="var(--color-subtle-foreground)"
          strokeWidth={1.5}
          strokeDasharray="5 4"
        />
        {series.map((s) => {
          const bins = s.pulse.bins;
          const band =
            s.band !== false
              ? bins
                  .map((b, i) =>
                    !isMissing(b.high) ? `${x[i]!.toFixed(1)},${y(b.high).toFixed(1)}` : null,
                  )
                  .filter(Boolean)
                  .concat(
                    bins
                      .map((b, i) =>
                        !isMissing(b.low) ? `${x[i]!.toFixed(1)},${y(b.low).toFixed(1)}` : null,
                      )
                      .filter(Boolean)
                      .reverse(),
                  )
              : [];
          return (
            <g key={s.name}>
              {band.length > 2 ? (
                <polygon points={band.join(" ")} fill={s.color} opacity={0.14} />
              ) : null}
              <path
                d={path(bins.map((b, i) => (isMissing(b.index) ? null : [x[i]!, y(b.index)])))}
                fill="none"
                stroke={s.color}
                strokeWidth={2.5}
                strokeLinejoin="round"
              />
            </g>
          );
        })}
        {[0, 4, 9, 13, 19].map((i) => (
          <text
            key={i}
            x={x[i]}
            y={H - 4}
            textAnchor="middle"
            fontSize="12"
            fill="var(--color-subtle-foreground)"
          >
            {series[0]?.pulse.bins[i]?.label.replace("-", "–") ?? ""}
          </text>
        ))}
      </svg>
      <figcaption className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-small text-muted-foreground">
        {series.map((s) => (
          <span key={s.name} className="inline-flex items-center gap-1">
            <span aria-hidden style={{ color: s.color }}>
              ●
            </span>
            {s.name}
          </span>
        ))}
        <span className="inline-flex items-center gap-1">
          <span aria-hidden>┅</span> {t("stats.pulseLeague")}
        </span>
      </figcaption>
      <table className="sr-only">
        <caption>{label}</caption>
        <thead>
          <tr>
            <th scope="col">min</th>
            {series.map((s) => (
              <th key={s.name} scope="col">
                {s.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {series[0]?.pulse.bins.map((b, i) => (
            <tr key={b.label}>
              <th scope="row">{b.label}</th>
              {series.map((s) => {
                const v = s.pulse.bins[i];
                return (
                  <td key={s.name}>
                    {v && !isMissing(v.index)
                      ? `${num(v.index, 0)} (${num(v.low, 0)}–${num(v.high, 0)})`
                      : "—"}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
