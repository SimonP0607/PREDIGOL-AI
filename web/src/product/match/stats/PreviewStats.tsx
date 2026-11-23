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
import { EvidenceChart } from "@/components/analytics/EvidenceChart";
import { READER_REVIEW } from "@/components/analytics/readerReview";
import { ChartCard, ChipChoice } from "@/components/analytics/stats/ChartCard";
import {
  compareRadarReading,
  figurePlace,
  intervalsReading,
  pulseReading,
  survivalReading,
  together,
} from "@/components/analytics/stats/howToRead";
import { t as r } from "@/components/analytics/stats/readText";
import { PulseChart } from "@/components/analytics/stats/PulseChart";
import { MirrorBins } from "@/components/analytics/stats/MirrorBins";
import { SurvivalCurve } from "@/components/analytics/stats/SurvivalCurve";
import { RadarBars } from "@/components/analytics/stats/RadarBars";
import { figName, figValue } from "@/components/analytics/stats/format";
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
      return <p className="text-small text-subtle-foreground">{t("stats.previewNone")}</p>;
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
  const common = { evidence: "E1", review: READER_REVIEW } as const;
  const pulseReadings = [home, away]
    .map((b) => ({ b, p: present(b.pulse_for) }))
    .filter((x) => x.p !== null)
    .map((x) => pulseReading(x.b.team.name, x.p!, present(x.b.pulse_against)));
  return (
    <section
      className="space-y-4"
      data-testid="match-stats-preview"
      aria-label={t("stats.previewTitle")}
    >
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-subheading">{t("stats.previewTitle")}</h2>
          <p className="text-small text-subtle-foreground">
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
          <EvidenceChart
            {...common}
            title={r("readchart.pulse.title")}
            axes={r("readchart.pulse.axis")}
            reading={together(pulseReadings)}
            terms={["goalPulse"]}
            footer={r("readchart.pulse.note")}
          >
            <PulseChart label={r("readchart.pulse.title")} series={pulses} />
          </EvidenceChart>
        ) : null}
        {intervals ? (
          <EvidenceChart
            {...common}
            title={`${r("readchart.intervals.title")} · ${chosen.team.name}`}
            axes={r("readchart.intervals.axis")}
            reading={intervalsReading(chosen.team.name, intervals)}
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
          </EvidenceChart>
        ) : null}
        <ChartCard title={r("readchart.compare.figuresTitle")}>
          <ul className="space-y-1.5 text-small">
            {CROSS_FIGURES.map((k) => {
              const fh = home.figures.find((f) => f.key === k);
              const fa = away.figures.find((f) => f.key === k);
              if (!fh || !fa) return null;
              return (
                <li key={k} className="grid grid-cols-[minmax(0,1fr)_auto_auto] gap-3">
                  <span className="truncate text-foreground-soft">{figName(k)}</span>
                  <span className="numeric" style={{ color: teamColor(0) }}>
                    {figValue(fh)}{" "}
                    <span className="text-subtle-foreground">{figurePlace(fh) ?? "—"}</span>
                  </span>
                  <span className="numeric" style={{ color: teamColor(1) }}>
                    {figValue(fa)}{" "}
                    <span className="text-subtle-foreground">{figurePlace(fa) ?? "—"}</span>
                  </span>
                </li>
              );
            })}
          </ul>
        </ChartCard>
        <ChartCard title={t("stats.previewTrends")} footer={t("stats.previewTrendsNote")}>
          <ul className="space-y-1.5 text-small">
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
          <EvidenceChart
            {...common}
            title={r("readchart.survival.title")}
            axes={r("readchart.survival.axis")}
            reading={together([
              survivalReading(home.team.name, sh),
              survivalReading(away.team.name, sa),
            ])}
          >
            <SurvivalCurve
              series={[
                { name: home.team.name, points: sh.points, color: teamColor(0) },
                { name: away.team.name, points: sa.points, color: teamColor(1) },
              ]}
            />
          </EvidenceChart>
        ) : null}
        <EvidenceChart
          {...common}
          title={r("readchart.compareRadar.title")}
          axes={r("readchart.radar.axis")}
          reading={compareRadarReading(
            { name: home.team.name, axes: home.radar },
            { name: away.team.name, axes: away.radar },
            Math.min(home.record.matches, away.record.matches),
          )}
          terms={["percentile"]}
          footer={r("readchart.radar.how")}
        >
          <RadarBars
            sides={[
              { name: home.team.name, axes: home.radar, color: teamColor(0) },
              { name: away.team.name, axes: away.radar, color: teamColor(1) },
            ]}
          />
        </EvidenceChart>
      </div>
      {entities[0] ? <StatsFooter entity={entities[0]} /> : null}
    </section>
  );
}
