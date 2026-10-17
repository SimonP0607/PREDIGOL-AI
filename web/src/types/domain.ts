/**
 * Domain types for the Football Intelligence Platform.
 * These mirror the future FastAPI contracts. Never widen to `any`.
 */

export type DataState = "healthy" | "warning" | "stale" | "failed" | "unknown";

export type FixtureStatus = "upcoming" | "live" | "finished" | "postponed";

export type ModelStatus =
  "market_baseline" | "validated" | "shadow" | "research" | "insufficient_data" | "not_trained";

export type PickStatus =
  "candidate" | "shadow" | "qualified" | "published" | "settled" | "rejected";

export type MarketKey = "1x2" | "ou_2_5" | "btts" | "double_chance";

export interface Competition {
  id: string;
  name: string;
  country: string;
  shortCode: string;
  tier: number;
}

export interface Team {
  id: string;
  name: string;
  shortName: string;
  code: string;
  competitionId: string;
}

export interface TeamRatings {
  elo: number;
  attackRating: number;
  defenseRating: number;
  homeAwayStrength: number;
  goalsFor: number;
  goalsAgainst: number;
  scheduleStrength: number;
  form: Array<"W" | "D" | "L">;
  xg: number | null;
}

export interface Fixture {
  id: string;
  competition: Competition;
  round: string;
  kickoff: string;
  status: FixtureStatus;
  home: Team;
  away: Team;
  modelStatus: ModelStatus;
  oddsState: DataState;
  marketCoverage: number;
  bookmakerCount: number;
  dataQuality: DataState;
}

export interface MarketProbability {
  market: MarketKey;
  marketLabel: string;
  selection: string;
  modelProbability: number | null;
  marketProbability: number | null;
  fairOdds: number | null;
  bestOdds: number | null;
  bookmaker: string | null;
  edge: number | null;
  ev: number | null;
}

export interface OddsSnapshot {
  id: string;
  capturedAt: string;
  bookmakerCount: number;
  overround: number;
  nearClose: boolean;
}

export interface Prediction {
  id: string;
  fixtureId: string;
  model: string;
  modelVersion: string;
  featureVersion: string;
  calibrator: string;
  dataCutoff: string;
  createdAt: string;
  rawPayloadHash: string;
  gitSha: string;
  oddsSnapshotId: string;
  probabilities: { home: number; draw: number; away: number };
  marketProbabilities: { home: number; draw: number; away: number };
}

export interface ModelSummary {
  id: string;
  name: string;
  family: string;
  version: string;
  status: ModelStatus;
  sample: number | null;
  brier: number | null;
  logLoss: number | null;
  calibrationError: number | null;
  vsMarket: number | null;
  roi: number | null;
  lineValue: number | null;
  lastEvaluation: string | null;
  description: string;
}

export interface PickCandidate {
  id: string;
  fixtureId: string;
  fixtureLabel: string;
  competition: string;
  kickoff: string;
  market: MarketKey;
  marketLabel: string;
  selection: string;
  modelProbability: number;
  marketProbability: number;
  fairOdds: number;
  bestOdds: number;
  bookmaker: string;
  edge: number;
  ev: number;
  reliability: "low" | "medium" | "high" | "unknown";
  status: PickStatus;
  createdAt: string;
  model: string;
  modelVersion: string;
  dataCutoff: string;
  oddsCapturedAt: string;
  dataQuality: DataState;
  rationale: string;
  risks: string[];
}

export interface PerformanceSummary {
  pnl: number | null;
  roi: number | null;
  yield: number | null;
  lineValue: number | null;
  hitRate: number | null;
  drawdown: number | null;
  bankroll: number | null;
  sampleSize: number;
  publishedPicks: number;
  note: string;
}

export interface DataQualityStatus {
  key: string;
  label: string;
  value: string;
  state: DataState;
  detail: string;
}

export interface SystemHealth {
  component: string;
  state: DataState;
  detail: string;
  value: string;
}

export interface CalibrationBin {
  predicted: number;
  observed: number;
  sample: number;
}

/* ---------------------------------------------------------------------------
 * V0.2 — market intelligence, data operations and research types.
 * ------------------------------------------------------------------------ */

/** Consistent freshness vocabulary used across every surface. */
export type Freshness = "live" | "fresh" | "aging" | "stale" | "unknown";

export interface BookmakerPrice {
  bookmaker: string;
  market: MarketKey;
  marketLabel: string;
  selection: string;
  odds: number;
  /** Raw implied probability (1/odds). NOT de-vigged. */
  impliedProbability: number;
  capturedAt: string;
  freshness: Freshness;
}

export interface ConsensusRow {
  market: MarketKey;
  marketLabel: string;
  selection: string;
  /** Overround-removed consensus probability. */
  marketProbability: number;
  bestOdds: number;
  bestBookmaker: string;
  medianOdds: number;
  bookmakerCount: number;
  overround: number;
  capturedAt: string;
  freshness: Freshness;
}

export interface LineMovementSeries {
  bookmaker: string;
  points: Array<{ at: string; odds: number }>;
}

export interface ValueRow {
  id: string;
  fixtureId: string;
  fixtureLabel: string;
  competition: string;
  competitionCode: string;
  kickoff: string;
  market: MarketKey;
  marketLabel: string;
  selection: string;
  modelProbability: number;
  marketProbability: number;
  fairOdds: number;
  bestOdds: number;
  bookmaker: string;
  edge: number;
  ev: number;
  freshness: Freshness;
}

export interface NearCloseRow {
  fixtureId: string;
  fixtureLabel: string;
  market: MarketKey;
  marketLabel: string;
  selection: string;
  capturedAt: string;
  minutesToKickoff: number;
  snapshotOdds: number;
  latestOdds: number;
  /** Difference between snapshot and latest capture. Not a closing-line claim. */
  delta: number;
  validated: boolean;
}

export interface CoverageRow {
  competitionId: string;
  competition: string;
  code: string;
  fixtures: number;
  oddsCoverage: number;
  marketsCoverage: number;
  bookmakers: number;
  lastCapture: string;
  freshness: Freshness;
  state: DataState;
}

export type IssueSeverity = "critical" | "high" | "medium" | "low";
export type IssueStatus = "open" | "investigating" | "monitoring" | "resolved";

export interface DataIssue {
  id: string;
  type: string;
  severity: IssueSeverity;
  entity: string;
  detectedAt: string;
  status: IssueStatus;
  detail: string;
}

export interface LineageNode {
  id: string;
  label: string;
  description: string;
  state: DataState;
  detail: string;
}

export type TimelineState = "done" | "pending" | "skipped" | "failed";

export interface TimelineEvent {
  id: string;
  label: string;
  detail: string;
  at: string | null;
  state: TimelineState;
}

export interface ModelComparisonRow {
  modelId: string;
  model: string;
  version: string;
  status: ModelStatus;
  home: number | null;
  draw: number | null;
  away: number | null;
  brier: number | null;
}

export interface SeriesPoint {
  at: string;
  value: number;
}

export interface BreakdownRow {
  key: string;
  label: string;
  sample: number;
  brier: number | null;
  roi: number | null;
}

export interface BacktestConfig {
  modelId: string;
  modelVersion: string;
  competitionId: string;
  season: string;
  market: MarketKey;
  from: string;
  to: string;
  oddsSource: string;
  stakeStrategy: string;
  minimumEdge: number;
}

export interface BacktestResult {
  /** False whenever historical odds are missing: no ROI may be reported. */
  economicAvailable: boolean;
  sampleSize: number;
  brier: number | null;
  logLoss: number | null;
  calibrationError: number | null;
  roi: number | null;
  yieldPct: number | null;
  drawdown: number | null;
  lineValue: number | null;
  equity: SeriesPoint[];
  drawdownSeries: SeriesPoint[];
  monthly: Array<{ month: string; sample: number; brier: number }>;
  leagueSplit: BreakdownRow[];
  marketSplit: BreakdownRow[];
  buckets: CalibrationBin[];
  note: string;
}

export interface PerformanceCharts {
  /** Always true in this phase: shapes exist to validate design, not results. */
  demo: boolean;
  equity: SeriesPoint[];
  drawdown: SeriesPoint[];
  monthly: Array<{ month: string; value: number }>;
  marketBreakdown: BreakdownRow[];
  leagueBreakdown: BreakdownRow[];
}

export type SearchHitType = "fixture" | "team" | "competition" | "model";

export interface SearchHit {
  id: string;
  type: SearchHitType;
  label: string;
  sublabel: string;
  fixtureId: string | null;
}

export interface AnalystSource {
  label: string;
  kind: "fixture" | "model" | "odds" | "data-quality" | "pick";
  reference: string;
  capturedAt: string;
  fixtureId: string | null;
}

export interface AnalystAnswer {
  id: string;
  question: string;
  answer: string;
  evidence: string[];
  metrics: Array<{ label: string; value: string; source: string }>;
  relatedFixtures: Array<{ id: string; label: string }>;
  relatedModels: Array<{ id: string; label: string }>;
  sources: AnalystSource[];
  generatedAt: string;
}
