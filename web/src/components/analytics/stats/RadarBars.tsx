/**
 * Six fixed axes in percentile (plan EA, catalogue n.º 7; V2·3): a radar or bars, the SAME numbers either way - the reader picks the
 * shape. The axes never move (Ataque, Pegada, Volumen, Presencia, Defensa, Disciplina) and are oriented so that more is better; the
 * league's median (p50) is the grey ring. Recharts 3 with its accessibility layer.
 */
import { useState } from "react";
import {
  Bar,
  BarChart,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ReferenceLine,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";
import { t } from "@/lib/i18n";
import { isMissing } from "@/lib/api/v1/types_intelligence";
import type { RadarAxis, RadarKey } from "@/lib/api/v1/types_stats";
import { placeInWords } from "./howToRead";
import { ChipChoice } from "./ChartCard";

export interface RadarSide {
  name: string;
  axes: RadarAxis[];
  color: string;
}

const ORDER: readonly RadarKey[] = [
  "ataque",
  "pegada",
  "volumen",
  "presencia",
  "defensa",
  "disciplina",
];

export function RadarBars({ sides, testId }: { sides: RadarSide[]; testId?: string }) {
  const [view, setView] = useState<"radar" | "bars">("bars");
  const rows = ORDER.map((key) => {
    const row: Record<string, string | number | null> = {
      axis: t(`stats.axis.${key}`),
      league: 50,
    };
    sides.forEach((s, i) => {
      const a = s.axes.find((x) => x.key === key);
      row[`s${i}`] = a && !isMissing(a.percentile) ? a.percentile : null;
    });
    return row;
  });
  return (
    <div className="space-y-2" data-testid={testId}>
      <ChipChoice
        value={view}
        onChange={setView}
        label={t("stats.radarTitle")}
        options={[
          { value: "radar", label: t("stats.radarView") },
          { value: "bars", label: t("stats.barsView") },
        ]}
      />
      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          {view === "radar" ? (
            <RadarChart data={rows} outerRadius="72%" accessibilityLayer>
              <PolarGrid stroke="var(--color-border)" />
              <PolarAngleAxis
                dataKey="axis"
                tick={{ fill: "var(--color-muted-foreground)", fontSize: 12 }}
              />
              <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
              <Radar
                dataKey="league"
                stroke="var(--color-subtle-foreground)"
                strokeDasharray="4 4"
                fill="none"
                isAnimationActive={false}
              />
              {sides.map((s, i) => (
                <Radar
                  key={s.name}
                  name={s.name}
                  dataKey={`s${i}`}
                  stroke={s.color}
                  fill={s.color}
                  fillOpacity={i === 0 ? 0.22 : 0.12}
                  isAnimationActive={false}
                  strokeWidth={2}
                />
              ))}
            </RadarChart>
          ) : (
            <BarChart
              data={rows}
              layout="vertical"
              margin={{ left: 8, right: 12 }}
              accessibilityLayer
            >
              <XAxis
                type="number"
                domain={[0, 100]}
                tick={{ fill: "var(--color-subtle-foreground)", fontSize: 12 }}
              />
              <YAxis
                type="category"
                dataKey="axis"
                width={78}
                tick={{ fill: "var(--color-muted-foreground)", fontSize: 12 }}
              />
              <ReferenceLine x={50} stroke="var(--color-subtle-foreground)" strokeDasharray="4 4" />
              {sides.map((s, i) => (
                <Bar
                  key={s.name}
                  name={s.name}
                  dataKey={`s${i}`}
                  fill={s.color}
                  radius={[0, 6, 6, 0]}
                  barSize={10}
                  isAnimationActive={false}
                />
              ))}
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
      <ul className="grid gap-y-1 text-small">
        {rows.map((r) => (
          <li key={String(r["axis"])} className="flex justify-between gap-2">
            <span className="text-muted-foreground">{r["axis"]}</span>
            <span className="numeric">
              {sides
                .map((_, i) => {
                  const v = r[`s${i}`];
                  return typeof v === "number" ? placeInWords(v) : "—";
                })
                .join(" · ")}
            </span>
          </li>
        ))}
      </ul>
      <p className="text-small text-subtle-foreground">{t("stats.radarSame")}</p>
    </div>
  );
}
