/**
 * Demo data provider contract.
 *
 * The demo pages talk to a `DataProvider` backed by src/mock. Live pages do
 * not use it: they read the FastAPI contracts through src/lib/api/v1.
 */
import type {
  AnalystAnswer,
  BacktestConfig,
  BacktestResult,
  BookmakerPrice,
  CalibrationBin,
  ConsensusRow,
  CoverageRow,
  DataIssue,
  DataQualityStatus,
  Fixture,
  LineMovementSeries,
  LineageNode,
  MarketProbability,
  ModelComparisonRow,
  ModelSummary,
  NearCloseRow,
  OddsSnapshot,
  PerformanceCharts,
  PerformanceSummary,
  PickCandidate,
  Prediction,
  SearchHit,
  SystemHealth,
  TeamRatings,
  TimelineEvent,
  ValueRow,
} from "@/types/domain";
import * as mock from "@/mock/data";
import * as market from "@/mock/market";
import * as ops from "@/mock/operations";
import * as research from "@/mock/research";
import { demo } from "./client";

export interface DataProvider {
  readonly mode: "demo";

  getHealth(): Promise<SystemHealth[]>;
  getMatches(): Promise<Fixture[]>;
  getMatch(id: string): Promise<Fixture | undefined>;
  getMatchMarkets(id: string): Promise<MarketProbability[]>;
  getMatchPrediction(id: string): Promise<Prediction>;
  getMatchOddsSnapshot(id: string): Promise<OddsSnapshot>;
  getMatchRatings(id: string): Promise<{ home: TeamRatings; away: TeamRatings }>;
  getMatchTimeline(id: string): Promise<TimelineEvent[]>;
  getMatchModelComparison(id: string): Promise<ModelComparisonRow[]>;

  getPicks(): Promise<PickCandidate[]>;
  getModels(): Promise<ModelSummary[]>;
  getCalibration(modelId: string): Promise<CalibrationBin[]>;

  getOddsBoard(fixtureId: string): Promise<BookmakerPrice[]>;
  getOddsConsensus(fixtureId: string): Promise<ConsensusRow[]>;
  getLineMovement(fixtureId: string): Promise<LineMovementSeries[]>;
  getValueScanner(): Promise<ValueRow[]>;
  getNearCloseSnapshots(): Promise<NearCloseRow[]>;

  getPerformance(): Promise<PerformanceSummary>;
  getPerformanceCharts(): Promise<PerformanceCharts>;
  runBacktest(config: BacktestConfig): Promise<BacktestResult>;

  getDataQuality(): Promise<DataQualityStatus[]>;
  getCoverage(): Promise<CoverageRow[]>;
  getDataIssues(): Promise<DataIssue[]>;
  getLineage(): Promise<LineageNode[]>;

  search(term: string): Promise<SearchHit[]>;
  getAnalystAnswers(): Promise<AnalystAnswer[]>;
}

function matchesTerm(hit: SearchHit, term: string): boolean {
  const q = term.trim().toLowerCase();
  if (!q) return false;
  return hit.label.toLowerCase().includes(q) || hit.sublabel.toLowerCase().includes(q);
}

export const mockProvider: DataProvider = {
  mode: "demo",

  getHealth: () => demo(mock.systemHealth),
  getMatches: () => demo(mock.fixtures),
  getMatch: (id) => demo(mock.fixtures.find((f) => f.id === id)),
  getMatchMarkets: (id) => demo(mock.marketsForFixture(id)),
  getMatchPrediction: (id) => demo(mock.predictionForFixture(id)),
  getMatchOddsSnapshot: () => demo(mock.oddsSnapshot),
  getMatchRatings: () => demo({ home: mock.teamRatings["home"]!, away: mock.teamRatings["away"]! }),
  getMatchTimeline: (id) => demo(ops.fixtureTimeline(id)),
  getMatchModelComparison: (id) => demo(research.modelComparison(id)),

  getPicks: () => demo(mock.picks),
  getModels: () => demo(mock.models),
  getCalibration: () => demo(mock.calibrationBins),

  getOddsBoard: (fixtureId) => demo(market.oddsBoard(fixtureId)),
  getOddsConsensus: (fixtureId) => demo(market.consensus(fixtureId)),
  getLineMovement: (fixtureId) => demo(market.lineMovement(fixtureId)),
  getValueScanner: () => demo(market.valueRows),
  getNearCloseSnapshots: () => demo(market.nearCloseRows),

  getPerformance: () => demo(mock.performance),
  getPerformanceCharts: () => demo(research.performanceCharts),
  runBacktest: (config) => demo(research.runBacktest(config), 450),

  getDataQuality: () => demo(mock.dataQuality),
  getCoverage: () => demo(ops.coverage),
  getDataIssues: () => demo(ops.issues),
  getLineage: () => demo(ops.lineage),

  search: (term) => demo(research.searchIndex.filter((h) => matchesTerm(h, term)).slice(0, 12), 40),
  getAnalystAnswers: () => demo(research.analystAnswers),
};

/**
 * The demo adapter. It is only ever rendered inside a DemoRegion, so a page
 * that shows it is labelled DEMO (or HYBRID) by construction.
 */
export const dataProvider: DataProvider = mockProvider;
