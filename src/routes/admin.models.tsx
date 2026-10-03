import { useState } from "react";
import { DATA_MODE } from "@/lib/api/mode";
import { DemoRegion } from "@/components/system/DataSources";
import { ModelsLive } from "@/live/ModelsLive";
import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { PageHeader } from "@/components/layout/PageHeader";
import {
  Panel,
  KeyValue,
  MetricCard,
  WarningBanner,
  EmptyState,
} from "@/components/primitives/Panel";
import { TableShell, THead, TH, TRow, TD, TableSkeleton } from "@/components/primitives/DataTable";
import { ModelBadge, StatusBadge } from "@/components/primitives/StatusBadge";
import { Numeric } from "@/components/primitives/Indicators";
import { MetricLabel } from "@/components/system/InfoTip";
import { modelQueries, queries } from "@/lib/api/resources";
import { EMPTY, int, num, pct, signedPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { ModelSummary } from "@/types/domain";

export const Route = createFileRoute("/admin/models")({
  head: () => ({
    meta: [
      { title: "Models — Football Intelligence" },
      {
        name: "description",
        content:
          "Model research lab: leaderboard against the market baseline, calibration, sample sufficiency and version history.",
      },
      { property: "og:title", content: "Models — Football Intelligence" },
      {
        property: "og:description",
        content: "Model leaderboard and calibration against the market baseline.",
      },
    ],
  }),
  component: RouteComponent,
});

function RouteComponent() {
  if (DATA_MODE === "mock") {
    return (
      <DemoRegion>
        <ModelsPage />
      </DemoRegion>
    );
  }
  return <ModelsLive />;
}

const detailTabs = [
  "Overview",
  "Calibration",
  "Performance",
  "Leagues",
  "Markets",
  "Temporal Stability",
  "Backtests",
  "Versions",
] as const;
type DetailTab = (typeof detailTabs)[number];

function ModelsPage() {
  const models = useQuery(queries.models);
  const [selectedId, setSelectedId] = useState("poisson");
  const [tab, setTab] = useState<DetailTab>("Overview");
  const calibration = useQuery(modelQueries.calibration(selectedId));

  const list = models.data ?? [];
  const selected = list.find((m) => m.id === selectedId);

  return (
    <div className="space-y-5">
      <PageHeader
        breadcrumb={[{ label: "Intelligence" }, { label: "Models" }]}
        title="Model Research Lab"
        description="Every model is scored against the market baseline first. A model that does not beat the baseline is not a model we can use."
      />

      <WarningBanner>
        No model has reached validated status. ROI and pick line value are intentionally empty:
        there is no published, settled sample from which to compute them.
      </WarningBanner>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          label="Models tracked"
          value={String(list.length)}
          hint="Including the baseline"
        />
        <MetricCard label="Validated" value="0" tone="muted" hint="Gate not passed" />
        <MetricCard label="In shadow" value="2" hint="Poisson · Elo" />
        <MetricCard
          label="Best vs baseline"
          value="-0.62%"
          tone="negative"
          hint="Poisson, Brier delta"
        />
      </div>

      <Panel
        title="Predictive quality"
        subtitle="Scored on the same fixture set. Lower Brier, log loss and calibration error are better. This section says nothing about profitability."
        bodyClassName=""
      >
        {models.isLoading ? (
          <TableSkeleton rows={7} cols={9} />
        ) : (
          <TableShell>
            <THead>
              <TH>Model</TH>
              <TH>Version</TH>
              <TH>Status</TH>
              <TH align="right">Sample</TH>
              <TH align="right">
                <MetricLabel term="brier">Brier</MetricLabel>
              </TH>
              <TH align="right">
                <MetricLabel term="logLoss">Log loss</MetricLabel>
              </TH>
              <TH align="right">
                <MetricLabel term="calibrationError">Calib. error</MetricLabel>
              </TH>
              <TH align="right">vs Market</TH>
              <TH align="right">Last evaluation</TH>
            </THead>
            <tbody>
              {list.map((m) => (
                <TRow key={m.id} onClick={() => setSelectedId(m.id)} selected={m.id === selectedId}>
                  <TD>
                    <div className="text-sm">{m.name}</div>
                    <div className="text-caption text-subtle-foreground">{m.family}</div>
                  </TD>
                  <TD>
                    <Numeric className="text-xs" muted>
                      {m.version}
                    </Numeric>
                  </TD>
                  <TD>
                    <ModelBadge status={m.status} />
                  </TD>
                  <TD align="right">
                    <Numeric>{int(m.sample)}</Numeric>
                  </TD>
                  <TD align="right">
                    <Numeric>{num(m.brier, 4)}</Numeric>
                  </TD>
                  <TD align="right">
                    <Numeric>{num(m.logLoss, 4)}</Numeric>
                  </TD>
                  <TD align="right">
                    <Numeric>{num(m.calibrationError, 4)}</Numeric>
                  </TD>
                  <TD align="right">
                    <span
                      className={cn(
                        "numeric text-sm",
                        m.vsMarket === null
                          ? "text-muted-foreground"
                          : m.vsMarket > 0
                            ? "text-positive"
                            : m.vsMarket < 0
                              ? "text-negative"
                              : "text-muted-foreground",
                      )}
                    >
                      {m.vsMarket === null ? EMPTY : signedPct(m.vsMarket, 2)}
                    </span>
                  </TD>
                  <TD align="right">
                    <Numeric className="text-xs" muted>
                      {m.lastEvaluation ?? EMPTY}
                    </Numeric>
                  </TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        )}
      </Panel>

      <Panel
        title="Betting performance"
        subtitle="Economic evaluation is a separate question from predictive quality and stays locked until a validated, settled sample exists."
        actions={<StatusBadge tone="neutral">Locked</StatusBadge>}
        bodyClassName=""
      >
        <div aria-disabled className="pointer-events-none opacity-60">
          <TableShell>
            <THead>
              <TH>Model</TH>
              <TH align="right">Settled picks</TH>
              <TH align="right">
                <MetricLabel term="roi">ROI</MetricLabel>
              </TH>
              <TH align="right">
                <MetricLabel term="yieldMetric">Yield</MetricLabel>
              </TH>
              <TH align="right">
                <MetricLabel term="pickLineValue">Pick line value</MetricLabel>
              </TH>
              <TH align="right">Hit rate</TH>
              <TH align="right">
                <MetricLabel term="drawdown">Max drawdown</MetricLabel>
              </TH>
            </THead>
            <tbody>
              {list.map((m) => (
                <TRow key={m.id}>
                  <TD className="text-sm">{m.name}</TD>
                  <TD align="right">
                    <Numeric muted>0</Numeric>
                  </TD>
                  {[0, 1, 2, 3, 4].map((i) => (
                    <TD key={i} align="right">
                      <Numeric muted>{EMPTY}</Numeric>
                    </TD>
                  ))}
                </TRow>
              ))}
            </tbody>
          </TableShell>
        </div>
        <p className="border-t border-border px-4 py-2.5 text-caption text-subtle-foreground">
          Insufficient validated sample — no published or settled pick exists in this dataset.
        </p>
      </Panel>

      {selected ? (
        <div className="surface-panel">
          <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
            <div>
              <h2 className="text-heading">{selected.name}</h2>
              <p className="text-caption text-muted-foreground">
                {selected.family} · version <span className="numeric">{selected.version}</span>
              </p>
            </div>
            <ModelBadge status={selected.status} />
          </header>

          <div className="flex gap-1 overflow-x-auto border-b border-border px-2">
            {detailTabs.map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTab(t)}
                className={cn(
                  "-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-xs transition-colors",
                  tab === t
                    ? "border-primary text-foreground"
                    : "border-transparent text-muted-foreground hover:text-foreground",
                )}
              >
                {t}
              </button>
            ))}
          </div>

          <div className="p-4">
            {tab === "Overview" ? <ModelOverview model={selected} /> : null}

            {tab === "Calibration" ? (
              <div className="grid gap-5 lg:grid-cols-3">
                <div className="lg:col-span-2">
                  <div className="text-label text-subtle-foreground">
                    Predicted probability vs observed frequency
                  </div>
                  <div className="mt-3 h-72 w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <ScatterChart margin={{ top: 8, right: 12, bottom: 24, left: 4 }}>
                        <CartesianGrid stroke="var(--border)" strokeDasharray="2 4" />
                        <XAxis
                          type="number"
                          dataKey="predicted"
                          domain={[0, 1]}
                          tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
                          stroke="var(--subtle-foreground)"
                          fontSize={11}
                          label={{
                            value: "Predicted",
                            position: "insideBottom",
                            offset: -12,
                            fill: "var(--subtle-foreground)",
                            fontSize: 11,
                          }}
                        />
                        <YAxis
                          type="number"
                          dataKey="observed"
                          domain={[0, 1]}
                          tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
                          stroke="var(--subtle-foreground)"
                          fontSize={11}
                        />
                        <Tooltip
                          cursor={{ stroke: "var(--border-strong)" }}
                          contentStyle={{
                            background: "var(--popover)",
                            border: "1px solid var(--border)",
                            borderRadius: 8,
                            fontSize: 12,
                          }}
                          formatter={(v: number) => pct(v, 1)}
                        />
                        <Line
                          type="linear"
                          dataKey="observed"
                          data={[
                            { predicted: 0, observed: 0 },
                            { predicted: 1, observed: 1 },
                          ]}
                          stroke="var(--border-strong)"
                          strokeDasharray="4 4"
                          dot={false}
                          isAnimationActive={false}
                        />
                        <Scatter
                          data={calibration.data ?? []}
                          fill="var(--primary)"
                          isAnimationActive={false}
                        />
                      </ScatterChart>
                    </ResponsiveContainer>
                  </div>
                  <p className="mt-2 text-caption text-muted-foreground">
                    The dashed diagonal is perfect calibration. Points above it mean the model is
                    under-confident in that bin; points below mean over-confident.
                  </p>
                </div>
                <div>
                  <div className="text-label text-subtle-foreground">Bin detail</div>
                  <div className="mt-2">
                    <TableShell className="min-w-0">
                      <THead>
                        <TH align="right">Predicted</TH>
                        <TH align="right">Observed</TH>
                        <TH align="right">Sample</TH>
                      </THead>
                      <tbody>
                        {(calibration.data ?? []).map((b) => (
                          <TRow key={b.predicted}>
                            <TD align="right">
                              <Numeric>{pct(b.predicted, 0)}</Numeric>
                            </TD>
                            <TD align="right">
                              <Numeric>{pct(b.observed, 1)}</Numeric>
                            </TD>
                            <TD align="right">
                              <Numeric muted>{int(b.sample)}</Numeric>
                            </TD>
                          </TRow>
                        ))}
                      </tbody>
                    </TableShell>
                  </div>
                </div>
              </div>
            ) : null}

            {tab === "Performance" ? (
              <div className="grid gap-5 lg:grid-cols-2">
                <div>
                  <div className="text-label text-subtle-foreground">
                    Brier delta vs market baseline (rolling)
                  </div>
                  <div className="mt-3 h-56 w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart
                        data={[
                          { w: "W1", d: -0.011 },
                          { w: "W2", d: -0.009 },
                          { w: "W3", d: -0.007 },
                          { w: "W4", d: -0.008 },
                          { w: "W5", d: -0.006 },
                          { w: "W6", d: -0.006 },
                        ]}
                        margin={{ top: 8, right: 12, bottom: 8, left: 4 }}
                      >
                        <CartesianGrid stroke="var(--border)" strokeDasharray="2 4" />
                        <XAxis dataKey="w" stroke="var(--subtle-foreground)" fontSize={11} />
                        <YAxis
                          stroke="var(--subtle-foreground)"
                          fontSize={11}
                          tickFormatter={(v: number) => v.toFixed(3)}
                        />
                        <Tooltip
                          contentStyle={{
                            background: "var(--popover)",
                            border: "1px solid var(--border)",
                            borderRadius: 8,
                            fontSize: 12,
                          }}
                        />
                        <Line
                          type="monotone"
                          dataKey="d"
                          stroke="var(--primary)"
                          strokeWidth={2}
                          dot={false}
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </div>
                <EmptyState
                  title="No monetary performance available"
                  description="Equity curve, drawdown and ROI require settled published picks. The model has never left shadow mode, so no financial series exists."
                />
              </div>
            ) : null}

            {tab === "Leagues" || tab === "Markets" || tab === "Temporal Stability" ? (
              <EmptyState
                title={`${tab} breakdown not available yet`}
                description="Segment scoring is blocked until the evaluation harness writes per-segment results with the same version metadata as the global run."
              />
            ) : null}

            {tab === "Backtests" ? (
              <EmptyState
                title="No backtest runs registered"
                description="Runs appear here once the replay harness records a reproducible run with a git SHA, feature version and dataset hash."
              />
            ) : null}

            {tab === "Versions" ? (
              <div className="space-y-2">
                {[
                  ["v0.4.2-rc1", "2026-09-03", "Current shadow candidate"],
                  ["v0.4.1", "2026-08-21", "Correlation term reworked"],
                  ["v0.3.0", "2026-07-30", "First v2-feature-store build"],
                ].map(([v, d, note]) => (
                  <div
                    key={v}
                    className="flex items-center justify-between rounded-md border border-border bg-elevated/40 px-3 py-2"
                  >
                    <Numeric className="text-xs">{v}</Numeric>
                    <span className="text-xs text-muted-foreground">{note}</span>
                    <Numeric className="text-xs" muted>
                      {d}
                    </Numeric>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ModelOverview({ model }: { model: ModelSummary }) {
  return (
    <div className="grid gap-5 lg:grid-cols-3">
      <div className="lg:col-span-2">
        <p className="text-sm leading-relaxed text-muted-foreground">{model.description}</p>
        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <MetricCard label="Brier" value={num(model.brier, 4)} hint="Lower is better" />
          <MetricCard label="Log loss" value={num(model.logLoss, 4)} hint="Lower is better" />
          <MetricCard
            label="Calibration error"
            value={num(model.calibrationError, 4)}
            hint="Mean absolute, 10 bins"
          />
        </div>
      </div>
      <div>
        <KeyValue label="Status" value={model.status.replace("_", " ")} />
        <KeyValue label="Version" value={model.version} />
        <KeyValue label="Sample" value={int(model.sample)} />
        <KeyValue
          label="vs market"
          value={model.vsMarket === null ? EMPTY : signedPct(model.vsMarket, 2)}
        />
        <KeyValue label="ROI" value={EMPTY} />
        <KeyValue label="Pick line value" value={EMPTY} />
        <KeyValue label="Last evaluation" value={model.lastEvaluation ?? EMPTY} />
      </div>
    </div>
  );
}
