/**
 * The advanced statistics of a player by position (plan EA, EA-103; maqueta V2·2): the template of his position - rates per 90 on
 * the distribution of the league's players of that position, with his percentile - his last five appearances metric by metric and his
 * minutes of the last ten. History and rates, never a probability: the player engine stays out of a reader's page (UX-156).
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowLeftRight } from "lucide-react";
import { live } from "@/lib/api/v1/queries";
import { LiveApiError } from "@/lib/api/v1/client";
import { isMissing, present } from "@/lib/api/v1/types_intelligence";
import { t } from "@/lib/i18n";
import { localFixed } from "@/lib/i18n/format";
import { Card, EmptyState, ErrorState, SkeletonCards } from "@/product/shared/States";
import { ChartCard, ChipChoice } from "@/components/analytics/stats/ChartCard";
import { DistributionRow } from "@/components/analytics/stats/PositionDistribution";
import { LastFive, MinutesBars } from "@/components/analytics/stats/SmallCharts";
import { figName } from "@/components/analytics/stats/format";
import { StatsFooter } from "./TeamStatsHub";

export function PlayerStatsHub({ playerId }: { playerId: string }) {
  const q = useQuery(live.playerStats(playerId));
  const [metric, setMetric] = useState<string | null>(null);
  if (q.isPending) return <SkeletonCards count={2} />;
  if (q.isError)
    return (
      <Card className="p-4">
        {q.error instanceof LiveApiError && q.error.status === 404 ? (
          <EmptyState title={t("stats.nonePlayer")} />
        ) : (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        )}
      </Card>
    );
  const entity = q.data.data.entities[0];
  const body = entity ? present(entity.player) : null;
  if (!entity || !body)
    return (
      <Card className="p-4">
        <EmptyState title={t("stats.nonePlayer")} />
      </Card>
    );
  const position = present(body.position);
  const stripKeys = body.last5[0]?.values.map((v) => v.key) ?? [];
  const chosen = metric && stripKeys.includes(metric) ? metric : (stripKeys[0] ?? null);
  return (
    <div className="grid gap-4 lg:grid-cols-2" data-testid="player-stats-hub">
      <ChartCard
        title={t("stats.distTitle", {
          position: position ? t(`stats.positionPlural.${position}`) : "—",
        })}
        subtitle={t("stats.distSub", { nineties: localFixed(body.nineties, 1) })}
        footer={t("stats.templateNote")}
        testId="player-distribution"
        actions={
          <Link
            to="/compare/players"
            search={{ a: Number(playerId) }}
            className="inline-flex min-h-11 items-center gap-1.5 rounded-lg border border-border bg-elevated px-3 text-caption font-semibold text-foreground-soft hover:border-primary"
          >
            <ArrowLeftRight aria-hidden className="h-4 w-4" /> {t("stats.compareWith")}
          </Link>
        }
      >
        <div className="space-y-3">
          {body.figures.map((f) => (
            <DistributionRow
              key={f.key}
              players={[{ name: body.player.name, figure: f, color: "var(--color-primary)" }]}
            />
          ))}
        </div>
      </ChartCard>
      <div className="flex flex-col gap-4">
        {chosen ? (
          <ChartCard title={t("stats.last5")} testId="player-last5">
            <ChipChoice
              value={chosen}
              onChange={setMetric}
              label={t("stats.last5")}
              options={stripKeys.map((k) => ({ value: k, label: figName(k) }))}
            />
            <LastFive strip={body.last5} metric={chosen} />
          </ChartCard>
        ) : null}
        <ChartCard
          title={t("stats.minutesTitle")}
          subtitle={t("stats.starts", { n: body.starts, of: body.appearances })}
          testId="player-minutes"
        >
          <MinutesBars items={body.recent_minutes} />
        </ChartCard>
        {isMissing(body.position) ? null : (
          <p className="text-caption text-subtle-foreground">{t("stats.playerNote")}</p>
        )}
        <StatsFooter entity={entity} />
      </div>
    </div>
  );
}
