/**
 * «¿Cuánto tarda en abrirse el partido?» (plan EA, catalogue n.º 3; V2·5): Kaplan-Meier of the first goal - the share of matches
 * still 0-0 after each minute - as steps, for one or two teams and the league (dashed).
 */
import { t } from "@/lib/i18n";
import type { SurvivalPoint } from "@/lib/api/v1/types_stats";
import { pct } from "./format";

const W = 340;
const H = 110;
const P = { left: 28, right: 6, top: 6, bottom: 16 };

export interface SurvivalSeries {
  name: string;
  points: SurvivalPoint[];
  color: string;
  dashed?: boolean;
}

/** The clock position of a step: 45+ sits just after 45, 90+ just after 90. */
function at(p: SurvivalPoint): number {
  return p.label.endsWith("+") ? p.minute + 2 : p.minute;
}

export function SurvivalCurve({ series, testId }: { series: SurvivalSeries[]; testId?: string }) {
  const x = (m: number) => P.left + (m / 92) * (W - P.left - P.right);
  const y = (s: number) => P.top + (1 - s) * (H - P.top - P.bottom);
  return (
    <figure className="m-0" data-testid={testId}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-auto w-full"
        role="img"
        aria-label={t("stats.survivalSub")}
      >
        {[0, 0.5, 1].map((v) => (
          <g key={v}>
            <line x1={P.left} x2={W - P.right} y1={y(v)} y2={y(v)} stroke="var(--color-border)" />
            <text
              x={P.left - 4}
              y={y(v) + 3}
              fontSize="9"
              textAnchor="end"
              fill="var(--color-subtle-foreground)"
            >
              {Math.round(v * 100)}%
            </text>
          </g>
        ))}
        {series.map((s) => {
          let d = "";
          s.points.forEach((p, i) => {
            const px = x(at(p));
            const py = y(p.survival);
            if (i === 0) d += `M${px.toFixed(1)},${py.toFixed(1)}`;
            else d += ` H${px.toFixed(1)} V${py.toFixed(1)}`;
          });
          return (
            <path
              key={s.name}
              d={d}
              fill="none"
              stroke={s.color}
              strokeWidth={s.dashed ? 1.5 : 2.5}
              strokeDasharray={s.dashed ? "5 4" : undefined}
            />
          );
        })}
        {[0, 45, 90].map((m) => (
          <text
            key={m}
            x={x(m)}
            y={H - 3}
            fontSize="9"
            textAnchor="middle"
            fill="var(--color-subtle-foreground)"
          >
            {m}'
          </text>
        ))}
      </svg>
      <table className="sr-only">
        <caption>{t("stats.survivalSub")}</caption>
        <tbody>
          {series[0]?.points.map((p, i) => (
            <tr key={p.label}>
              <th scope="row">{p.label}</th>
              {series.map((s) => (
                <td key={s.name}>{pct((s.points[i]?.survival ?? 0) * 100)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
