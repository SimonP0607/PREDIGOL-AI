/**
 * Resource layer. Thin, typed facade over the active DataProvider so that
 * pages never import the mock modules directly.
 */
import { dataProvider } from "./provider";
import type { BacktestConfig } from "@/types/domain";

export const api = dataProvider;

export const queries = {
  health: { queryKey: ["health"], queryFn: () => api.getHealth() },
  matches: { queryKey: ["matches"], queryFn: () => api.getMatches() },
  picks: { queryKey: ["picks"], queryFn: () => api.getPicks() },
  models: { queryKey: ["models"], queryFn: () => api.getModels() },
  performance: { queryKey: ["performance"], queryFn: () => api.getPerformance() },
  performanceCharts: {
    queryKey: ["performance", "charts"],
    queryFn: () => api.getPerformanceCharts(),
  },
  dataQuality: { queryKey: ["data-quality"], queryFn: () => api.getDataQuality() },
  coverage: { queryKey: ["data-quality", "coverage"], queryFn: () => api.getCoverage() },
  issues: { queryKey: ["data-quality", "issues"], queryFn: () => api.getDataIssues() },
  lineage: { queryKey: ["data-quality", "lineage"], queryFn: () => api.getLineage() },
  valueScanner: { queryKey: ["odds", "value-scanner"], queryFn: () => api.getValueScanner() },
  nearClose: { queryKey: ["odds", "near-close"], queryFn: () => api.getNearCloseSnapshots() },
  analyst: { queryKey: ["analyst"], queryFn: () => api.getAnalystAnswers() },
} as const;

export const fixtureQueries = {
  match: (id: string) => ({ queryKey: ["match", id], queryFn: () => api.getMatch(id) }),
  markets: (id: string) => ({
    queryKey: ["match", id, "markets"],
    queryFn: () => api.getMatchMarkets(id),
  }),
  prediction: (id: string) => ({
    queryKey: ["match", id, "prediction"],
    queryFn: () => api.getMatchPrediction(id),
  }),
  oddsSnapshot: (id: string) => ({
    queryKey: ["match", id, "odds-snapshot"],
    queryFn: () => api.getMatchOddsSnapshot(id),
  }),
  ratings: (id: string) => ({
    queryKey: ["match", id, "ratings"],
    queryFn: () => api.getMatchRatings(id),
  }),
  timeline: (id: string) => ({
    queryKey: ["match", id, "timeline"],
    queryFn: () => api.getMatchTimeline(id),
  }),
  modelComparison: (id: string) => ({
    queryKey: ["match", id, "model-comparison"],
    queryFn: () => api.getMatchModelComparison(id),
  }),
  oddsBoard: (id: string) => ({
    queryKey: ["match", id, "odds-board"],
    queryFn: () => api.getOddsBoard(id),
  }),
  consensus: (id: string) => ({
    queryKey: ["match", id, "consensus"],
    queryFn: () => api.getOddsConsensus(id),
  }),
  movement: (id: string) => ({
    queryKey: ["match", id, "movement"],
    queryFn: () => api.getLineMovement(id),
  }),
};

export const modelQueries = {
  calibration: (id: string) => ({
    queryKey: ["models", id, "calibration"],
    queryFn: () => api.getCalibration(id),
  }),
};

export const backtestQuery = (config: BacktestConfig, enabled: boolean) => ({
  queryKey: ["backtest", config],
  queryFn: () => api.runBacktest(config),
  enabled,
});
