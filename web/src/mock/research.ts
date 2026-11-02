/**
 * DEMO DATA — research layer: model comparison, backtests, performance shapes,
 * search index. No result here is a real measurement.
 */
import type {
  BacktestConfig,
  BacktestResult,
  BreakdownRow,
  CalibrationBin,
  ModelComparisonRow,
  PerformanceCharts,
  SearchHit,
  SeriesPoint,
} from "@/types/domain";
import { competitions, fixtures, models, teams, calibrationBins } from "./data";

export function modelComparison(fixtureId: string): ModelComparisonRow[] {
  const skew = fixtureId.charCodeAt(fixtureId.length - 1) % 5;
  const s = skew * 0.004;
  return [
    {
      modelId: "market-baseline",
      model: "Market Baseline",
      version: "v1.0.0",
      status: "market_baseline",
      home: 0.351,
      draw: 0.264,
      away: 0.385,
      brier: 0.2012,
    },
    {
      modelId: "poisson",
      model: "Poisson (bivariate)",
      version: "v0.4.2-rc1",
      status: "shadow",
      home: Number((0.372 + s).toFixed(3)),
      draw: 0.259,
      away: Number((0.369 - s).toFixed(3)),
      brier: 0.2074,
    },
    {
      modelId: "elo",
      model: "Elo",
      version: "v0.3.1",
      status: "shadow",
      home: Number((0.344 + s).toFixed(3)),
      draw: 0.271,
      away: Number((0.385 - s).toFixed(3)),
      brier: 0.2189,
    },
    {
      modelId: "dixon-coles",
      model: "Dixon-Coles",
      version: "v0.2.0",
      status: "research",
      home: Number((0.361 + s).toFixed(3)),
      draw: 0.283,
      away: Number((0.356 - s).toFixed(3)),
      brier: 0.2231,
    },
    {
      modelId: "logreg",
      model: "Logistic Regression",
      version: "—",
      status: "not_trained",
      home: null,
      draw: null,
      away: null,
      brier: null,
    },
  ];
}

const months = [
  "2025-10",
  "2025-11",
  "2025-12",
  "2026-01",
  "2026-02",
  "2026-03",
  "2026-04",
  "2026-05",
];

const equitySeed = [0, 1.4, 0.6, 2.1, 1.2, 2.8, 2.2, 3.4, 2.9, 4.1, 3.6, 4.8];
const equity: SeriesPoint[] = equitySeed.map((v, i) => ({
  at: `2026-0${Math.min(9, Math.floor(i / 2) + 1)}-${String((i % 2) * 14 + 1).padStart(2, "0")}`,
  value: v,
}));
const drawdownSeries: SeriesPoint[] = equitySeed.map((v, i) => {
  const peak = Math.max(...equitySeed.slice(0, i + 1));
  return { at: equity[i]!.at, value: Number((v - peak).toFixed(2)) };
});

const leagueSplit: BreakdownRow[] = [
  { key: "epl", label: "Premier League", sample: 2140, brier: 0.2031, roi: null },
  { key: "laliga", label: "LaLiga", sample: 1880, brier: 0.2088, roi: null },
  { key: "seriea", label: "Serie A", sample: 1620, brier: 0.2117, roi: null },
  { key: "bundesliga", label: "Bundesliga", sample: 1490, brier: 0.2064, roi: null },
  { key: "ligue1", label: "Ligue 1", sample: 980, brier: 0.2192, roi: null },
  { key: "eredivisie", label: "Eredivisie", sample: 610, brier: 0.2241, roi: null },
];

const marketSplit: BreakdownRow[] = [
  { key: "1x2", label: "1X2", sample: 6320, brier: 0.2074, roi: null },
  { key: "ou_2_5", label: "Over / Under 2.5", sample: 4180, brier: 0.2216, roi: null },
  { key: "btts", label: "BTTS", sample: 3940, brier: 0.2288, roi: null },
  { key: "double_chance", label: "Double Chance", sample: 2110, brier: 0.1743, roi: null },
];

export const performanceCharts: PerformanceCharts = {
  demo: true,
  equity,
  drawdown: drawdownSeries,
  monthly: months.map((month, i) => ({
    month,
    value: Number(((i % 3) - 1 + (i % 2) * 0.6).toFixed(2)),
  })),
  marketBreakdown: marketSplit,
  leagueBreakdown: leagueSplit,
};

export const defaultBacktestConfig: BacktestConfig = {
  modelId: "poisson",
  modelVersion: "v0.4.2-rc1",
  competitionId: "all",
  season: "2025/26",
  market: "1x2",
  from: "2025-08-01",
  to: "2026-05-31",
  oddsSource: "consensus",
  stakeStrategy: "flat",
  minimumEdge: 0.02,
};

const buckets: CalibrationBin[] = calibrationBins;

/**
 * Economic evaluation is only available when historical odds exist for the
 * selected window. Any other configuration returns predictive metrics only.
 */
export function runBacktest(config: BacktestConfig): BacktestResult {
  const oddsHistory = config.oddsSource === "consensus" && config.competitionId !== "ligue1";
  const model = models.find((m) => m.id === config.modelId);
  const trained = model?.sample != null;
  return {
    economicAvailable: false,
    sampleSize: trained ? (model?.sample ?? 0) : 0,
    brier: trained ? (model?.brier ?? null) : null,
    logLoss: trained ? (model?.logLoss ?? null) : null,
    calibrationError: trained ? (model?.calibrationError ?? null) : null,
    roi: null,
    yieldPct: null,
    drawdown: null,
    lineValue: null,
    equity,
    drawdownSeries,
    monthly: months.map((month, i) => ({
      month,
      sample: 420 + i * 37,
      brier: Number((0.2 + (i % 4) * 0.006).toFixed(4)),
    })),
    leagueSplit,
    marketSplit,
    buckets,
    note: trained
      ? oddsHistory
        ? "Economic backtest unavailable for this dataset. Predictive evaluation only: historical prices are not yet reconstructed per selection."
        : "Odds history unavailable for the selected source. Economic backtest unavailable for this dataset. Predictive evaluation only."
      : "This model has not been trained. No predictive or economic evaluation is available.",
  };
}

export const searchIndex: SearchHit[] = [
  ...fixtures.map<SearchHit>((f) => ({
    id: f.id,
    type: "fixture",
    label: `${f.home.name} vs ${f.away.name}`,
    sublabel: `${f.competition.name} · ${f.round}`,
    fixtureId: f.id,
  })),
  ...teams.map<SearchHit>((t) => ({
    id: `team-${t.id}`,
    type: "team",
    label: t.name,
    sublabel: competitions.find((c) => c.id === t.competitionId)?.name ?? "Unknown competition",
    fixtureId: fixtures.find((f) => f.home.id === t.id || f.away.id === t.id)?.id ?? null,
  })),
  ...competitions.map<SearchHit>((c) => ({
    id: `comp-${c.id}`,
    type: "competition",
    label: c.name,
    sublabel: `${c.country} · tier ${c.tier}`,
    fixtureId: null,
  })),
  ...models.map<SearchHit>((m) => ({
    id: `model-${m.id}`,
    type: "model",
    label: m.name,
    sublabel: `${m.family} · ${m.version}`,
    fixtureId: null,
  })),
];
