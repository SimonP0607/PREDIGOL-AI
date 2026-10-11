/**
 * The pure rules behind the product's records on screen: which selection is which, what a
 * result means, and the parlay slip a user is assembling (one leg per match, at most ten) and
 * what it adds up to - arithmetic only: the user's own parlay is never sent to an AI.
 */
import type {
  HistoryGroupKey,
  MarketKey,
  ParlayProgress,
  ParlayStatus,
  ParlayValidation,
  ResultStatus,
} from "@/lib/api/v1/types_records";

export const MAX_SLIP_LEGS = 10;
export const MIN_SLIP_LEGS = 2;
export const HISTORY_GROUPS: readonly HistoryGroupKey[] = [
  "predigol_picks",
  "my_picks",
  "predigol_parlays",
  "my_parlays",
] as const;

/** "2.50" / 2.5 / "2.5" are one line: compare lines as numbers, never as text. */
export function normLine(line: string | number | null | undefined): string {
  const n = Number(line ?? 0);
  return Number.isFinite(n) ? String(n === 0 ? 0 : n) : "0";
}

export interface SelectionRef {
  fixture_id: number;
  market_key: string;
  selection: string;
  line?: string | number | null | undefined;
}

export function selectionKey(s: SelectionRef): string {
  return `${s.fixture_id}|${s.market_key}|${s.selection}|${normLine(s.line)}`;
}

/** A quarter line (.25 / .75): a half-won leg has no clean meaning inside a parlay. */
export function isQuarterLine(line: string | number | null | undefined): boolean {
  const n = Math.abs(Number(line ?? 0) * 4);
  return Number.isFinite(n) && Math.round(n) % 2 === 1;
}

export type Tone = "pending" | "win" | "loss" | "neutral" | "live";

export function resultTone(status: ResultStatus): Tone {
  if (status === "WIN" || status === "HALF_WIN") return "win";
  if (status === "LOSS" || status === "HALF_LOSS") return "loss";
  if (status === "PUSH" || status === "VOID") return "neutral";
  return "pending";
}

export type ParlayOutcome = "playing" | "won" | "lost" | "void" | "building";

/**
 * One state for a parlay's result (REVIEW PREDIGOL, point 2): En juego, Ganado or Perdido - plus Anulado
 * when it happens. A lost leg decides it at once, even with legs still to play.
 */
export function parlayOutcome(
  status: ParlayStatus,
  progress?: ParlayProgress | null,
): ParlayOutcome {
  if (status === "WON" || status === "PARTIAL_VOID") return "won";
  if (status === "LOST") return "lost";
  if (status === "VOID") return "void";
  if (status === "BUILDING") return "building";
  if (progress === "LOST" || progress === "PARTIAL_LOST") return "lost";
  if (progress === "WON") return "won";
  return "playing";
}

export function parlayTone(status: ParlayStatus): Tone {
  if (status === "WON" || status === "PARTIAL_VOID") return "win";
  if (status === "LOST") return "loss";
  if (status === "VOID") return "neutral";
  if (status === "ACTIVE") return "live";
  return "pending";
}

/** A match that has kicked off cannot be saved, edited or added any more. */
export function hasStarted(
  m: { kickoff_at: string; status_group?: string | null | undefined },
  now: number = Date.now(),
): boolean {
  if (m.status_group && m.status_group !== "scheduled") return true;
  return Date.parse(m.kickoff_at) <= now;
}

// ── the slip ────────────────────────────────────────────────────────────────

export interface SlipLeg {
  key: string;
  fixture_id: number;
  market_key: MarketKey;
  selection: string;
  line: string;
  home: string;
  away: string;
  kickoff_at: string;
  /** The best price we showed when it was added (null: none known). */
  odds: string | null;
  bookmaker: string | null;
  /** PrediGol's probability for it when it was added (null or absent: not known). Shown, never sent to a model. */
  p_model?: string | null;
}

export type SlipAction =
  | { type: "toggle"; leg: Omit<SlipLeg, "key"> }
  | { type: "remove"; key: string }
  | { type: "clear" }
  | { type: "load"; legs: SlipLeg[] };

export interface SlipChange {
  legs: SlipLeg[];
  /** What happened, for the UI to say so: added, removed, replaced (same match), full. */
  effect: "added" | "removed" | "replaced" | "full" | "cleared" | "loaded";
}

/** One leg per match: adding a second selection of a match replaces the first. */
export function slipReduce(legs: readonly SlipLeg[], action: SlipAction): SlipChange {
  switch (action.type) {
    case "toggle": {
      const key = selectionKey(action.leg);
      if (legs.some((l) => l.key === key)) {
        return { legs: legs.filter((l) => l.key !== key), effect: "removed" };
      }
      const leg: SlipLeg = { ...action.leg, line: normLine(action.leg.line), key };
      const sameMatch = legs.findIndex((l) => l.fixture_id === leg.fixture_id);
      if (sameMatch >= 0) {
        const next = [...legs];
        next[sameMatch] = leg;
        return { legs: next, effect: "replaced" };
      }
      if (legs.length >= MAX_SLIP_LEGS) return { legs: [...legs], effect: "full" };
      return { legs: [...legs, leg], effect: "added" };
    }
    case "remove":
      return { legs: legs.filter((l) => l.key !== action.key), effect: "removed" };
    case "clear":
      return { legs: [], effect: "cleared" };
    case "load":
      return { legs: action.legs.slice(0, MAX_SLIP_LEGS), effect: "loaded" };
  }
}

const MARKETS: readonly string[] = ["1X2", "OU", "BTTS", "AH", "DC"];

/** A slip read back from storage: anything malformed is dropped, never trusted. */
export function parseSlip(raw: string | null): SlipLeg[] {
  if (!raw) return [];
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!Array.isArray(data)) return [];
  const out: SlipLeg[] = [];
  for (const x of data as Array<Record<string, unknown>>) {
    if (
      typeof x !== "object" ||
      x === null ||
      typeof x["fixture_id"] !== "number" ||
      typeof x["market_key"] !== "string" ||
      !MARKETS.includes(x["market_key"]) ||
      typeof x["selection"] !== "string" ||
      typeof x["kickoff_at"] !== "string"
    ) {
      continue;
    }
    const leg = {
      fixture_id: x["fixture_id"],
      market_key: x["market_key"] as MarketKey,
      selection: x["selection"],
      line: normLine(x["line"] as string | number | undefined),
      home: typeof x["home"] === "string" ? x["home"] : "",
      away: typeof x["away"] === "string" ? x["away"] : "",
      kickoff_at: x["kickoff_at"],
      odds: typeof x["odds"] === "string" ? x["odds"] : null,
      bookmaker: typeof x["bookmaker"] === "string" ? x["bookmaker"] : null,
      p_model: typeof x["p_model"] === "string" ? x["p_model"] : null,
    };
    out.push({ ...leg, key: selectionKey(leg) });
  }
  return slipReduce([], { type: "load", legs: dedupe(out) }).legs;
}

function dedupe(legs: SlipLeg[]): SlipLeg[] {
  const seen = new Set<number>();
  return legs.filter((l) => (seen.has(l.fixture_id) ? false : (seen.add(l.fixture_id), true)));
}

/** The combined price of the legs that have one; null when any leg has none. */
export function slipOdds(legs: readonly SlipLeg[]): number | null {
  if (legs.length === 0) return null;
  let product = 1;
  for (const l of legs) {
    const o = l.odds === null ? NaN : Number(l.odds);
    if (!Number.isFinite(o) || o <= 1) return null;
    product *= o;
  }
  return Math.round(product * 1000) / 1000;
}

// ── what the slip adds up to: arithmetic on numbers already known, never a model call ──

export type DependencyLevel = "low" | "medium" | "high";
export type DependencyReason = "shared_team" | "measured_dependence" | "same_competition_day";
export const DEPENDENCY_LEVELS: readonly DependencyLevel[] = ["low", "medium", "high"] as const;
export const DEPENDENCY_REASONS: readonly DependencyReason[] = [
  "shared_team",
  "measured_dependence",
  "same_competition_day",
] as const;

/** A probability as the API sends it ("0.5432"): a number in (0, 1], otherwise null. */
export function toProbability(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) && n > 0 && n <= 1 ? n : null;
}

/**
 * Every leg wins, were the legs independent: the product of their PrediGol probabilities.
 * Null when there is no leg or any leg's probability is missing or invalid.
 */
export function slipProbability(
  legs: readonly { p_model?: string | number | null | undefined }[],
): number | null {
  if (legs.length === 0) return null;
  let product = 1;
  for (const l of legs) {
    const p = toProbability(l.p_model);
    if (p === null) return null;
    product *= p;
  }
  return product;
}

function teamKey(name: string): string {
  return name.trim().replace(/\s+/g, " ").toLowerCase();
}

/** Two legs share a team (by name, ignoring case and spacing): their results are linked. */
export function sharedTeamHint(legs: readonly { home: string; away: string }[]): boolean {
  const seen = new Set<string>();
  for (const l of legs) {
    const teams = new Set([teamKey(l.home), teamKey(l.away)].filter((k) => k !== ""));
    for (const team of teams) if (seen.has(team)) return true;
    for (const team of teams) seen.add(team);
  }
  return false;
}

export function isDependencyLevel(value: unknown): value is DependencyLevel {
  return (DEPENDENCY_LEVELS as readonly unknown[]).includes(value);
}

export function isDependencyReason(value: unknown): value is DependencyReason {
  return (DEPENDENCY_REASONS as readonly unknown[]).includes(value);
}

export interface DependencyView {
  level: DependencyLevel;
  /** Known reasons only, each once, in the server's order. */
  reasons: DependencyReason[];
}

/** What the server checked (POST /me/parlays/validate: rules and arithmetic, no AI). */
export type ServerCheck = Pick<
  ParlayValidation,
  "estimated_probability" | "dependency" | "correlation"
>;

/** The server's word on dependence; an answer without a level only said whether legs are independent. */
export function dependencyOf(server: ServerCheck): DependencyView | null {
  const level = server.dependency?.level;
  if (isDependencyLevel(level)) {
    const reasons = [...new Set(server.dependency?.reasons ?? [])].filter(isDependencyReason);
    return { level, reasons };
  }
  const independent = server.correlation?.independent;
  if (independent === false) return { level: "medium", reasons: [] };
  if (independent === true) return { level: "low", reasons: [] };
  return null;
}

/** The reasons worth saying: a measured dependence already says the legs share a competition and day. */
export function explainedReasons(reasons: readonly DependencyReason[]): DependencyReason[] {
  return reasons.includes("measured_dependence")
    ? reasons.filter((r) => r !== "same_competition_day")
    : [...reasons];
}

export interface SlipEstimate {
  /** Null: not known yet. "hint": the client saw two legs share a team; the server's answer replaces it. */
  dependency: (DependencyView & { source: "server" | "hint" }) | null;
  /**
   * Every leg wins. "server": PrediGol's estimate adjusted for the measured dependence; "product": the
   * plain product of the legs' probabilities, given only while nothing says the legs depend on each other.
   * Null: not known, or only a blind product of dependent legs was available.
   */
  probability: { value: number; source: "server" | "product" } | null;
}

/**
 * What the slip's summary may honestly say. The server's answer wins once it has one. Before it,
 * the client says what it can at once: a shared team means high dependence (and no product), and
 * otherwise the product of the legs' probabilities stands as a provisional figure. Never a blind
 * product when the dependence is medium or high, or could not be checked.
 */
export function slipEstimate(
  legs: readonly { home: string; away: string; p_model?: string | number | null | undefined }[],
  server: ServerCheck | null,
  failed = false,
): SlipEstimate {
  const hint: SlipEstimate["dependency"] = sharedTeamHint(legs)
    ? { level: "high", reasons: ["shared_team"], source: "hint" }
    : null;
  const product = slipProbability(legs);
  if (server) {
    const told = dependencyOf(server);
    const dependency: SlipEstimate["dependency"] = told ? { ...told, source: "server" } : hint;
    const estimated = toProbability(server.estimated_probability);
    if (estimated !== null)
      return { dependency, probability: { value: estimated, source: "server" } };
    const independent = dependency?.level === "low";
    return {
      dependency,
      probability: independent && product !== null ? { value: product, source: "product" } : null,
    };
  }
  return {
    dependency: hint,
    probability:
      !failed && hint === null && product !== null ? { value: product, source: "product" } : null,
  };
}
