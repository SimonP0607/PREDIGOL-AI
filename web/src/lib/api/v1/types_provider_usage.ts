/**
 * `GET /admin/monitoring/provider-usage` (plan PM, PM-04-05; BE-076, backend `fbi.api.contracts.provider_usage`): the provider's
 * requests by day, lane, endpoint and competition, the margin and the guards. 404 while `FBI_USAGE_CONSOLE` is off.
 */
export interface UsageDay {
  day: string;
  spent: number;
  budget: number;
  exhausted: boolean;
}

export interface UsageWindow {
  since: string;
  until: string;
  days: number;
  mean: number;
  median: number;
  max: number;
  max_day: string | null;
  max_normal: number;
  max_normal_day: string | null;
  exhausted_days: number;
}

export interface UsageToday {
  day: string;
  spent: number;
  counted: number;
  budget: number;
  provider_limit: number;
  elapsed: number;
  projected: number;
  margin: number;
  margin_pct: number;
  last_request_at: string | null;
}

export interface LaneUsage {
  lane: string;
  label: string;
  priority: number;
  ceiling: number;
  vital: boolean;
  today: number;
  max_day: number;
  share: number;
}

export interface EndpointUsage {
  endpoint: string;
  lane: string;
  today: number;
  window: number;
}

export interface CompetitionUsage {
  league_id: number;
  competition_id: number | null;
  name: string | null;
  country: string | null;
  responses: number;
}

export interface UsageGuards {
  lanes_mode: "off" | "measure" | "enforce";
  dynamic_limits: boolean;
  emergency_reserve: number;
  account_guard: boolean;
  account_pause_seconds: number;
  quiet_minutes: number | null;
}

export interface ProviderUsage {
  provider: string;
  generated_at: string;
  today: UsageToday;
  window: UsageWindow;
  days: UsageDay[];
  lanes: LaneUsage[];
  endpoints: EndpointUsage[];
  competitions: CompetitionUsage[];
  counted_since: string | null;
  guards: UsageGuards;
}
