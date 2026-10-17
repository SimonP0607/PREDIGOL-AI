/**
 * DEMO DATA — research layer: model comparison, backtests, performance shapes,
 * search index and analyst answers. No result here is a real measurement.
 */
import type {
  AnalystAnswer,
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

const day = "2026-09-04";

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

export const suggestedQueries = [
  "Why does this candidate have positive EV?",
  "Compare Poisson vs market baseline.",
  "Which competitions have poor data coverage?",
  "Show models with worsening calibration.",
  "Find matches with strong model-market disagreement.",
];

export const analystAnswers: AnalystAnswer[] = [
  {
    id: "ans-ev",
    question: "Why does this candidate have positive EV?",
    answer:
      "The candidate Brentford vs Newcastle · Over 2.5 shows positive expected value because the model probability (54.8%) exceeds the overround-removed consensus (52.1%) while the best available price (1.95 at Book D) is above the fair price implied by the model (1.82). Expected value is the product of model probability and available price minus one; it is not a claim about profitability and the model producing it is in shadow status.",
    evidence: [
      "Model probability 54.8% comes from Poisson v0.4.2-rc1 on feature snapshot feat-2026.08.3.",
      "Market probability 52.1% is derived from 14 bookmakers after overround removal.",
      "Best price 1.95 was captured at 12:03 UTC and is 7.1% above the fair price.",
      "Sample for this model is 6,320 scored fixtures, below the validation threshold.",
    ],
    metrics: [
      { label: "Model probability", value: "54.8%", source: "prediction pred_01J9F3K2QF8N" },
      { label: "Market probability", value: "52.1%", source: "odds snapshot odds_snap_44812" },
      { label: "Edge", value: "+2.70%", source: "derived" },
      { label: "Expected value", value: "+6.86%", source: "derived" },
    ],
    relatedFixtures: [{ id: "fx-10241", label: "Brentford vs Newcastle" }],
    relatedModels: [{ id: "poisson", label: "Poisson (bivariate)" }],
    sources: [
      {
        label: "Prediction pred_01J9F3K2QF8N",
        kind: "model",
        reference: "poisson v0.4.2-rc1",
        capturedAt: `${day}T12:04:11Z`,
        fixtureId: "fx-10241",
      },
      {
        label: "Odds snapshot odds_snap_44812",
        kind: "odds",
        reference: "14 bookmakers · overround 1.043",
        capturedAt: `${day}T12:03:50Z`,
        fixtureId: "fx-10241",
      },
    ],
    generatedAt: `${day}T12:10:00Z`,
  },
  {
    id: "ans-poisson",
    question: "Compare Poisson vs market baseline.",
    answer:
      "On the current evaluation window the market baseline is still ahead. Poisson scores a Brier of 0.2074 against 0.2012 for the baseline, and log loss 0.9903 against 0.9741. Calibration error is 1.48% versus 0.61%. Poisson has not beaten the reference on any competition split, so it remains in shadow status.",
    evidence: [
      "Poisson sample: 6,320 scored fixtures. Baseline sample: 12,480.",
      "Difference versus market on Brier: -0.62% (worse).",
      "No economic evaluation exists: historical prices per selection are not reconstructed.",
    ],
    metrics: [
      { label: "Brier (Poisson)", value: "0.2074", source: "model evaluation 2026-09-03" },
      { label: "Brier (baseline)", value: "0.2012", source: "model evaluation 2026-09-03" },
      { label: "Calibration error", value: "1.48%", source: "calibration bins" },
      { label: "ROI", value: "—", source: "no validated economic history" },
    ],
    relatedFixtures: [],
    relatedModels: [
      { id: "poisson", label: "Poisson (bivariate)" },
      { id: "market-baseline", label: "Market Baseline" },
    ],
    sources: [
      {
        label: "Model evaluation run",
        kind: "model",
        reference: "eval_2026_09_03",
        capturedAt: "2026-09-03T22:10:00Z",
        fixtureId: null,
      },
    ],
    generatedAt: `${day}T12:11:00Z`,
  },
  {
    id: "ans-coverage",
    question: "Which competitions have poor data coverage?",
    answer:
      "Ligue 1 is the worst partition: odds coverage 33%, markets coverage 34%, 3 bookmakers, and the last successful capture was at 09:12 UTC — beyond the stale threshold, caused by a failed odds sweep. Serie A is degraded at 67% odds coverage with 6 bookmakers and an aging capture. Every other tracked competition is healthy.",
    evidence: [
      "Ligue 1 odds sweep aborted after 3 provider rate-limit responses.",
      "Serie A is missing 2 fixtures relative to the competition calendar.",
      "Analytical layer partition for Ligue 1 has not been refreshed since 09:12 UTC.",
    ],
    metrics: [
      { label: "Ligue 1 odds coverage", value: "33.0%", source: "coverage table" },
      { label: "Serie A odds coverage", value: "67.0%", source: "coverage table" },
      { label: "Failed jobs", value: "1", source: "data quality" },
    ],
    relatedFixtures: [{ id: "fx-10245", label: "Lille vs Rennes" }],
    relatedModels: [],
    sources: [
      {
        label: "Coverage snapshot",
        kind: "data-quality",
        reference: "coverage_2026_09_04",
        capturedAt: `${day}T12:03:00Z`,
        fixtureId: null,
      },
    ],
    generatedAt: `${day}T12:12:00Z`,
  },
  {
    id: "ans-calibration",
    question: "Show models with worsening calibration.",
    answer:
      "Dixon-Coles has the highest calibration error at 3.34% on a sample of 1,980 fixtures, which is too small to separate drift from noise. Elo sits at 2.12% and has degraded in the long-odds region. Poisson is the closest shadow model to the baseline at 1.48%. Logistic Regression, Gradient Boosting and the Ensemble are not trained, so no calibration exists.",
    evidence: [
      "Calibration is measured as mean absolute gap between predicted probability and observed frequency per decile.",
      "Long-odds deciles carry the largest gaps for every goal-process model.",
      "No model has crossed the validation gate.",
    ],
    metrics: [
      { label: "Dixon-Coles calibration error", value: "3.34%", source: "model evaluation" },
      { label: "Elo calibration error", value: "2.12%", source: "model evaluation" },
      { label: "Poisson calibration error", value: "1.48%", source: "model evaluation" },
    ],
    relatedFixtures: [],
    relatedModels: [
      { id: "dixon-coles", label: "Dixon-Coles" },
      { id: "elo", label: "Elo" },
    ],
    sources: [
      {
        label: "Calibration bins",
        kind: "model",
        reference: "eval_2026_09_03",
        capturedAt: "2026-09-03T22:10:00Z",
        fixtureId: null,
      },
    ],
    generatedAt: `${day}T12:13:00Z`,
  },
  {
    id: "ans-disagreement",
    question: "Find matches with strong model-market disagreement.",
    answer:
      "Three fixtures show a model-market gap above 2 percentage points on the tracked markets: Brentford vs Newcastle (Over 2.5, +2.70%), Real Betis vs Osasuna (BTTS Yes, +2.60%) and Atalanta vs Torino (Away, +2.40%). The Atalanta fixture should be treated with caution: market coverage is 61%, the capture is stale and the producing model is in research status.",
    evidence: [
      "Disagreement is computed against the overround-removed consensus, not against a single bookmaker.",
      "Atalanta vs Torino has only 6 tracked bookmakers.",
      "None of these fixtures has a near-close snapshot yet.",
    ],
    metrics: [
      { label: "Largest gap", value: "+2.70%", source: "value scanner" },
      { label: "Fixtures above threshold", value: "3", source: "value scanner" },
    ],
    relatedFixtures: [
      { id: "fx-10241", label: "Brentford vs Newcastle" },
      { id: "fx-10242", label: "Real Betis vs Osasuna" },
      { id: "fx-10243", label: "Atalanta vs Torino" },
    ],
    relatedModels: [{ id: "poisson", label: "Poisson (bivariate)" }],
    sources: [
      {
        label: "Value scanner sweep",
        kind: "odds",
        reference: "scan_2026_09_04_1203",
        capturedAt: `${day}T12:03:00Z`,
        fixtureId: null,
      },
    ],
    generatedAt: `${day}T12:14:00Z`,
  },
];
