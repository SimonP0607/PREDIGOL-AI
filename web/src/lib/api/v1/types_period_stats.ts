/**
 * A match's statistics by half (plan PM, PM-10-03; `GET /matches/{id}/period-stats`, 404 while FBI_MATCH_HALVES is off): the match,
 * the first half and the second half of the statistics the competition has built. A figure the provider did not send is null.
 */
export type PeriodKey = "total" | "1h" | "2h";

export interface PeriodFigure {
  /** A column of core.fixture_team_stats_period: corners, shots, fouls, possession_pct, expected_goals... */
  key: string;
  home: number | null;
  away: number | null;
}

export interface PeriodBlock {
  period: PeriodKey;
  figures: PeriodFigure[];
}

export interface MatchPeriodStats {
  fixture_id: number;
  /** The statistics this competition has built by half (>= 90 % of the matches asked, at least 5). */
  built: string[];
  asked: number;
  periods: PeriodBlock[];
  as_of: string | null;
  source: string;
}
