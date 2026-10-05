import { intlTag, t, translateOr } from "@/lib/i18n";

/** Human names (English) for job types recorded in the ledger; `jobLabel` translates them. */
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
  context_refresh: "Context refresh",
  results_repair: "Results repair",
  ai_daily_report: "AI daily report",
  ai_pick_review: "AI pick review",
  catalogue_refresh: "Catalogue refresh",
  context_due: "Context (due matches)",
  context_refresh_manual: "Context refresh (manual)",
  elo_refresh: "Elo ratings refresh",
  final_prematch: "Final pre-match prices",
  reference_refresh: "Reference feeds",
  research_monitor: "Research monitor",
  research_monitor_catch_up: "Research monitor (catch-up)",
  research_v2_weekly: "Research V2 (weekly)",
  research_v2: "Research V2",
  run_watchdog: "Run watchdog",
  post_match_detail: "Post-match detail",
  historical_validation: "Historical validation",
  truth_audit: "Data truth audit",
  capacity_probe: "Capacity probe",
  raw_backfill_season_stats: "Season stats from RAW",
};

/** A job type for display, in the reader's language. */
export function jobLabel(kind: string): string {
  return translateOr(`admin.jobs.${kind}`, JOB_LABEL[kind] ?? kind.replace(/_/g, " "));
}

/** "pinnacle/closing/shin" -> "Pinnacle · closing · shin". */
export function baselineLabel(key: string): string {
  const [bm, kind, method] = key.split("/");
  const book =
    bm === "AVG"
      ? t("admin.labels.marketAverage")
      : bm === "MAX"
        ? t("admin.labels.bestPrice")
        : titleCase(bm ?? key);
  const when =
    kind === "pre_closing"
      ? t("admin.labels.preClosing")
      : kind === "closing"
        ? t("admin.labels.closing")
        : (kind ?? "");
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
  if (code === "AVG") return t("admin.labels.marketAverage");
  if (code === "MAX") return t("admin.labels.bestPrice");
  return BOOK_LABEL[code] ?? code;
}

const POSITION_KEY: Record<string, string> = {
  g: "goalkeeper",
  gk: "goalkeeper",
  goalkeeper: "goalkeeper",
  d: "defender",
  defender: "defender",
  m: "midfielder",
  midfielder: "midfielder",
  f: "attacker",
  attacker: "attacker",
  forward: "attacker",
};

/** A position as the provider writes it in a line-up ("G", "D", "M", "F") or a profile ("Attacker"), one way. */
export function positionLabel(position: string | null | undefined): string {
  if (!position) return "—";
  const key = POSITION_KEY[position.trim().toLowerCase()];
  return key ? t(`catalog.positions.${key}`) : position;
}

/**
 * A health reason in the reader's language: the backend's stable code with its values (a job name shown as its
 * label), falling back to the English detail when this page does not know the code.
 */
export function healthReason(c: {
  detail: string;
  code?: string | undefined;
  vars?: Record<string, string | number | null> | undefined;
}): string {
  if (!c.code) return c.detail;
  const vars: Record<string, string | number> = {};
  for (const [k, v] of Object.entries(c.vars ?? {})) {
    if (v === null || v === undefined) continue;
    vars[k] =
      k === "job" ? jobLabel(String(v)) : typeof v === "number" ? v.toLocaleString(intlTag()) : v;
  }
  return translateOr(`system.health.${c.code}`, c.detail, vars);
}
