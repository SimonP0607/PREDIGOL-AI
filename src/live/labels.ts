/** Human names for job types recorded in the ledger. */
export const JOB_LABEL: Record<string, string> = {
  odds_capture: "Odds capture",
  fixtures_sync: "Fixtures sync",
  results_sync: "Results sync",
  raw_replay: "Raw replay",
  seasons_refresh: "Seasons refresh",
  historical_backfill: "Historical backfill",
  feature_build: "Feature build",
  historical_odds_import: "Historical odds import",
  backtest: "Backtest",
  pick_pipeline: "Decision pipeline",
  odds_import: "Odds import",
  live_odds: "In-play odds (job)",
  live_odds_capture: "In-play odds capture",
  live_match: "Live match follow (job)",
  live_match_capture: "Live match follow",
  notifier: "Notifier",
  quality_sweep: "Quality sweep",
  team_identity_resolve: "Team identity resolve",
  teams_sync: "Teams sync",
  window_probe: "Window probe",
  plan_probe: "Plan probe",
  raw_transfer: "Raw transfer",
};

/** "pinnacle/closing/shin" -> "Pinnacle · closing · shin". */
export function baselineLabel(key: string): string {
  const [bm, kind, method] = key.split("/");
  const book = bm === "AVG" ? "Market average" : bm === "MAX" ? "Best price" : titleCase(bm ?? key);
  const when =
    kind === "pre_closing" ? "pre-closing" : kind === "closing" ? "closing" : (kind ?? "");
  return `${book} · ${when}${method ? ` · ${method}` : ""}`;
}

function titleCase(s: string): string {
  return s.length ? s[0]!.toUpperCase() + s.slice(1) : s;
}

/** 2024 -> "2024/25", the way API-Football labels a season. */
export function seasonLabel(season: number | null | undefined): string {
  if (season === null || season === undefined) return "—";
  return `${season}/${String((season + 1) % 100).padStart(2, "0")}`;
}

const BOOK_LABEL: Record<string, string> = {
  pinnacle: "Pinnacle",
  bet365: "Bet365",
  AVG: "Market average",
  MAX: "Best price",
  betfair_exchange: "Betfair Exchange",
  betfair_sb: "Betfair Sportsbook",
  williamhill: "William Hill",
  bwin: "bwin",
  interwetten: "Interwetten",
  betvictor: "BetVictor",
  "1xbet": "1xBet",
};

/** A Football-Data bookmaker code, for display. */
export function bookLabel(code: string): string {
  return BOOK_LABEL[code] ?? code;
}
