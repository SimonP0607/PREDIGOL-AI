/**
 * DEMO DATA — data operations layer: coverage, issues, lineage, fixture timeline.
 */
import type { CoverageRow, DataIssue, LineageNode, TimelineEvent } from "@/types/domain";

const day = "2026-09-04";
const at = (hhmm: string) => `${day}T${hhmm}:00Z`;

export const coverage: CoverageRow[] = [
  {
    competitionId: "epl",
    competition: "Premier League",
    code: "EPL",
    fixtures: 10,
    oddsCoverage: 1,
    marketsCoverage: 0.92,
    bookmakers: 14,
    lastCapture: at("12:03"),
    freshness: "fresh",
    state: "healthy",
  },
  {
    competitionId: "laliga",
    competition: "LaLiga",
    code: "LAL",
    fixtures: 10,
    oddsCoverage: 0.9,
    marketsCoverage: 0.81,
    bookmakers: 11,
    lastCapture: at("12:01"),
    freshness: "fresh",
    state: "healthy",
  },
  {
    competitionId: "seriea",
    competition: "Serie A",
    code: "SEA",
    fixtures: 9,
    oddsCoverage: 0.67,
    marketsCoverage: 0.61,
    bookmakers: 6,
    lastCapture: at("11:41"),
    freshness: "aging",
    state: "warning",
  },
  {
    competitionId: "bundesliga",
    competition: "Bundesliga",
    code: "BUN",
    fixtures: 9,
    oddsCoverage: 0.89,
    marketsCoverage: 0.88,
    bookmakers: 12,
    lastCapture: at("12:02"),
    freshness: "fresh",
    state: "healthy",
  },
  {
    competitionId: "ligue1",
    competition: "Ligue 1",
    code: "LI1",
    fixtures: 6,
    oddsCoverage: 0.33,
    marketsCoverage: 0.34,
    bookmakers: 3,
    lastCapture: at("09:12"),
    freshness: "stale",
    state: "failed",
  },
  {
    competitionId: "eredivisie",
    competition: "Eredivisie",
    code: "ERE",
    fixtures: 4,
    oddsCoverage: 0.75,
    marketsCoverage: 0.79,
    bookmakers: 9,
    lastCapture: at("11:56"),
    freshness: "fresh",
    state: "healthy",
  },
];

export const issues: DataIssue[] = [
  {
    id: "iss-01",
    type: "Failed job",
    severity: "critical",
    entity: "Ligue 1 · odds sweep",
    detectedAt: at("09:14"),
    status: "open",
    detail: "Sweep aborted after 3 consecutive provider 429 responses.",
  },
  {
    id: "iss-02",
    type: "Missing fixtures",
    severity: "high",
    entity: "Serie A · Giornata 3",
    detectedAt: at("08:40"),
    status: "investigating",
    detail: "2 fixtures present in the calendar are absent from the provider response.",
  },
  {
    id: "iss-03",
    type: "Missing odds",
    severity: "high",
    entity: "5 fixtures",
    detectedAt: at("10:05"),
    status: "open",
    detail: "No tracked bookmaker returned a price for these fixtures.",
  },
  {
    id: "iss-04",
    type: "Stale snapshot",
    severity: "medium",
    entity: "Lille vs Rennes",
    detectedAt: at("11:20"),
    status: "monitoring",
    detail: "Latest capture is older than the 20 minute freshness threshold.",
  },
  {
    id: "iss-05",
    type: "Unknown team",
    severity: "medium",
    entity: "provider_team_id 88431",
    detectedAt: at("07:58"),
    status: "open",
    detail: "Provider entity does not resolve to a canonical team row.",
  },
  {
    id: "iss-06",
    type: "Broken mapping",
    severity: "low",
    entity: "Book F · totals alias",
    detectedAt: at("07:31"),
    status: "investigating",
    detail: "Market alias 'Goals O/U 2,5' is not mapped to ou_2_5.",
  },
  {
    id: "iss-07",
    type: "Provider error",
    severity: "medium",
    entity: "API-Football",
    detectedAt: at("11:02"),
    status: "monitoring",
    detail: "4 rate-limit responses in the last hour. Backoff active.",
  },
];

export const lineage: LineageNode[] = [
  {
    id: "provider",
    label: "API-Football",
    description: "Upstream provider",
    state: "warning",
    detail: "Responding · 4 rate-limit errors in the last hour",
  },
  {
    id: "raw",
    label: "Raw payload",
    description: "Immutable landing store",
    state: "healthy",
    detail: "2,148 payloads today · hashed on write",
  },
  {
    id: "normalization",
    label: "Normalization",
    description: "Entity resolution and market mapping",
    state: "warning",
    detail: "2 unknown teams · 1 unmapped market alias",
  },
  {
    id: "postgres",
    label: "PostgreSQL",
    description: "Canonical relational store",
    state: "healthy",
    detail: "Primary reachable · replication lag 0.4 s",
  },
  {
    id: "analytical",
    label: "Analytical layer",
    description: "Feature store and model inputs",
    state: "stale",
    detail: "Ligue 1 partition not refreshed since 09:12 UTC",
  },
];

export function fixtureTimeline(fixtureId: string): TimelineEvent[] {
  const stale = fixtureId === "fx-10245";
  return [
    {
      id: "discovered",
      label: "Fixture discovered",
      detail: "Calendar sync resolved both teams to canonical entities.",
      at: `${day}T06:12:00Z`,
      state: "done",
    },
    {
      id: "odds-first",
      label: "First odds captured",
      detail: "Opening prices stored with provider payload hash.",
      at: `${day}T07:04:00Z`,
      state: "done",
    },
    {
      id: "model",
      label: "Model prediction generated",
      detail: "Poisson v0.4.2-rc1 executed against feature snapshot feat-2026.08.3.",
      at: `${day}T12:04:11Z`,
      state: stale ? "skipped" : "done",
    },
    {
      id: "odds-latest",
      label: "Latest odds snapshot",
      detail: stale
        ? "Capture older than the freshness threshold."
        : "14 bookmakers, overround 1.043.",
      at: stale ? `${day}T09:12:00Z` : `${day}T12:03:50Z`,
      state: stale ? "failed" : "done",
    },
    {
      id: "lineup",
      label: "Lineup update",
      detail: "Confirmed lineups are published ~60 minutes before kickoff.",
      at: null,
      state: "pending",
    },
    {
      id: "near-close",
      label: "Near-close snapshot",
      detail: "T-12m capture. Not validated as an official closing price.",
      at: null,
      state: "pending",
    },
    {
      id: "kickoff",
      label: "Kickoff",
      detail: "Result ingestion starts after the final whistle.",
      at: null,
      state: "pending",
    },
  ];
}
