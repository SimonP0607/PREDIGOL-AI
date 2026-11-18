/**
 * The advanced statistics of a team (plan EA, EA-102, EA-106 and EA-107; maquetas V2·1, V2·5, V2·6 and V2·7): the «Estadísticas»
 * tab of the profile turned into its centre of analysis. Scope (last 5/10/20, season) and context (all, home, away) change the series
 * the server already computed (C-13); nothing is recomputed here. Shown while FBI_STATS_V2 is on; otherwise the tab stays as it was.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowLeftRight } from "lucide-react";
import { live } from "@/lib/api/v1/queries";
import { LiveApiError } from "@/lib/api/v1/client";
import { isMissing, present } from "@/lib/api/v1/types_intelligence";
import type { StatsContext, StatsEntity, StatsScope, TeamBody } from "@/lib/api/v1/types_stats";
import { t } from "@/lib/i18n";
import { formatRelative } from "@/lib/time";
import { Card, EmptyState, ErrorState, SkeletonCards } from "@/product/shared/States";
import { ChartCard, ChipChoice } from "@/components/analytics/stats/ChartCard";
import { PercentileBars } from "@/components/analytics/stats/PercentileBars";
import { PulseChart } from "@/components/analytics/stats/PulseChart";
import { MirrorBins } from "@/components/analytics/stats/MirrorBins";
import { SurvivalCurve } from "@/components/analytics/stats/SurvivalCurve";
import { TrendMatrix, WilsonRow } from "@/components/analytics/stats/Trends";
import { RadarBars } from "@/components/analytics/stats/RadarBars";
import { Halves, StateBar, XgLine } from "@/components/analytics/stats/SmallCharts";
import { missingText, sampleText } from "@/components/analytics/stats/format";
import { MATRIX_KEYS } from "./shared";

const KEY_FIGURES = ["xg_for", "xg_against", "shots_for", "corners_for", "cards"];
const STREAK_KEYS = ["btts", "over_2_5", "scores_first", "clean_sheet", "win"];

function Missingly({ value }: { value: unknown }) {
  return isMissing(value) ? (
    <p className="text-caption text-subtle-foreground">{missingText(value)}</p>
  ) : null;
}

export function StatsFooter({ entity }: { entity: StatsEntity }) {
  return (
    <p className="text-caption text-subtle-foreground" data-testid="stats-footer">
      {t("stats.source", { version: entity.calc_version })} ·{" "}
      {t("stats.updated", { when: formatRelative(entity.computed_at) })}
    </p>
  );
}

function Controls({
  entity,
  scope,
  context,
  onScope,
  onContext,
  season,
  onSeason,
}: {
  entity: StatsEntity;
  scope: StatsScope;
  context: StatsContext;
  onScope: (s: StatsScope) => void;
  onContext: (c: StatsContext) => void;
  season: number | undefined;
  onSeason: (s: number | undefined) => void;
}) {
  return (
    <div
      className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center"
      data-testid="stats-controls"
    >
      <ChipChoice
        value={scope}
        onChange={onScope}
        label={t("stats.scopeLabel")}
        testId="stats-scope"
        options={(["u5", "u10", "u20", "season"] as const)
          .filter((s) => s === "season" || entity.available_scopes.includes(s) || s === scope)
          .map((s) => ({ value: s, label: t(`stats.scope.${s}`) }))}
      />
      <ChipChoice
        value={context}
        onChange={onContext}
        label={t("stats.contextLabel")}
        testId="stats-context"
        options={(["all", "home", "away"] as const).map((c) => ({
          value: c,
          label: t(`stats.context.${c}`),
        }))}
      />
      {entity.available_competitions.length > 1 ? (
        <label className="flex min-h-11 items-center gap-2 text-caption text-muted-foreground">
          <span>{t("stats.competitionLabel")}</span>
          <select
            className="min-h-11 rounded-lg border border-border bg-elevated px-2 text-foreground"
            value={season ?? entity.competition.competition_season_id}
            onChange={(e) => onSeason(Number(e.target.value))}
          >
            {entity.available_competitions.map((c) => (
              <option key={c.competition_season_id} value={c.competition_season_id}>
                {c.competition.name} {c.season}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      <span className="text-caption text-subtle-foreground sm:ml-auto">
        {sampleText(entity.matches)}
      </span>
    </div>
  );
}

export function TeamSections({ entity, body }: { entity: StatsEntity; body: TeamBody }) {
  const [allFigures, setAllFigures] = useState(false);
  const figures = allFigures
    ? body.figures
    : body.figures.filter((f) => KEY_FIGURES.includes(f.key));
  const teams = body.figures.find((f) => !isMissing(f.distribution))?.distribution;
  const pulseFor = present(body.pulse_for);
  const pulseAgainst = present(body.pulse_against);
  const intervals = present(body.intervals);
  const survival = present(body.survival);
  const states = present(body.states);
  const halves = present(body.halves);
  const matrix = present(body.matrix);
  const streaks = body.trends.items.filter((r) => STREAK_KEYS.includes(r.key));
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <ChartCard
        title={t("stats.performance")}
        subtitle={t("stats.performanceSub", {
          unit: t("stats.unit.por_partido"),
          teams: teams && !isMissing(teams) ? teams.entities : "—",
        })}
        footer={t("stats.leagueMark")}
        testId="stats-performance"
        actions={
          <button
            type="button"
            className="min-h-11 rounded-lg px-2 text-caption font-semibold text-primary hover:underline"
            onClick={() => setAllFigures((v) => !v)}
            aria-expanded={allFigures}
          >
            {allFigures ? "−" : "+"} {body.figures.length}
          </button>
        }
      >
        <PercentileBars figures={figures} />
      </ChartCard>
      <ChartCard
        title={t("stats.states")}
        subtitle={states ? t("stats.statesSub", { n: states.matches_with_data }) : undefined}
        testId="stats-states"
      >
        {states ? <StateBar states={states} /> : <Missingly value={body.states} />}
      </ChartCard>
      <ChartCard
        title={t("stats.pulseTitle")}
        subtitle={t("stats.pulseSub")}
        method={t("stats.pulseMethod")}
        footer={t("stats.pulseNote")}
        testId="stats-pulse"
      >
        {pulseFor ? (
          <PulseChart
            label={t("stats.pulseTitle")}
            series={[
              { name: t("stats.pulseFor"), pulse: pulseFor, color: "var(--color-primary)" },
              ...(pulseAgainst
                ? [
                    {
                      name: t("stats.pulseAgainst"),
                      pulse: pulseAgainst,
                      color: "var(--color-negative)",
                      band: false,
                    },
                  ]
                : []),
            ]}
          />
        ) : (
          <Missingly value={body.pulse_for} />
        )}
      </ChartCard>
      <ChartCard
        title={t("stats.intervalsTitle")}
        subtitle={t("stats.intervalsSub")}
        testId="stats-intervals"
      >
        {intervals ? <MirrorBins intervals={intervals} /> : <Missingly value={body.intervals} />}
      </ChartCard>
      <ChartCard
        title={t("stats.survivalTitle")}
        subtitle={t("stats.survivalSub")}
        testId="stats-survival"
      >
        {survival ? (
          <>
            <SurvivalCurve
              series={[
                { name: body.team.name, points: survival.points, color: "var(--color-primary)" },
                {
                  name: t("stats.survivalLeague"),
                  points: survival.league_points,
                  color: "var(--color-subtle-foreground)",
                  dashed: true,
                },
              ]}
            />
            <p className="text-caption text-muted-foreground">
              {isMissing(survival.median_first_goal)
                ? t("stats.survivalNone")
                : t("stats.survivalMedian", { label: survival.median_first_goal })}
              {!isMissing(survival.level_at_half)
                ? ` · ${t("stats.levelAtHalf", { pct: `${Math.round(survival.level_at_half * 100)} %` })}`
                : null}
            </p>
          </>
        ) : (
          <Missingly value={body.survival} />
        )}
      </ChartCard>
      <ChartCard title={t("stats.xgTitle")} subtitle={t("stats.xgSub")} testId="stats-xg">
        <XgLine series={body.series} />
      </ChartCard>
      <ChartCard title={t("stats.halves")} testId="stats-halves">
        {halves ? <Halves halves={halves} /> : <Missingly value={body.halves} />}
      </ChartCard>
      <ChartCard
        title={t("stats.radarTitle")}
        subtitle={t("stats.radarSub")}
        method={t("stats.radarFormula")}
        testId="stats-radar"
      >
        <RadarBars
          sides={[{ name: body.team.name, axes: body.radar, color: "var(--color-primary)" }]}
        />
      </ChartCard>
      <ChartCard
        title={t("stats.trendsTitle")}
        subtitle={t("stats.trendsSub")}
        className="lg:col-span-2"
        testId="stats-trends"
      >
        {matrix ? (
          <>
            <h3 className="text-caption font-semibold text-muted-foreground">
              {t("stats.matrixTitle")}
            </h3>
            <TrendMatrix columns={matrix} keys={MATRIX_KEYS} />
          </>
        ) : null}
        <h3 className="pt-1 text-caption font-semibold text-muted-foreground">
          {t("stats.streaksTitle")}
        </h3>
        <p className="text-caption text-subtle-foreground">{t("stats.streaksSub")}</p>
        <div className="space-y-2">
          {streaks.map((r) => (
            <WilsonRow key={r.key} label={t(`stats.trend.${r.key}`)} row={r} />
          ))}
        </div>
      </ChartCard>
      <div className="lg:col-span-2">
        <StatsFooter entity={entity} />
      </div>
    </div>
  );
}

export function TeamStatsHub({ teamId }: { teamId: string }) {
  const [scope, setScope] = useState<StatsScope>("u10");
  const [context, setContext] = useState<StatsContext>("all");
  const [season, setSeason] = useState<number | undefined>(undefined);
  const q = useQuery(live.teamStats(teamId, { scope, context, ...(season ? { season } : {}) }));
  const fallback = useQuery({
    ...live.teamStats(teamId, { scope: "season", context, ...(season ? { season } : {}) }),
    enabled:
      q.isError && q.error instanceof LiveApiError && q.error.status === 404 && scope !== "season",
  });
  const data = q.data ?? fallback.data;
  if (q.isPending) return <SkeletonCards count={3} />;
  if (!data) {
    if (
      q.error instanceof LiveApiError &&
      q.error.status === 404 &&
      (scope === "season" || fallback.isError)
    )
      return (
        <Card className="p-4">
          <EmptyState title={t("stats.none")} />
        </Card>
      );
    if (fallback.isPending && scope !== "season") return <SkeletonCards count={2} />;
    return (
      <Card>
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      </Card>
    );
  }
  const entity = data.data.entities[0];
  const body = entity ? present(entity.team) : null;
  if (!entity || !body)
    return (
      <Card className="p-4">
        <EmptyState title={t("stats.none")} />
      </Card>
    );
  return (
    <div className="flex flex-col gap-4" data-testid="team-stats-hub">
      {data.data.freshness.stale ? (
        <p className="rounded-xl bg-warning-soft p-3 text-caption text-warning">
          {t("stats.stale")}
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <Controls
          entity={entity}
          scope={entity.scope}
          context={context}
          onScope={setScope}
          onContext={setContext}
          season={season}
          onSeason={setSeason}
        />
        <Link
          to="/compare/teams"
          search={{ a: Number(teamId) }}
          className="inline-flex min-h-11 items-center gap-1.5 rounded-lg border border-border bg-elevated px-3 text-caption font-semibold text-foreground-soft hover:border-primary"
          data-testid="stats-compare"
        >
          <ArrowLeftRight aria-hidden className="h-4 w-4" /> {t("stats.compareWith")}
        </Link>
      </div>
      <TeamSections entity={entity} body={body} />
    </div>
  );
}
