import { createFileRoute } from "@tanstack/react-router";
import { DATA_MODE } from "@/lib/api/mode";
import { DemoRegion } from "@/components/system/DataSources";
import { PerformanceLive } from "@/live/MarketLive";
import { useQuery } from "@tanstack/react-query";
import { Lock } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { MetricCard, Panel, WarningBanner } from "@/components/primitives/Panel";
import { TableShell, THead, TH, TRow, TD } from "@/components/primitives/DataTable";
import { Numeric } from "@/components/primitives/Indicators";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { InfoTip } from "@/components/system/InfoTip";
import {
  ChartContainer,
  DrawdownChart,
  EquityCurve,
  MonthlyBars,
} from "@/components/analytics/Charts";
import { queries } from "@/lib/api/resources";
import { EMPTY, int, num } from "@/lib/format";
import type { GlossaryKey } from "@/lib/glossary";

export const Route = createFileRoute("/admin/performance")({
  head: () => ({
    meta: [
      { title: "Performance · PrediGol Admin" },
      {
        name: "description",
        content:
          "Realised results of published picks. No validated sample exists yet, so every economic metric reads as unavailable.",
      },
      { property: "og:title", content: "Performance · PrediGol Admin" },
      {
        property: "og:description",
        content: "Economic reporting gated behind a validated, settled sample.",
      },
    ],
  }),
  component: RouteComponent,
});

function RouteComponent() {
  if (DATA_MODE === "mock") {
    return (
      <DemoRegion>
        <PerformancePage />
      </DemoRegion>
    );
  }
  return <PerformanceLive />;
}

const metrics: Array<{ key: string; label: string; term: GlossaryKey }> = [
  { key: "pnl", label: "P&L", term: "roi" },
  { key: "roi", label: "ROI", term: "roi" },
  { key: "yield", label: "Yield", term: "yieldMetric" },
  { key: "lineValue", label: "Pick line value", term: "pickLineValue" },
  { key: "hitRate", label: "Hit rate", term: "sampleSize" },
  { key: "drawdown", label: "Max drawdown", term: "drawdown" },
];

function PerformancePage() {
  const performance = useQuery(queries.performance);
  const charts = useQuery(queries.performanceCharts);
  const p = performance.data;
  const c = charts.data;

  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumb={[{ label: "Operations" }, { label: "Performance" }]}
        title="Performance"
        description="Economic reporting over settled, published picks. Nothing is published while the platform runs in shadow mode."
        actions={
          <div className="flex items-center gap-2">
            <StatusBadge tone="warning">Insufficient validated sample</StatusBadge>
          </div>
        }
      />

      <WarningBanner>
        Insufficient validated sample. {p?.note ?? "No settled published picks exist."} Every
        economic metric below stays empty by design — it is never back-filled with demo results.
      </WarningBanner>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          label="Published picks"
          value={int(p?.publishedPicks ?? 0)}
          hint="Required before any economic metric is computed"
        />
        <MetricCard
          label="Settled sample"
          value={int(p?.sampleSize ?? 0)}
          hint="Minimum viable sample not reached"
          tone="warning"
        />
        <MetricCard
          label="Bankroll"
          value={p?.bankroll === null ? EMPTY : num(p?.bankroll, 2)}
          hint="Not initialised"
          tone="muted"
        />
        <MetricCard
          label="Reporting mode"
          value="Shadow"
          hint="No stake is recorded"
          tone="muted"
        />
      </div>

      <Panel
        title="Economic metrics"
        subtitle="Locked until a validated, settled sample exists. Definitions are shown so the contract is unambiguous."
        bodyClassName=""
      >
        <TableShell>
          <THead>
            <TH>Metric</TH>
            <TH align="right">Value</TH>
            <TH>State</TH>
            <TH>Unlock condition</TH>
          </THead>
          <tbody>
            {metrics.map((m) => (
              <TRow key={m.key}>
                <TD>
                  <InfoTip term={m.term} className="text-sm">
                    {m.label}
                  </InfoTip>
                </TD>
                <TD align="right">
                  <Numeric muted>{EMPTY}</Numeric>
                </TD>
                <TD>
                  <StatusBadge tone="neutral">
                    <Lock aria-hidden className="h-3 w-3" />
                    Unavailable
                  </StatusBadge>
                </TD>
                <TD className="text-xs text-muted-foreground">
                  {m.key === "lineValue"
                    ? "Requires validated near-close capture per pick."
                    : "Requires settled published picks above the minimum sample."}
                </TD>
              </TRow>
            ))}
          </tbody>
        </TableShell>
      </Panel>

      <div className="grid gap-4 xl:grid-cols-2">
        <ChartContainer
          title="Equity curve"
          subtitle="Shape only. Values are synthetic and describe the layout, not results."
          demo
        >
          <EquityCurve points={c?.equity ?? []} />
        </ChartContainer>
        <ChartContainer
          title="Drawdown"
          subtitle="Shape only. Synthetic series used to validate the visualisation."
          demo
        >
          <DrawdownChart points={c?.drawdown ?? []} />
        </ChartContainer>
        <ChartContainer
          title="Monthly contribution"
          subtitle="Synthetic monthly buckets. No realised profit is represented."
          demo
        >
          <MonthlyBars data={c?.monthly ?? []} />
        </ChartContainer>
        <Panel
          title="Breakdown"
          subtitle="Predictive sample per market and competition. ROI columns stay empty."
          bodyClassName=""
          actions={<StatusBadge tone="warning">Demo data</StatusBadge>}
        >
          <TableShell>
            <THead>
              <TH>Segment</TH>
              <TH align="right">Sample</TH>
              <TH align="right">Brier</TH>
              <TH align="right">ROI</TH>
            </THead>
            <tbody>
              {[...(c?.marketBreakdown ?? []), ...(c?.leagueBreakdown ?? [])].map((r) => (
                <TRow key={r.key}>
                  <TD className="text-sm">{r.label}</TD>
                  <TD align="right">
                    <Numeric muted>{int(r.sample)}</Numeric>
                  </TD>
                  <TD align="right">
                    <Numeric>{num(r.brier, 4)}</Numeric>
                  </TD>
                  <TD align="right">
                    <span className="text-caption text-subtle-foreground">Not available yet</span>
                  </TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        </Panel>
      </div>
    </div>
  );
}
