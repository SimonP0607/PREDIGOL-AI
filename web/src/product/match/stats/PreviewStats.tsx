/**
 * The match in statistics before kick-off (plan EA, EA-203; maqueta V2·11): the two sides each in its own context - the home side's
 * home matches, the away side's away matches - against its own league: the goal pulse of both, goals by interval in mirror, the
 * percentiles side by side, the game states and the trends of the match with their sample. Inside the existing «Estadísticas» tab:
 * no tab is added. Shown while FBI_STATS_V2 is on; otherwise the tab is what it was.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { live } from "@/lib/api/v1/queries";
import { LiveApiError } from "@/lib/api/v1/client";
import { present } from "@/lib/api/v1/types_intelligence";
import type { StatsScope, TeamBody } from "@/lib/api/v1/types_stats";
import { t } from "@/lib/i18n";
import { ChartCard, ChipChoice } from "@/components/analytics/stats/ChartCard";
import { PulseChart } from "@/components/analytics/stats/PulseChart";
import { MirrorBins } from "@/components/analytics/stats/MirrorBins";
import { SurvivalCurve } from "@/components/analytics/stats/SurvivalCurve";
import { RadarBars } from "@/components/analytics/stats/RadarBars";
import { figName, figValue, percentileText } from "@/components/analytics/stats/format";
import { StatsFooter } from "@/product/teams/stats/TeamStatsHub";
import { teamColor } from "@/product/teams/stats/shared";

const CROSS_TRENDS = ["btts", "over_2_5", "scores_first", "corners_over_9_5", "cards_over_4_5"];
const CROSS_FIGURES = [
  "goals_for",
  "goals_against",
  "xg_for",
  "xg_against",
  "shots_for",
  "corners_for",
  "cards",
];

export function PreviewStats({ fixtureId }: { fixtureId: string }) {
  const [scope, setScope] = useState<StatsScope>("u10");
  const [side, setSide] = useState<0 | 1>(0);
  const q = useQuery(live.matchStatsPreview(fixtureId, scope));
  if (q.isPending) return null;
  if (q.isError) {
    if (q.error instanceof LiveApiError && q.error.status === 404)
      return <p className="text-caption text-subtle-foreground">{t("stats.previewNone")}</p>;
    return null;
  }
  const entities = q.data.data.entities;
  const bodies = entities.map((e) => present(e.team));
  if (bodies.length < 2 || bodies.some((b) => !b)) return null;
  const [home, away] = bodies as [TeamBody, TeamBody];
  const pulses = [home, away]
    .map((b, i) => ({ b, i, p: present(b.pulse_for) }))
    .filter((x) => x.p !== null)
    .map((x) => ({ name: x.b.team.name, pulse: x.p!, color: teamColor(x.i), band: x.i === 0 }));
  const chosen = side === 0 ? home : away;
  const intervals = present(chosen.intervals);
  const sh = present(home.survival);
  const sa = present(away.survival);
  return (
    <section
      className="space-y-4"
      data-testid="match-stats-preview"
      aria-label={t("stats.previewTitle")}
    >
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-subheading">{t("stats.previewTitle")}</h2>
          <p className="text-caption text-subtle-foreground">
            {t("stats.previewSub", { home: home.team.name, away: away.team.name })}
          </p>
        </div>
        <ChipChoice
          value={scope}
          onChange={setScope}
          label={t("stats.scopeLabel")}
          options={(["u5", "u10", "u20", "season"] as const).map((s) => ({
            value: s,
            label: t(`stats.scope.${s}`),
          }))}
        />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        {pulses.length ? (
          <ChartCard
            title={t("stats.pulseTitle")}
            footer={t("stats.pulseNote")}
            method={t("stats.pulseMethod")}
          >
            <PulseChart label={t("stats.pulseTitle")} series={pulses} />
          </ChartCard>
        ) : null}
        {intervals ? (
          <ChartCard
            title={`${t("stats.intervalsTitle")} · ${chosen.team.name}`}
            subtitle={t("stats.intervalsSub")}
            actions={
              <ChipChoice
                value={String(side) as "0" | "1"}
                onChange={(v) => setSide(v === "0" ? 0 : 1)}
                label={t("stats.intervalsTitle")}
                options={[
                  { value: "0", label: home.team.name },
                  { value: "1", label: away.team.name },
                ]}
              />
            }
          >
            <MirrorBins intervals={intervals} />
          </ChartCard>
        ) : null}
        <ChartCard title={t("stats.performance")} subtitle={t("stats.compareEach")}>
          <ul className="space-y-1.5 text-caption">
            {CROSS_FIGURES.map((k) => {
              const fh = home.figures.find((f) => f.key === k);
              const fa = away.figures.find((f) => f.key === k);
              if (!fh || !fa) return null;
              return (
                <li key={k} className="grid grid-cols-[minmax(0,1fr)_auto_auto] gap-3">
                  <span className="truncate text-foreground-soft">{figName(k)}</span>
                  <span className="numeric" style={{ color: teamColor(0) }}>
                    {figValue(fh)}{" "}
                    <span className="text-subtle-foreground">{percentileText(fh.percentile)}</span>
                  </span>
                  <span className="numeric" style={{ color: teamColor(1) }}>
                    {figValue(fa)}{" "}
                    <span className="text-subtle-foreground">{percentileText(fa.percentile)}</span>
                  </span>
                </li>
              );
            })}
          </ul>
        </ChartCard>
        <ChartCard title={t("stats.previewTrends")} footer={t("stats.previewTrendsNote")}>
          <ul className="space-y-1.5 text-caption">
            {CROSS_TRENDS.map((k) => {
              const rh = home.trends.items.find((r) => r.key === k);
              const ra = away.trends.items.find((r) => r.key === k);
              if (!rh && !ra) return null;
              return (
                <li key={k} className="flex justify-between gap-3">
                  <span className="text-foreground-soft">{t(`stats.trend.${k}`)}</span>
                  <span className="numeric">
                    <span style={{ color: teamColor(0) }}>{rh ? `${rh.hits}/${rh.n}` : "—"}</span> ·{" "}
                    <span style={{ color: teamColor(1) }}>{ra ? `${ra.hits}/${ra.n}` : "—"}</span>
                  </span>
                </li>
              );
            })}
          </ul>
        </ChartCard>
        {sh && sa ? (
          <ChartCard title={t("stats.survivalTitle")} subtitle={t("stats.survivalSub")}>
            <SurvivalCurve
              series={[
                { name: home.team.name, points: sh.points, color: teamColor(0) },
                { name: away.team.name, points: sa.points, color: teamColor(1) },
              ]}
            />
          </ChartCard>
        ) : null}
        <ChartCard
          title={t("stats.radarTitle")}
          subtitle={t("stats.radarSub")}
          method={t("stats.radarFormula")}
        >
          <RadarBars
            sides={[
              { name: home.team.name, axes: home.radar, color: teamColor(0) },
              { name: away.team.name, axes: away.radar, color: teamColor(1) },
            ]}
          />
        </ChartCard>
      </div>
      {entities[0] ? <StatsFooter entity={entities[0]} /> : null}
    </section>
  );
}
