/**
 * Models lab, live. The market comes first: a model is only interesting if it
 * knows something the de-vigged closing price did not. Predictive quality and
 * betting performance are separate panels, and the betting one is labelled
 * hypothetical because it is a backtest simulation, not a record of bets.
 */
import { t } from "@/lib/i18n";
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
import { localDecimalText, localFixed, localPct } from "@/lib/i18n/format";

/** Display name of a model; Poisson and Dixon-Coles are proper names in both languages. */
function modelLabel(name: string): string {
  switch (name) {
    case "poisson":
      return "Poisson (Maher)";
    case "dixon_coles":
      return "Dixon-Coles";
    case "elo_ologit":
      return t("research.models.names.elo_ologit");
    case "base_rates":
      return t("research.models.names.base_rates");
    case "mnlogit":
      return t("research.models.names.mnlogit");
    default:
      return name;
  }
}
/** Families that price 1X2 only: no goal distribution, so no Over/Under or BTTS. */
const ONE_X_TWO_ONLY = new Set(["elo_ologit", "base_rates", "mnlogit"]);

const verdictTone: Record<Verdict, BadgeTone> = {
  better: "positive",
  indistinguishable: "neutral",
  worse: "negative",
};

function verdictText(verdict: Verdict): string {
  switch (verdict) {
    case "better":
      return t("research.models.verdict.better");
    case "indistinguishable":
      return t("research.models.verdict.indistinguishable");
    case "worse":
      return t("research.models.verdict.worse");
  }
}

function signed(value: string | number | null | undefined, digits = 4): string | null {
  if (value === null || value === undefined) return null;
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return null;
  return `${n > 0 ? "+" : n < 0 ? "−" : "±"}${localFixed(Math.abs(n), digits)}`;
}

function interval(c: MarketComparison): string {
  return `[${signed(c.logloss_diff_ci_low)}, ${signed(c.logloss_diff_ci_high)}]`;
}

function VerdictBadge({ c }: { c: MarketComparison | null | undefined }) {
  if (!c) return <Nullable value={null} reason={t("research.models.verdict.noMarket")} />;
  return <StatusBadge tone={verdictTone[c.verdict]}>{verdictText(c.verdict)}</StatusBadge>;
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
        title={t("admin.pages.models.title")}
        description={t("admin.pages.models.description")}
      />
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      {session && tested.length ? (
        beating.length ? (
          <WarningBanner tone="info">
            {t("research.models.banner.beating", {
              count: beating.length,
              models: beating.map((m) => modelLabel(m.name)).join(", "),
              baseline: baselineLabel(session.primary_baseline),
              season: seasonLabel(session.test_season),
            })}
          </WarningBanner>
        ) : (
          <WarningBanner>
            {t("research.models.banner.noneBeating", {
              count: session.n_targets,
              n: int(session.n_targets),
              season: seasonLabel(session.test_season),
              baseline: baselineLabel(session.primary_baseline),
            })}
          </WarningBanner>
        )
      ) : null}

      <Panel
        title={t("research.models.baseline.title")}
        subtitle={t("research.models.baseline.subtitle")}
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
                <span className="text-label text-subtle-foreground">
                  {t("research.models.baseline.liveConsensus")}
                </span>
                <SectionView section={d.market_baseline} compact>
                  {(b) =>
                    b ? (
                      <span className="numeric">
                        {t("research.models.baseline.consensusLine", {
                          count: b.fixtures_with_consensus,
                          n: int(b.fixtures_with_consensus),
                          methods: b.methods.join(", "),
                          when: utcDateTime(b.last_as_of),
                        })}
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
        title={t("research.models.quality.title")}
        subtitle={t("research.models.quality.subtitle")}
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
        title={t("research.models.betting.title")}
        subtitle={t("research.models.betting.subtitle")}
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
        label={t("research.common.testSeason")}
        value={`${seasonLabel(session.test_season)} · ${utcDate(session.test_from)} – ${utcDate(session.test_to)}`}
      />
      <Fact label={t("research.common.fixtures")} value={int(session.n_targets)} />
      <Fact
        label={t("research.common.competitions")}
        value={session.competitions.map((c) => c.name).join(", ")}
      />
      <Fact
        label={t("research.models.session.chosenOn")}
        value={t("research.models.session.seasonOnly", {
          season: seasonLabel(session.validation_season),
        })}
      />
      <Fact
        label={t("research.common.protocol")}
        value={t("research.models.session.protocolValue")}
      />
      <Fact
        label={t("research.common.primaryBaseline")}
        value={baselineLabel(session.primary_baseline)}
      />
    </dl>
  );
}

function BaselineTable({ rows }: { rows: BaselineScore[] }) {
  return (
    <TableShell>
      <THead>
        <TH>{t("research.models.baseline.baseline")}</TH>
        <TH>{t("research.common.market")}</TH>
        <TH>
          <InfoTip
            term="historicalClosing"
            className="text-label font-semibold text-subtle-foreground"
          >
            {t("research.models.baseline.source")}
          </InfoTip>
        </TH>
        <TH align="right">
          <MetricLabel term="sampleSize">{t("research.common.sample")}</MetricLabel>
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
                {b.is_primary ? (
                  <StatusBadge tone="brand">{t("research.models.baseline.primary")}</StatusBadge>
                ) : null}
              </div>
            </TD>
            <TD className="text-xs text-muted-foreground">
              {b.market_key === "OU"
                ? t("research.models.overUnder", { line: Number(b.line) })
                : b.market_key}
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
                reason={t("research.models.baseline.overroundNotStored")}
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
  const noBacktest = t("research.models.noBacktest");
  return (
    <TableShell>
      <THead>
        <TH>{t("research.common.model")}</TH>
        <TH align="right">
          <MetricLabel term="sampleSize">{t("research.common.sample")}</MetricLabel>
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
          <MetricLabel term="vsMarket">{t("research.models.leaderboard.vsMarket")}</MetricLabel>
        </TH>
        <TH>{t("research.common.verdict")}</TH>
        <TH>{t("research.common.version")}</TH>
      </THead>
      <tbody>
        {primary ? (
          <TRow selected>
            <TD>
              <div className="text-sm">{baselineLabel(primary.baseline_key)}</div>
              <div className="text-caption text-subtle-foreground">
                {t("research.models.leaderboard.marketBaseline")}
              </div>
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
              {t("research.models.leaderboard.reference")}
            </TD>
            <TD>
              <StatusBadge tone="brand">{t("research.models.leaderboard.baseline")}</StatusBadge>
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
                <div className="text-sm">{modelLabel(m.name)}</div>
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
                  reason={noBacktest}
                  className="numeric"
                />
              </TD>
              <TD align="right">
                <Nullable value={dec(bt?.logloss, 4)} reason={noBacktest} className="numeric" />
              </TD>
              <TD align="right">
                <Nullable value={dec(bt?.brier, 4)} reason={noBacktest} className="numeric" />
              </TD>
              <TD align="right">
                <Nullable value={dec(bt?.ece, 4)} reason={noBacktest} className="numeric" />
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
                    reason={bt ? t("research.models.leaderboard.noCommon") : noBacktest}
                  />
                )}
              </TD>
              <TD>{bt ? <VerdictBadge c={c} /> : <Nullable value={null} reason={noBacktest} />}</TD>
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

const detailTabs = ["calibration", "leagues", "temporal", "markets", "protocol"] as const;
type DetailTab = (typeof detailTabs)[number];

function detailTabLabel(tab: DetailTab): string {
  switch (tab) {
    case "calibration":
      return t("research.models.detail.tabs.calibration");
    case "leagues":
      return t("research.models.detail.tabs.leagues");
    case "temporal":
      return t("research.models.detail.tabs.temporal");
    case "markets":
      return t("research.common.markets");
    case "protocol":
      return t("research.common.protocol");
  }
}

function ModelDetail({
  models,
  session,
}: {
  models: ModelVersionSummary[];
  session: BacktestSessionSummary | null;
}) {
  const [selected, setSelected] = useState(models[0]?.name ?? "");
  const [tab, setTab] = useState<DetailTab>("calibration");
  const model = models.find((m) => m.name === selected) ?? models[0];
  if (!model?.latest_backtest) return null;
  const bt = model.latest_backtest;
  const names = models.map((m) => m.name);
  return (
    <Panel title={t("research.models.detail.title")} bodyClassName="p-4 space-y-4">
      <SegmentedTabs
        tabs={names}
        value={model.name}
        onChange={setSelected}
        format={(n) => modelLabel(n)}
        label={t("research.common.model")}
      />
      <p className="text-caption text-muted-foreground">{model.description}</p>
      <SegmentedTabs
        tabs={detailTabs}
        value={tab}
        onChange={setTab}
        format={detailTabLabel}
        label={t("research.models.detail.tabsLabel")}
      />
      {tab === "calibration" ? <CalibrationView model={model} /> : null}
      {tab === "leagues" ? (
        <SplitTable rows={bt.by_competition} keyLabel={t("research.common.competition")} />
      ) : null}
      {tab === "temporal" ? <MonthlyView model={model} /> : null}
      {tab === "markets" ? <MarketsView model={model} /> : null}
      {tab === "protocol" ? <ProtocolView model={model} session={session} /> : null}
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
        <div className="h-64 w-full" aria-label={t("research.models.calibration.chartLabel")}>
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
                  value: t("research.models.calibration.axis"),
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
                formatter={(v: number, name: string) => (name === "n" ? int(v) : localPct(v, 1))}
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
          {t("research.models.calibration.note", { ece: dec(bt.ece, 4) ?? "" })}
        </p>
      </div>
      <TableShell compact>
        <THead>
          <TH>{t("research.models.calibration.bin")}</TH>
          <TH align="right">{t("research.models.calibration.predicted")}</TH>
          <TH align="right">{t("research.models.calibration.observed")}</TH>
          <TH align="right">{t("research.common.sample")}</TH>
        </THead>
        <tbody>
          {bt.calibration.map((b) => (
            <TRow key={b.lower}>
              <TD className="numeric text-xs">
                {Math.round(b.lower * 100)}–{Math.round(b.upper * 100)}%
              </TD>
              <TD align="right">
                <Nullable
                  value={b.mean_predicted === null ? null : localPct(b.mean_predicted, 1)}
                  reason={t("research.models.calibration.emptyBin")}
                  className="numeric"
                />
              </TD>
              <TD align="right">
                <Nullable
                  value={b.observed_rate === null ? null : localPct(b.observed_rate, 1)}
                  reason={t("research.models.calibration.emptyBin")}
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
    return <StatusNotice status="empty" reason={t("research.models.split.empty")} compact />;
  }
  return (
    <TableShell>
      <THead>
        <TH>{keyLabel}</TH>
        <TH align="right">{t("research.common.fixtures")}</TH>
        <TH align="right">{t("research.models.split.modelLogLoss")}</TH>
        <TH align="right">{t("research.models.split.marketLogLoss")}</TH>
        <TH align="right">
          <MetricLabel term="vsMarket">{t("research.models.split.difference")}</MetricLabel>
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
              <Numeric>{localFixed(r.model_logloss, 4)}</Numeric>
            </TD>
            <TD align="right">
              <Numeric muted>{localFixed(r.baseline_logloss, 4)}</Numeric>
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
      <div className="h-52 w-full" aria-label={t("research.models.monthly.chartLabel")}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 8, left: 4 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="2 4" />
            <XAxis dataKey="month" stroke="var(--subtle-foreground)" fontSize={11} />
            <YAxis
              stroke="var(--subtle-foreground)"
              fontSize={11}
              tickFormatter={(v: number) => localFixed(v, 2)}
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
              name={t("research.models.monthly.series")}
              stroke="var(--primary)"
              dot={{ r: 2 }}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <p className="text-caption text-muted-foreground">{t("research.models.monthly.note")}</p>
      <SplitTable rows={rows} keyLabel={t("research.models.monthly.month")} />
    </div>
  );
}

function ComparisonRows({ rows }: { rows: MarketComparison[] }) {
  return (
    <TableShell>
      <THead>
        <TH>{t("research.models.comparison.against")}</TH>
        <TH align="right">{t("research.models.comparison.commonFixtures")}</TH>
        <TH align="right">{t("research.common.model")}</TH>
        <TH align="right">{t("research.common.market")}</TH>
        <TH align="right">
          <MetricLabel term="vsMarket">Δ log loss [95%]</MetricLabel>
        </TH>
        <TH align="right">Δ Brier</TH>
        <TH>{t("research.common.verdict")}</TH>
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
        <div className="mb-2 text-label text-subtle-foreground">
          {t("research.models.overUnder", { line: "2.5" })}
        </div>
        {ou.length ? (
          <ComparisonRows rows={ou} />
        ) : (
          <StatusNotice
            status="not_available"
            reason={
              ONE_X_TWO_ONLY.has(model.name)
                ? t("research.models.markets.oneXTwoOnly", { model: modelLabel(model.name) })
                : t("research.models.markets.noOverUnder")
            }
            compact
          />
        )}
      </div>
      <div>
        <div className="mb-2 text-label text-subtle-foreground">
          {t("research.models.markets.btts")}
        </div>
        {bt.btts ? (
          <div className="grid gap-x-8 sm:grid-cols-2 xl:grid-cols-4">
            <KeyValue label={t("research.common.fixtures")} value={int(bt.btts.n)} />
            <KeyValue label="Log loss" value={localFixed(bt.btts.log_loss, 4)} />
            <KeyValue label="Brier" value={localFixed(bt.btts.brier, 4)} />
            <KeyValue label="ECE" value={localFixed(bt.btts.ece, 4)} />
          </div>
        ) : null}
        <p className="mt-2 text-caption text-muted-foreground">
          {bt.btts
            ? t("research.models.markets.bttsNoBaseline")
            : t("research.models.markets.noBtts")}
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
        <div className="mb-1 text-label text-subtle-foreground">
          {t("research.models.protocol.lineage")}
        </div>
        <KeyValue label={t("research.models.protocol.modelVersion")} value={model.version} />
        <KeyValue label={t("research.common.codeVersion")} value={shortHash(bt.code_version)} />
        <KeyValue label={t("research.models.protocol.backtestRun")} value={`#${bt.run_id}`} />
        <KeyValue
          label={t("research.common.session")}
          value={session ? shortHash(session.session_uuid, 8) : "—"}
        />
        <KeyValue
          label={t("research.common.datasetHash")}
          value={session ? shortHash(session.dataset_hash) : "—"}
        />
        <KeyValue
          label={t("research.models.protocol.trainedOn")}
          value={t("research.models.protocol.trainedRange", {
            count: model.n_train,
            from: utcDate(model.train_from),
            to: utcDate(model.train_to),
            n: int(model.n_train),
          })}
        />
        <KeyValue label={t("research.common.finished")} value={utcDateTime(bt.finished_at)} />
        <KeyValue
          label={t("research.models.protocol.accuracy")}
          value={`${localFixed(Number(bt.accuracy_pct), 1)}%`}
        />
      </div>
      <div>
        <div className="mb-1 text-label text-subtle-foreground">
          {t("research.models.protocol.coverage")}
        </div>
        {bt.coverage ? (
          <>
            <KeyValue
              label={t("research.models.protocol.predicted")}
              value={t("research.models.protocol.predictedValue", {
                predicted: int(bt.coverage.predicted),
                targets: int(bt.coverage.targets),
              })}
            />
            <KeyValue label={t("research.models.protocol.refits")} value={int(bt.coverage.fits)} />
            <KeyValue
              label={t("research.models.protocol.failedFits")}
              value={int(bt.coverage.failed_fits)}
            />
            <KeyValue
              label={t("research.models.protocol.noInterval")}
              value={int(bt.coverage.no_interval)}
            />
            {uncovered.map(([why, n]) => (
              <KeyValue
                key={why}
                label={t("research.models.protocol.notPredicted", { n: int(n) })}
                value={why}
              />
            ))}
          </>
        ) : (
          <StatusNotice
            status="not_available"
            reason={t("research.models.protocol.noCoverage")}
            compact
          />
        )}
        {selection ? (
          <div className="mt-4">
            <div className="mb-1 text-label text-subtle-foreground">
              {t("research.models.protocol.chosenOn", {
                season: seasonLabel(selection.validation_season ?? session?.validation_season),
              })}
            </div>
            <KeyValue
              label={t("research.models.protocol.timeDecay")}
              value={String(selection.chosen.xi)}
            />
            <KeyValue
              label={t("research.models.protocol.shrinkage")}
              value={String(selection.chosen.penalty)}
            />
            <KeyValue
              label={t("research.models.protocol.candidates")}
              value={
                selection.validation_logloss
                  ? t("research.models.protocol.candidatesValue", {
                      n: Object.keys(selection.validation_logloss).length,
                    })
                  : t("research.models.protocol.notStored")
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
    return <StatusNotice status="not_available" reason={t("research.models.betting.empty")} />;
  }
  const rule = rows[0]!.latest_backtest!.betting!.rule;
  const source = rows[0]!.latest_backtest!.betting!.odds_source;
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2.5 text-caption text-muted-foreground">
        <StatusBadge tone="warning">{t("research.models.betting.hypothetical")}</StatusBadge>
        <InfoTip term="hypotheticalBetting" className="text-caption">
          <span>{t("research.models.betting.simulation", { rule, source })}</span>
        </InfoTip>
      </div>
      <TableShell>
        <THead>
          <TH>{t("research.common.model")}</TH>
          <TH align="right">{t("research.models.betting.fixturesPriced")}</TH>
          <TH align="right">{t("research.models.betting.bets")}</TH>
          <TH align="right">{t("research.models.betting.profit")}</TH>
          <TH align="right">
            <MetricLabel term="roi">ROI</MetricLabel>
          </TH>
          <TH align="right">{t("research.models.betting.interval")}</TH>
          <TH align="right">
            <MetricLabel term="drawdown">{t("research.models.betting.drawdown")}</MetricLabel>
          </TH>
        </THead>
        <tbody>
          {rows.map((m) => {
            const b = m.latest_backtest!.betting!;
            const roi = b.roi_pct === null ? null : Number(b.roi_pct);
            return (
              <TRow key={m.version_id}>
                <TD className="text-sm">{modelLabel(m.name)}</TD>
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
                    reason={t("research.models.betting.noBetMetRule")}
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
                    reason={t("research.models.betting.fewBets")}
                    className="numeric text-muted-foreground"
                  />
                </TD>
                <TD align="right">
                  <Nullable
                    value={dec(b.max_drawdown_units, 1)}
                    reason={t("research.models.betting.noBets")}
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
  if (!q.data || !d) {
    return <span className="text-subtle-foreground">{t("research.models.shadow.loading")}</span>;
  }
  if (q.data.status !== "ok" || d.roi_pct === null) {
    return (
      <span>
        <span className="text-label text-subtle-foreground">
          {t("research.models.shadow.label")}
        </span>{" "}
        — {t("research.models.shadow.unavailable", { reason: q.data.reason ?? d.note })}
      </span>
    );
  }
  const roi = Number(d.roi_pct);
  return (
    <span>
      <span className="text-label text-subtle-foreground">{t("research.models.shadow.label")}</span>{" "}
      — {t("research.models.shadow.settled", { count: d.settled })}{" "}
      <span className={roi > 0 ? "text-positive" : "text-negative"}>
        {localDecimalText(d.roi_pct)}%
      </span>
      ,{" "}
      {t("research.models.shadow.hitRate", {
        hitRate: d.hit_rate === null ? "" : localDecimalText(d.hit_rate),
      })}
    </span>
  );
}
