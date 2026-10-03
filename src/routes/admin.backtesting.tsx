import { useState } from "react";
import { DATA_MODE } from "@/lib/api/mode";
import { DemoRegion } from "@/components/system/DataSources";
import { BacktestingLive } from "@/live/ResearchLive";
import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { MetricCard, Panel, WarningBanner } from "@/components/primitives/Panel";
import { TableShell, THead, TH, TRow, TD, TableSkeleton } from "@/components/primitives/DataTable";
import { Numeric } from "@/components/primitives/Indicators";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { MetricLabel } from "@/components/system/InfoTip";
import { SelectFilter, NumberFilter } from "@/components/system/Filters";
import {
  CalibrationChart,
  ChartContainer,
  MonthlyBars,
  ProbabilityBuckets,
} from "@/components/analytics/Charts";
import { backtestQuery } from "@/lib/api/resources";
import { defaultBacktestConfig } from "@/mock/research";
import { competitions, models } from "@/mock/data";
import { EMPTY, int, num } from "@/lib/format";
import type { BacktestConfig, MarketKey } from "@/types/domain";

export const Route = createFileRoute("/admin/backtesting")({
  head: () => ({
    meta: [
      { title: "Backtesting — Football Intelligence" },
      {
        name: "description",
        content: "Point-in-time replay of model versions against historical fixtures.",
      },
      { property: "og:title", content: "Backtesting — Football Intelligence" },
      {
        property: "og:description",
        content: "Reproducible, versioned replay scored against the market baseline.",
      },
    ],
  }),
  component: RouteComponent,
});

function RouteComponent() {
  if (DATA_MODE !== "mock") return <BacktestingLive />;
  return (
    <DemoRegion>
      <BacktestingPage />
    </DemoRegion>
  );
}

function BacktestingPage() {
  const [draft, setDraft] = useState<BacktestConfig>(defaultBacktestConfig);
  const [submitted, setSubmitted] = useState<BacktestConfig | null>(null);
  const result = useQuery(backtestQuery(submitted ?? draft, submitted !== null));
  const r = result.data;

  const set = <K extends keyof BacktestConfig>(key: K, value: BacktestConfig[K]) =>
    setDraft((d) => ({ ...d, [key]: value }));

  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumb={[{ label: "Intelligence" }, { label: "Backtesting" }]}
        title="Backtesting"
        description="Replay a model version over historical fixtures using only features available before each kickoff."
      />

      <div className="grid gap-4 xl:grid-cols-[20rem_minmax(0,1fr)]">
        <Panel title="Run configuration" subtitle="Same version, same cutoff, same result.">
          <div className="space-y-3">
            <SelectFilter
              label="Model"
              value={draft.modelId}
              onChange={(v) => set("modelId", v)}
              options={models.map((m) => ({ value: m.id, label: m.name }))}
            />
            <SelectFilter
              label="Version"
              value={draft.modelVersion}
              onChange={(v) => set("modelVersion", v)}
              options={[
                { value: draft.modelVersion, label: draft.modelVersion },
                { value: "v0.4.1", label: "v0.4.1" },
              ]}
            />
            <SelectFilter
              label="Competition"
              value={draft.competitionId}
              onChange={(v) => set("competitionId", v)}
              options={[
                { value: "all", label: "All competitions" },
                ...competitions.map((c) => ({ value: c.id, label: c.name })),
              ]}
            />
            <SelectFilter
              label="Season"
              value={draft.season}
              onChange={(v) => set("season", v)}
              options={[
                { value: "2025/26", label: "2025/26" },
                { value: "2024/25", label: "2024/25" },
              ]}
            />
            <SelectFilter
              label="Market"
              value={draft.market}
              onChange={(v) => set("market", v as MarketKey)}
              options={[
                { value: "1x2", label: "1X2" },
                { value: "ou_2_5", label: "Over / Under 2.5" },
                { value: "btts", label: "BTTS" },
                { value: "double_chance", label: "Double Chance" },
              ]}
            />
            <SelectFilter
              label="Odds source"
              value={draft.oddsSource}
              onChange={(v) => set("oddsSource", v)}
              options={[
                { value: "consensus", label: "Consensus" },
                { value: "best", label: "Best available" },
                { value: "none", label: "None (predictive only)" },
              ]}
            />
            <SelectFilter
              label="Stake strategy"
              value={draft.stakeStrategy}
              onChange={(v) => set("stakeStrategy", v)}
              options={[
                { value: "flat", label: "Flat" },
                { value: "kelly", label: "Fractional Kelly" },
              ]}
            />
            <NumberFilter
              label="Min edge"
              value={Number((draft.minimumEdge * 100).toFixed(1))}
              onChange={(v) => set("minimumEdge", v / 100)}
              min={0}
              max={10}
              step={0.5}
            />
            <button
              type="button"
              onClick={() => setSubmitted({ ...draft })}
              className="inline-flex w-full items-center justify-center gap-1.5 rounded-md border border-primary/40 bg-primary/12 px-3 py-2 text-xs font-medium text-primary transition-colors hover:bg-primary/20 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              <Play aria-hidden className="h-3.5 w-3.5" />
              Run backtest
            </button>
          </div>
        </Panel>

        <div className="space-y-4">
          {submitted === null ? (
            <Panel>
              <p className="text-sm text-muted-foreground">
                Configure the run and execute it. Results are scoped to the selected version and
                cutoff; nothing is cached across configurations.
              </p>
            </Panel>
          ) : result.isFetching ? (
            <Panel bodyClassName="">
              <TableSkeleton rows={5} cols={4} />
            </Panel>
          ) : r ? (
            <>
              <WarningBanner>
                {r.economicAvailable
                  ? "Economic evaluation available for this dataset."
                  : "Economic backtest unavailable for this dataset. Predictive evaluation only."}{" "}
                {r.note}
              </WarningBanner>

              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <MetricCard label="Sample" value={int(r.sampleSize)} hint="Scored observations" />
                <MetricCard label="Brier" value={num(r.brier, 4)} hint="Lower is better" />
                <MetricCard label="Log loss" value={num(r.logLoss, 4)} hint="Lower is better" />
                <MetricCard
                  label="Calibration error"
                  value={num(r.calibrationError, 4)}
                  hint="Mean absolute gap"
                />
                <MetricCard
                  label="ROI"
                  value={EMPTY}
                  hint="Economic evaluation unavailable"
                  tone="muted"
                />
                <MetricCard
                  label="Yield"
                  value={EMPTY}
                  hint="Economic evaluation unavailable"
                  tone="muted"
                />
                <MetricCard
                  label="Max drawdown"
                  value={EMPTY}
                  hint="Requires staked results"
                  tone="muted"
                />
                <MetricCard
                  label="Pick line value"
                  value={EMPTY}
                  hint="Requires validated near-close capture"
                  tone="muted"
                />
              </div>

              <div className="grid gap-4 xl:grid-cols-2">
                <ChartContainer
                  title="Calibration"
                  subtitle="Predicted probability versus observed frequency against the ideal diagonal."
                  demo
                >
                  <CalibrationChart bins={r.buckets} />
                </ChartContainer>
                <ChartContainer
                  title="Sample per probability bucket"
                  subtitle="Bucket occupancy behind the calibration curve."
                  demo
                >
                  <ProbabilityBuckets bins={r.buckets} />
                </ChartContainer>
                <ChartContainer
                  title="Monthly Brier"
                  subtitle="Temporal stability of predictive quality."
                  demo
                  className="xl:col-span-2"
                >
                  <MonthlyBars data={r.monthly} dataKey="brier" />
                </ChartContainer>
              </div>

              <div className="grid gap-4 xl:grid-cols-2">
                <SplitTable title="By competition" rows={r.leagueSplit} />
                <SplitTable title="By market" rows={r.marketSplit} />
              </div>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function SplitTable({
  title,
  rows,
}: {
  title: string;
  rows: Array<{ key: string; label: string; sample: number; brier: number | null }>;
}) {
  return (
    <Panel title={title} bodyClassName="">
      <TableShell>
        <THead>
          <TH>Segment</TH>
          <TH align="right">
            <MetricLabel term="sampleSize">Sample</MetricLabel>
          </TH>
          <TH align="right">
            <MetricLabel term="brier">Brier</MetricLabel>
          </TH>
          <TH align="right">ROI</TH>
        </THead>
        <tbody>
          {rows.map((r) => (
            <TRow key={r.key}>
              <TD className="text-sm">{r.label}</TD>
              <TD align="right">
                <Numeric muted>{int(r.sample)}</Numeric>
              </TD>
              <TD align="right">
                <Numeric>{num(r.brier, 4)}</Numeric>
              </TD>
              <TD align="right">
                <span className="text-caption text-subtle-foreground">Unavailable</span>
              </TD>
            </TRow>
          ))}
        </tbody>
      </TableShell>
    </Panel>
  );
}
