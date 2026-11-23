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
import { Card, EmptyState, ErrorState, SkeletonCards } from "@/product/shared/States";
import { EvidenceChart } from "@/components/analytics/EvidenceChart";
import { READER_REVIEW } from "@/components/analytics/readerReview";
import { ChipChoice } from "@/components/analytics/stats/ChartCard";
import {
  lastFiveReading,
  minutesReading,
  playerReading,
} from "@/components/analytics/stats/howToRead";
import { t as r } from "@/components/analytics/stats/readText";
import { DistributionRow } from "@/components/analytics/stats/PositionDistribution";
import { LastFive, MinutesBars } from "@/components/analytics/stats/SmallCharts";
import { figName } from "@/components/analytics/stats/format";
import { StatsFooter } from "./TeamStatsHub";
import { usePmReaderSwitches } from "@/lib/auth/AuthProvider";
import { PlayerExtras } from "./PlayerExtras";

export function PlayerStatsHub({ playerId }: { playerId: string }) {
  const q = useQuery(live.playerStats(playerId));
  const { playerExtras } = usePmReaderSwitches();
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
  const posName = position ? t(`stats.position.${position}`).toLowerCase() : "—";
  const name = body.player.name;
  const common = { evidence: "E1", review: READER_REVIEW } as const;
  return (
    <div className="grid gap-4 lg:grid-cols-2" data-testid="player-stats-hub">
      <EvidenceChart
        {...common}
        title={r("readchart.player.title")}
        axes={r("readchart.player.axis")}
        reading={playerReading(body, posName)}
        terms={["percentile"]}
        footer={t("stats.templateNote")}
        testId="player-distribution"
        actions={
          <Link
            to="/compare/players"
            search={{ a: Number(playerId) }}
            className="inline-flex min-h-11 items-center gap-1.5 rounded-lg border border-border bg-elevated px-3 text-small font-semibold text-foreground-soft hover:border-primary"
          >
            <ArrowLeftRight aria-hidden className="h-4 w-4" /> {t("stats.compareWith")}
          </Link>
        }
      >
        <div className="space-y-3">
          {body.figures.map((f) => (
            <DistributionRow
              key={f.key}
              players={[{ name, figure: f, color: "var(--color-primary)" }]}
            />
          ))}
        </div>
      </EvidenceChart>
      <div className="flex flex-col gap-4">
        {chosen ? (
          <EvidenceChart
            {...common}
            title={r("readchart.last5.title")}
            axes={r("readchart.last5.axis")}
            reading={lastFiveReading(name, body.last5, chosen)}
            testId="player-last5"
          >
            <ChipChoice
              value={chosen}
              onChange={setMetric}
              label={t("stats.last5")}
              options={stripKeys.map((k) => ({ value: k, label: figName(k) }))}
            />
            <LastFive strip={body.last5} metric={chosen} />
          </EvidenceChart>
        ) : null}
        {body.recent_minutes.length > 0 ? (
          <EvidenceChart
            {...common}
            title={r("readchart.minutes.title")}
            axes={r("readchart.minutes.axis")}
            reading={minutesReading(body)}
            testId="player-minutes"
          >
            <MinutesBars items={body.recent_minutes} />
          </EvidenceChart>
        ) : null}
        {isMissing(body.position) ? null : (
          <p className="text-small text-subtle-foreground">{t("stats.playerNote")}</p>
        )}
        <StatsFooter entity={entity} />
      </div>
      {/* plan PM, PM-08-06 (UX-180): the goalkeeper's and every player's new data, behind FBI_PLAYER_PROFILE_EXTRAS */}
      {playerExtras ? (
        <div className="lg:col-span-2">
          <PlayerExtras entity={entity} body={body} />
        </div>
      ) : null}
    </div>
  );
}
