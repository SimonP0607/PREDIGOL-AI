/**
 * Models lab, live. The market comes first: a model is only interesting if it
 * knows something the de-vigged closing price did not. Predictive quality and
 * betting performance are separate panels, and the betting one is labelled
 * hypothetical because it is a backtest simulation, not a record of bets.
 */
import { useMemo, useState } from "react";
import {
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { PageHeader } from "@/components/layout/PageHeader";
import { KeyValue, Panel, WarningBanner } from "@/components/primitives/Panel";
import { TableShell, THead, TH, TRow, TD, TableSkeleton } from "@/components/primitives/DataTable";
import { StatusBadge, type BadgeTone } from "@/components/primitives/StatusBadge";
import { Numeric } from "@/components/primitives/Indicators";
import { SegmentedTabs } from "@/components/system/Filters";
import { InfoTip, MetricLabel } from "@/components/system/InfoTip";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice, Nullable, SectionView, StatusNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type {
  BacktestSessionSummary,
  BaselineScore,
  MarketComparison,
  ModelVersionSummary,
  SplitRow,
  Verdict,
} from "@/lib/api/v1/types";
import { int } from "@/lib/format";
import { dec, shortHash, utcDate, utcDateTime } from "./format";
import { baselineLabel, seasonLabel } from "./labels";
import { Fact } from "./shared";

const NO_BACKTEST = "This model version has no stored walk-forward backtest.";

const MODEL_LABEL: Record<string, string> = {
  poisson: "Poisson (Maher)",
  dixon_coles: "Dixon-Coles",
  elo_ologit: "Elo V2 + ordered logit",
  base_rates: "League base rates",
  mnlogit: "Multinomial logit (features v2)",
};
/** Families that price 1X2 only: no goal distribution, so no Over/Under or BTTS. */
const ONE_X_TWO_ONLY = new Set(["elo_ologit", "base_rates", "mnlogit"]);

const verdictTone: Record<Verdict, BadgeTone> = {
  better: "positive",
  indistinguishable: "neutral",
  worse: "negative",
};

const VERDICT_TEXT: Record<Verdict, string> = {
  better: "Beats market",
  indistinguishable: "No detectable difference",
  worse: "Worse than market",
};

function signed(value: string | number | null | undefined, digits = 4): string | null {
  if (value === null || value === undefined) return null;
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return null;
  return `${n > 0 ? "+" : n < 0 ? "−" : "±"}${Math.abs(n).toFixed(digits)}`;
}

function interval(c: MarketComparison): string {
  return `[${signed(c.logloss_diff_ci_low)}, ${signed(c.logloss_diff_ci_high)}]`;
}

function VerdictBadge({ c }: { c: MarketComparison | null | undefined }) {
  if (!c) return <Nullable value={null} reason="No market price for this model's fixtures." />;
  return <StatusBadge tone={verdictTone[c.verdict]}>{VERDICT_TEXT[c.verdict]}</StatusBadge>;
}

export function ModelsLive() {
  const q = useLiveQuery(live.models);
  const d = q.data?.data;
  const models = useMemo(
    () =>
      d?.models.status === "ok"
        ? [...d.models.data].sort(
            (a, b) =>
              Number(a.latest_backtest?.logloss ?? Infinity) -
              Number(b.latest_backtest?.logloss ?? Infinity),
          )
        : [],
    [d],
  );
  const tested = models.filter((m) => m.latest_backtest?.primary);
  const beating = tested.filter((m) => m.latest_backtest?.primary?.verdict === "better");
  const session = d?.backtest.status === "ok" ? d.backtest.data : null;

  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumb={[{ label: "Research" }, { label: "Models" }]}
        title="Models"
        description="A model is judged against the de-vigged market, on the same fixtures, out of sample. Predictive quality and betting performance are separate questions."
      />
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      {session && tested.length ? (
        beating.length ? (
          <WarningBanner tone="info">
            {beating.map((m) => MODEL_LABEL[m.name] ?? m.name).join(", ")} scored better than{" "}
            {baselineLabel(session.primary_baseline)} on the {seasonLabel(session.test_season)} test
            season, with the whole 95% interval below zero. One season is one sample; nothing is
            promoted automatically.
          </WarningBanner>
        ) : (
          <WarningBanner>
            No model beats the market. On {int(session.n_targets)} test fixtures (
            {seasonLabel(session.test_season)}), every model has a higher log loss than{" "}
            {baselineLabel(session.primary_baseline)}, with the whole 95% interval above zero. All
            models stay experimental and none feeds a pick.
          </WarningBanner>
        )
      ) : null}

      <Panel
        title="Market baseline"
        subtitle="The bar every model has to clear: bookmaker prices with the margin removed, scored like a model"
        bodyClassName=""
      >
        {!d ? (
          <TableSkeleton rows={4} cols={6} />
        ) : (
          <div className="divide-y divide-border">
            <SectionView section={d.backtest}>
              {(s) => (s ? <SessionFacts session={s} /> : null)}
            </SectionView>
            <SectionView section={d.historical_baselines}>
              {(rows) => <BaselineTable rows={rows} />}
            </SectionView>
            <div className="px-4 py-3">
              <div className="flex flex-wrap items-center gap-2 text-caption text-muted-foreground">
                <span className="text-label text-subtle-foreground">Live consensus</span>
                <SectionView section={d.market_baseline} compact>
                  {(b) =>
                    b ? (
                      <span className="numeric">
                        {int(b.fixtures_with_consensus)} fixtures · {b.methods.join(", ")} · last{" "}
                        {utcDateTime(b.last_as_of)}
                      </span>
                    ) : null
                  }
                </SectionView>
              </div>
            </div>
          </div>
        )}
      </Panel>

      <Panel
        title="Predictive quality · 1X2"
        subtitle="Walk-forward, out of sample. Lower log loss and Brier are better; ECE is calibration error. Accuracy is not a ranking metric."
        bodyClassName=""
      >
        {!d ? (
          <TableSkeleton rows={4} cols={8} />
        ) : (
          <SectionView section={d.models}>
            {() => <Leaderboard models={models} baselines={d.historical_baselines} />}
          </SectionView>
        )}
      </Panel>

      {tested.length ? <ModelDetail models={tested} session={session} /> : null}

      <Panel
        title="Betting performance"
        subtitle="Kept apart from predictive quality. A backtest simulation is not a betting record."
        bodyClassName=""
      >
        {!d ? <TableSkeleton rows={3} cols={7} /> : <BettingTable models={tested} />}
        <div className="border-t border-border px-4 py-3 text-caption text-muted-foreground">
          <ShadowPicksLine />
        </div>
      </Panel>
    </div>
  );
}

function SessionFacts({ session }: { session: BacktestSessionSummary }) {
  return (
    <dl className="grid gap-x-8 px-4 py-3 sm:grid-cols-2 xl:grid-cols-3">
      <Fact
        label="Test season"
        value={`${seasonLabel(session.test_season)} · ${utcDate(session.test_from)} – ${utcDate(session.test_to)}`}
      />
      <Fact label="Fixtures" value={int(session.n_targets)} />
      <Fact label="Competitions" value={session.competitions.map((c) => c.name).join(", ")} />
      <Fact
        label="Hyper-parameters chosen on"
        value={`${seasonLabel(session.validation_season)} only`}
      />
      <Fact label="Protocol" value="walk-forward, refit daily" />
      <Fact label="Primary baseline" value={baselineLabel(session.primary_baseline)} />
    </dl>
  );
}

function BaselineTable({ rows }: { rows: BaselineScore[] }) {
  return (
    <TableShell>
      <THead>
        <TH>Baseline</TH>
        <TH>Market</TH>
        <TH>
          <InfoTip
            term="historicalClosing"
            className="text-label font-semibold text-subtle-foreground"
          >
            Source
          </InfoTip>
        </TH>
        <TH align="right">
          <MetricLabel term="sampleSize">Sample</MetricLabel>
        </TH>
        <TH align="right">
          <MetricLabel term="logLoss">Log loss</MetricLabel>
        </TH>
        <TH align="right">
          <MetricLabel term="brier">Brier</MetricLabel>
        </TH>
        <TH align="right">
          <MetricLabel term="calibrationError">ECE</MetricLabel>
        </TH>
        <TH align="right">
          <MetricLabel term="overround">Overround</MetricLabel>
        </TH>
      </THead>
      <tbody>
        {rows.map((b) => (
          <TRow key={`${b.baseline_key}-${b.market_key}`} selected={b.is_primary}>
            <TD>
              <div className="flex items-center gap-2 text-sm">
                {baselineLabel(b.baseline_key)}
                {b.is_primary ? <StatusBadge tone="brand">Primary</StatusBadge> : null}
              </div>
            </TD>
            <TD className="text-xs text-muted-foreground">
              {b.market_key === "OU" ? `Over/Under ${Number(b.line)}` : b.market_key}
            </TD>
            <TD className="text-xs text-muted-foreground">{b.source}</TD>
            <TD align="right">
              <Numeric>{int(b.n_samples)}</Numeric>
            </TD>
            <TD align="right">
              <Numeric>{dec(b.logloss, 4)}</Numeric>
            </TD>
            <TD align="right">
              <Numeric>{dec(b.brier, 4)}</Numeric>
            </TD>
            <TD align="right">
              <Numeric>{dec(b.ece, 4)}</Numeric>
            </TD>
            <TD align="right">
              <Nullable
                value={dec(b.mean_overround, 3)}
                reason="Two-way market de-vigged on the fly; overround not stored."
                className="numeric"
              />
            </TD>
          </TRow>
        ))}
      </tbody>
    </TableShell>
  );
}

function Leaderboard({
  models,
  baselines,
}: {
  models: ModelVersionSummary[];
  baselines: { status: string; data: BaselineScore[] };
}) {
  const primary =
    baselines.status === "ok" ? (baselines.data.find((b) => b.is_primary) ?? null) : null;
  return (
    <TableShell>
      <THead>
        <TH>Model</TH>
        <TH align="right">
          <MetricLabel term="sampleSize">Sample</MetricLabel>
        </TH>
        <TH align="right">
          <MetricLabel term="logLoss">Log loss</MetricLabel>
        </TH>
        <TH align="right">
          <MetricLabel term="brier">Brier</MetricLabel>
        </TH>
        <TH align="right">
          <MetricLabel term="calibrationError">ECE</MetricLabel>
        </TH>
        <TH align="right">
          <MetricLabel term="vsMarket">Δ log loss vs market</MetricLabel>
        </TH>
        <TH>Verdict</TH>
        <TH>Version</TH>
      </THead>
      <tbody>
        {primary ? (
          <TRow selected>
            <TD>
              <div className="text-sm">{baselineLabel(primary.baseline_key)}</div>
              <div className="text-caption text-subtle-foreground">market baseline</div>
            </TD>
            <TD align="right">
              <Numeric>{int(primary.n_samples)}</Numeric>
            </TD>
            <TD align="right">
              <Numeric>{dec(primary.logloss, 4)}</Numeric>
            </TD>
            <TD align="right">
              <Numeric>{dec(primary.brier, 4)}</Numeric>
            </TD>
            <TD align="right">
              <Numeric>{dec(primary.ece, 4)}</Numeric>
            </TD>
            <TD align="right" className="text-caption text-subtle-foreground">
              reference
            </TD>
            <TD>
              <StatusBadge tone="brand">Baseline</StatusBadge>
            </TD>
            <TD className="text-xs text-muted-foreground">{primary.source}</TD>
          </TRow>
        ) : null}
        {models.map((m) => {
          const bt = m.latest_backtest;
          const c = bt?.primary ?? null;
          return (
            <TRow key={m.version_id}>
              <TD>
                <div className="text-sm">{MODEL_LABEL[m.name] ?? m.name}</div>
                <div className="text-caption text-subtle-foreground">
                  {m.family} · {m.status}
                </div>
              </TD>
              <TD align="right">
                <Nullable
                  value={
                    bt
                      ? `${int(bt.n_samples)}${bt.coverage ? ` / ${int(bt.coverage.targets)}` : ""}`
                      : null
                  }
                  reason={NO_BACKTEST}
                  className="numeric"
                />
              </TD>
              <TD align="right">
                <Nullable value={dec(bt?.logloss, 4)} reason={NO_BACKTEST} className="numeric" />
              </TD>
              <TD align="right">
                <Nullable value={dec(bt?.brier, 4)} reason={NO_BACKTEST} className="numeric" />
              </TD>
              <TD align="right">
                <Nullable value={dec(bt?.ece, 4)} reason={NO_BACKTEST} className="numeric" />
              </TD>
              <TD align="right">
                {c ? (
                  <div className="numeric">
                    <span
                      className={
                        c.verdict === "worse"
                          ? "text-negative"
                          : c.verdict === "better"
                            ? "text-positive"
                            : ""
                      }
                    >
                      {signed(c.logloss_diff)}
                    </span>
                    <div className="text-caption text-subtle-foreground">
                      {interval(c)} · n={int(c.n_common)}
                    </div>
                  </div>
                ) : (
                  <Nullable
                    value={null}
                    reason={bt ? "No common fixtures with the market." : NO_BACKTEST}
                  />
                )}
              </TD>
              <TD>
                {bt ? <VerdictBadge c={c} /> : <Nullable value={null} reason={NO_BACKTEST} />}
              </TD>
              <TD className="numeric text-caption text-muted-foreground">
                <span title={m.version}>{shortVersion(m.version)}</span>
              </TD>
            </TRow>
          );
        })}
      </tbody>
    </TableShell>
  );
}

function shortVersion(v: string): string {
  const at = v.lastIndexOf("@");
  const semver = v.split("/")[0] ?? v;
  return at > 0 ? `${semver} @${v.slice(at + 1)}` : semver;
}

const detailTabs = ["Calibration", "Leagues", "Temporal stability", "Markets", "Protocol"] as const;
type DetailTab = (typeof detailTabs)[number];

function ModelDetail({
  models,
  session,
}: {
  models: ModelVersionSummary[];
  session: BacktestSessionSummary | null;
}) {
  const [selected, setSelected] = useState(models[0]?.name ?? "");
  const [tab, setTab] = useState<DetailTab>("Calibration");
  const model = models.find((m) => m.name === selected) ?? models[0];
  if (!model?.latest_backtest) return null;
  const bt = model.latest_backtest;
  const names = models.map((m) => m.name);
  return (
    <Panel title="Model detail" bodyClassName="p-4 space-y-4">
      <SegmentedTabs
        tabs={names}
        value={model.name}
        onChange={setSelected}
        format={(n) => MODEL_LABEL[n] ?? n}
        label="Model"
      />
      <p className="text-caption text-muted-foreground">{model.description}</p>
      <SegmentedTabs tabs={detailTabs} value={tab} onChange={setTab} label="Detail" />
      {tab === "Calibration" ? <CalibrationView model={model} /> : null}
      {tab === "Leagues" ? <SplitTable rows={bt.by_competition} keyLabel="Competition" /> : null}
      {tab === "Temporal stability" ? <MonthlyView model={model} /> : null}
      {tab === "Markets" ? <MarketsView model={model} /> : null}
      {tab === "Protocol" ? <ProtocolView model={model} session={session} /> : null}
    </Panel>
  );
}

function CalibrationView({ model }: { model: ModelVersionSummary }) {
  const bt = model.latest_backtest!;
  const points = bt.calibration
    .filter((b) => b.n > 0 && b.mean_predicted !== null && b.observed_rate !== null)
    .map((b) => ({ predicted: b.mean_predicted!, observed: b.observed_rate!, n: b.n }));
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
      <div>
        <div className="h-64 w-full" aria-label="Reliability diagram">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart margin={{ top: 8, right: 12, bottom: 24, left: 4 }}>
              <CartesianGrid stroke="var(--border)" strokeDasharray="2 4" />
              <XAxis
                type="number"
                dataKey="predicted"
                domain={[0, 1]}
                tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
                stroke="var(--subtle-foreground)"
                fontSize={11}
                label={{
                  value: "Predicted probability",
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
                formatter={(v: number, name: string) =>
                  name === "n" ? int(v) : `${(v * 100).toFixed(1)}%`
                }
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
                legendType="none"
                tooltipType="none"
              />
              <Scatter data={points} fill="var(--primary)" isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        <p className="mt-2 text-caption text-muted-foreground">
          Every outcome of every test fixture, in ten equal-width bins. The dashed diagonal is
          perfect calibration: below it the model was over-confident in that bin, above it
          under-confident. ECE {dec(bt.ece, 4)}.
        </p>
      </div>
      <TableShell compact>
        <THead>
          <TH>Bin</TH>
          <TH align="right">Predicted</TH>
          <TH align="right">Observed</TH>
          <TH align="right">Sample</TH>
        </THead>
        <tbody>
          {bt.calibration.map((b) => (
            <TRow key={b.lower}>
              <TD className="numeric text-xs">
                {Math.round(b.lower * 100)}–{Math.round(b.upper * 100)}%
              </TD>
              <TD align="right">
                <Nullable
                  value={
                    b.mean_predicted === null ? null : `${(b.mean_predicted * 100).toFixed(1)}%`
                  }
                  reason="No prediction fell in this bin."
                  className="numeric"
                />
              </TD>
              <TD align="right">
                <Nullable
                  value={b.observed_rate === null ? null : `${(b.observed_rate * 100).toFixed(1)}%`}
                  reason="No prediction fell in this bin."
                  className="numeric"
                />
              </TD>
              <TD align="right">
                <Numeric muted={b.n === 0}>{int(b.n)}</Numeric>
              </TD>
            </TRow>
          ))}
        </tbody>
      </TableShell>
    </div>
  );
}

function SplitTable({ rows, keyLabel }: { rows: SplitRow[]; keyLabel: string }) {
  if (!rows.length) {
    return <StatusNotice status="empty" reason="No split was stored for this run." compact />;
  }
  return (
    <TableShell>
      <THead>
        <TH>{keyLabel}</TH>
        <TH align="right">Fixtures</TH>
        <TH align="right">Model log loss</TH>
        <TH align="right">Market log loss</TH>
        <TH align="right">
          <MetricLabel term="vsMarket">Difference</MetricLabel>
        </TH>
      </THead>
      <tbody>
        {rows.map((r) => (
          <TRow key={r.key}>
            <TD className="text-sm">{r.label}</TD>
            <TD align="right">
              <Numeric>{int(r.n)}</Numeric>
            </TD>
            <TD align="right">
              <Numeric>{r.model_logloss.toFixed(4)}</Numeric>
            </TD>
            <TD align="right">
              <Numeric muted>{r.baseline_logloss.toFixed(4)}</Numeric>
            </TD>
            <TD align="right">
              <span
                className={r.logloss_diff > 0 ? "numeric text-negative" : "numeric text-positive"}
              >
                {signed(r.logloss_diff)}
              </span>
            </TD>
          </TRow>
        ))}
      </tbody>
    </TableShell>
  );
}

function MonthlyView({ model }: { model: ModelVersionSummary }) {
  const rows = model.latest_backtest!.by_month;
  const data = rows.map((r) => ({ month: r.key, diff: r.logloss_diff, n: r.n }));
  return (
    <div className="space-y-3">
      <div className="h-52 w-full" aria-label="Monthly log-loss difference against the market">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 8, left: 4 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="2 4" />
            <XAxis dataKey="month" stroke="var(--subtle-foreground)" fontSize={11} />
            <YAxis
              stroke="var(--subtle-foreground)"
              fontSize={11}
              tickFormatter={(v: number) => v.toFixed(2)}
            />
            <ReferenceLine y={0} stroke="var(--border-strong)" strokeDasharray="4 4" />
            <Tooltip
              contentStyle={{
                background: "var(--popover)",
                border: "1px solid var(--border)",
                borderRadius: 8,
                fontSize: 12,
              }}
              formatter={(v: number, name: string) => (name === "n" ? int(v) : (signed(v) ?? ""))}
            />
            <Line
              type="monotone"
              dataKey="diff"
              name="model − market"
              stroke="var(--primary)"
              dot={{ r: 2 }}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <p className="text-caption text-muted-foreground">
        Log loss of the model minus the market, month by month. Above the dashed line the market was
        better that month. A model that only wins in one month has not shown anything.
      </p>
      <SplitTable rows={rows} keyLabel="Month" />
    </div>
  );
}

function ComparisonRows({ rows }: { rows: MarketComparison[] }) {
  return (
    <TableShell>
      <THead>
        <TH>Against</TH>
        <TH align="right">Common fixtures</TH>
        <TH align="right">Model</TH>
        <TH align="right">Market</TH>
        <TH align="right">
          <MetricLabel term="vsMarket">Δ log loss [95%]</MetricLabel>
        </TH>
        <TH align="right">Δ Brier</TH>
        <TH>Verdict</TH>
      </THead>
      <tbody>
        {rows.map((c) => (
          <TRow key={`${c.baseline_key}-${c.market_key}`}>
            <TD className="text-sm">{baselineLabel(c.baseline_key)}</TD>
            <TD align="right">
              <Numeric>{int(c.n_common)}</Numeric>
            </TD>
            <TD align="right">
              <Numeric>{dec(c.model_logloss, 4)}</Numeric>
            </TD>
            <TD align="right">
              <Numeric muted>{dec(c.baseline_logloss, 4)}</Numeric>
            </TD>
            <TD align="right">
              <span className="numeric">
                {signed(c.logloss_diff)}{" "}
                <span className="text-caption text-subtle-foreground">{interval(c)}</span>
              </span>
            </TD>
            <TD align="right">
              <Numeric>{signed(c.brier_diff)}</Numeric>
            </TD>
            <TD>
              <VerdictBadge c={c} />
            </TD>
          </TRow>
        ))}
      </tbody>
    </TableShell>
  );
}

function MarketsView({ model }: { model: ModelVersionSummary }) {
  const bt = model.latest_backtest!;
  const x12 = bt.vs_market.filter((c) => c.market_key === "1X2");
  const ou = bt.vs_market.filter((c) => c.market_key === "OU");
  return (
    <div className="space-y-4">
      <div>
        <div className="mb-2 text-label text-subtle-foreground">1X2</div>
        <ComparisonRows rows={x12} />
      </div>
      <div>
        <div className="mb-2 text-label text-subtle-foreground">Over/Under 2.5</div>
        {ou.length ? (
          <ComparisonRows rows={ou} />
        ) : (
          <StatusNotice
            status="not_available"
            reason={
              ONE_X_TWO_ONLY.has(model.name)
                ? `${MODEL_LABEL[model.name] ?? model.name} prices 1X2 only: it has no goal distribution.`
                : "No Over/Under comparison was stored for this run."
            }
            compact
          />
        )}
      </div>
      <div>
        <div className="mb-2 text-label text-subtle-foreground">Both teams to score</div>
        {bt.btts ? (
          <div className="grid gap-x-8 sm:grid-cols-2 xl:grid-cols-4">
            <KeyValue label="Fixtures" value={int(bt.btts.n)} />
            <KeyValue label="Log loss" value={bt.btts.log_loss.toFixed(4)} />
            <KeyValue label="Brier" value={bt.btts.brier.toFixed(4)} />
            <KeyValue label="ECE" value={bt.btts.ece.toFixed(4)} />
          </div>
        ) : null}
        <p className="mt-2 text-caption text-muted-foreground">
          {bt.btts
            ? "No market baseline: the historical source publishes no BTTS prices, so this is scored against outcomes only and cannot be called better or worse than the market."
            : "This model does not price BTTS."}
        </p>
      </div>
    </div>
  );
}

function ProtocolView({
  model,
  session,
}: {
  model: ModelVersionSummary;
  session: BacktestSessionSummary | null;
}) {
  const bt = model.latest_backtest!;
  const selection = session?.selection[model.name];
  const uncovered = Object.entries(bt.coverage?.uncovered ?? {});
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div>
        <div className="mb-1 text-label text-subtle-foreground">Lineage</div>
        <KeyValue label="Model version" value={model.version} />
        <KeyValue label="Code version" value={shortHash(bt.code_version)} />
        <KeyValue label="Backtest run" value={`#${bt.run_id}`} />
        <KeyValue label="Session" value={session ? shortHash(session.session_uuid, 8) : "—"} />
        <KeyValue label="Dataset hash" value={session ? shortHash(session.dataset_hash) : "—"} />
        <KeyValue
          label="Trained on results"
          value={`${utcDate(model.train_from)} – ${utcDate(model.train_to)} · ${int(model.n_train)} fixtures`}
        />
        <KeyValue label="Finished" value={utcDateTime(bt.finished_at)} />
        <KeyValue label="Accuracy (not ranked)" value={`${Number(bt.accuracy_pct).toFixed(1)}%`} />
      </div>
      <div>
        <div className="mb-1 text-label text-subtle-foreground">Coverage</div>
        {bt.coverage ? (
          <>
            <KeyValue
              label="Predicted"
              value={`${int(bt.coverage.predicted)} of ${int(bt.coverage.targets)}`}
            />
            <KeyValue label="Refits" value={int(bt.coverage.fits)} />
            <KeyValue label="Failed fits" value={int(bt.coverage.failed_fits)} />
            <KeyValue label="Without interval" value={int(bt.coverage.no_interval)} />
            {uncovered.map(([why, n]) => (
              <KeyValue key={why} label={`Not predicted · ${int(n)}`} value={why} />
            ))}
          </>
        ) : (
          <StatusNotice status="not_available" reason="Coverage was not recorded." compact />
        )}
        {selection ? (
          <div className="mt-4">
            <div className="mb-1 text-label text-subtle-foreground">
              Hyper-parameters · chosen on{" "}
              {seasonLabel(selection.validation_season ?? session?.validation_season)}
            </div>
            <KeyValue label="Time decay ξ (per day)" value={String(selection.chosen.xi)} />
            <KeyValue label="Shrinkage penalty" value={String(selection.chosen.penalty)} />
            <KeyValue
              label="Candidates scored"
              value={
                selection.validation_logloss
                  ? `${Object.keys(selection.validation_logloss).length} (validation log loss)`
                  : "not stored in this session"
              }
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}

function BettingTable({ models }: { models: ModelVersionSummary[] }) {
  const rows = models.filter((m) => m.latest_backtest?.betting);
  if (!rows.length) {
    return (
      <StatusNotice
        status="not_available"
        reason="No backtest with historical prices has been stored."
      />
    );
  }
  const rule = rows[0]!.latest_backtest!.betting!.rule;
  const source = rows[0]!.latest_backtest!.betting!.odds_source;
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2.5 text-caption text-muted-foreground">
        <StatusBadge tone="warning">Hypothetical</StatusBadge>
        <InfoTip term="hypotheticalBetting" className="text-caption">
          <span>
            Backtest simulation · {rule} · prices: {source}
          </span>
        </InfoTip>
      </div>
      <TableShell>
        <THead>
          <TH>Model</TH>
          <TH align="right">Fixtures priced</TH>
          <TH align="right">Bets</TH>
          <TH align="right">Profit (units)</TH>
          <TH align="right">
            <MetricLabel term="roi">ROI</MetricLabel>
          </TH>
          <TH align="right">95% interval</TH>
          <TH align="right">
            <MetricLabel term="drawdown">Max drawdown</MetricLabel>
          </TH>
        </THead>
        <tbody>
          {rows.map((m) => {
            const b = m.latest_backtest!.betting!;
            const roi = b.roi_pct === null ? null : Number(b.roi_pct);
            return (
              <TRow key={m.version_id}>
                <TD className="text-sm">{MODEL_LABEL[m.name] ?? m.name}</TD>
                <TD align="right">
                  <Numeric>{int(b.fixtures_priced)}</Numeric>
                </TD>
                <TD align="right">
                  <Numeric>{int(b.n_bets)}</Numeric>
                </TD>
                <TD align="right">
                  <Numeric>{signed(b.profit_units, 1)}</Numeric>
                </TD>
                <TD align="right">
                  <Nullable
                    value={roi === null ? null : `${signed(roi, 1)}%`}
                    reason="No bet met the rule."
                    className={roi !== null && roi < 0 ? "numeric text-negative" : "numeric"}
                  />
                </TD>
                <TD align="right">
                  <Nullable
                    value={
                      b.roi_ci_low === null || b.roi_ci_high === null
                        ? null
                        : `[${signed(b.roi_ci_low, 1)}%, ${signed(b.roi_ci_high, 1)}%]`
                    }
                    reason="Fewer than 30 bets: no interval is reported."
                    className="numeric text-muted-foreground"
                  />
                </TD>
                <TD align="right">
                  <Nullable
                    value={dec(b.max_drawdown_units, 1)}
                    reason="No bets."
                    className="numeric"
                  />
                </TD>
              </TRow>
            );
          })}
        </tbody>
      </TableShell>
      <p className="px-4 pb-3 text-caption text-muted-foreground">
        {rows[0]!.latest_backtest!.betting!.note}
      </p>
    </div>
  );
}

/** What the shadow picks have actually done - read, not assumed. */
function ShadowPicksLine() {
  const q = useLiveQuery(live.performance);
  const d = q.data?.data;
  if (!q.data || !d) return <span className="text-subtle-foreground">Shadow picks: loading…</span>;
  if (q.data.status !== "ok" || d.roi_pct === null) {
    return (
      <span>
        <span className="text-label text-subtle-foreground">Shadow picks</span> —{" "}
        {q.data.reason ?? d.note} See Performance.
      </span>
    );
  }
  const roi = Number(d.roi_pct);
  return (
    <span>
      <span className="text-label text-subtle-foreground">Shadow picks</span> — {d.settled} settled
      at the captured price: ROI{" "}
      <span className={roi > 0 ? "text-positive" : "text-negative"}>{d.roi_pct}%</span>, hit rate{" "}
      {d.hit_rate}%. Not a betting record; the breakdown by model is in Performance.
    </span>
  );
}
