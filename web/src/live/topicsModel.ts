/**
 * The "Por entidad y tema" view of Operación → Trabajo IA (plan IA, phase 2): what the page concludes from the figures it is given. Pure functions -
 * the words come from the catalogs, the verdicts from the numbers - so each verdict can be tested without a screen. Nothing here asks the server for
 * anything.
 */
import type { BadgeTone } from "@/components/primitives/StatusBadge";
import type {
  AnswerRow,
  ClaimBreakdown,
  EntityResearchOverview,
  GateCheckRow,
  PageCache,
  ResearchClaims,
  ResearchDay,
  ResearchFreshness,
  ResearchSwitch,
  ResearchWord,
  TopicRow,
} from "@/lib/api/v1/types_ai_research";
import { DASH, localDecimalText, localFixed, localPct } from "@/lib/i18n/format";
import { orderedCounts } from "./agentsModel";

/** What the owner can ask of `FBI_AI_RESEARCH_V2`, in the order of how much research v2 is trusted. */
export const MODES = ["off", "shadow", "on"] as const;
/** The topics of the research (fbi.ai.research.TOPICS), in the code's order. */
export const TOPICS = ["availability", "confirmation", "preview"] as const;
/** The entities an answer can be about (fbi.ai.cache.ENTITY_KINDS). */
export const ENTITY_KINDS = ["TEAM", "PLAYER", "COACH", "REFEREE", "MATCH", "COMPETITION"] as const;
/** The states a typed claim can end in (fbi.ai.evidence.Status), from the surest to the oldest. */
export const CLAIM_STATUSES = [
  "CONFIRMED",
  "PROBABLE",
  "RUMOR",
  "CONTRADICTORY",
  "OUTDATED",
] as const;
/** The classes of source (fbi.ai.contracts.mcp.SOURCE_CLASSES), from the one that settles a fact to the one that settles none. */
export const SOURCE_CLASSES = [
  "OFFICIAL",
  "PROVIDER",
  "JOURNALIST",
  "RELIABLE_MEDIA",
  "LOCAL_MEDIA",
  "AGGREGATOR",
  "SOCIAL",
  "UNKNOWN",
] as const;
/** The types of claim (fbi.ai.contracts.claim.ClaimType). */
export const CLAIM_TYPES = [
  "OUT",
  "DOUBT",
  "AVAILABLE",
  "STARTER",
  "SUSPENSION",
  "COACH",
  "SCHEDULE",
  "VENUE",
  "OTHER",
] as const;
/** The tiers of a domain (fbi.ai.evidence.TIER_RANK), as an answer counts its results. */
export const TIERS = [
  "official",
  "competition",
  "club",
  "provider",
  "journalist",
  "media",
  "aggregator",
  "social",
  "unknown",
] as const;
/** The checks of the gate of research v2 (fbi.ai.gate_research), in the order the gate judges them. */
export const GATE_CHECKS = [
  "window",
  "fewer_searches",
  "coverage",
  "coverage_players",
  "shadow_invisible",
  "evidence_known",
  "sample",
] as const;
/** How a call to the claim extractor ends in the ledger (`ai.usage.status`), from the one that gave an answer to the ones that did not. */
export const EXTRACTOR_STATUSES = [
  "ok",
  "invalid_output",
  "timeout",
  "refused",
  "failed",
  "over_budget",
] as const;
/** The verdicts of the gate, in its own words. */
export const VERDICTS = ["PASA", "NO PASA", "PENDIENTE POR TIEMPO REAL"] as const;
/** The words of the gate's evidence the page shows of the days gone while the verdict is pending. */
export const PREVIEW_FIGURES = [
  ["searches", "passes_compared"],
  ["searches", "searches_v1"],
  ["searches", "searches_v2_alone"],
  ["searches", "saved_pct"],
  ["searches", "reuse_pct"],
  ["coverage", "fixtures"],
  ["coverage", "facts_v1"],
  ["coverage", "facts_v2"],
  ["coverage", "coverage_pct"],
  ["coverage", "coverage_players_pct"],
] as const;

/** How the cycle reads the owner's word: as asked, or `held` when `on` was asked and the gate has not let it stand (it behaves as `shadow`). */
export type SwitchState = "off" | "shadow" | "on" | "held";

export function switchState(s: Pick<ResearchSwitch, "asked" | "mode">): SwitchState {
  if (s.asked === "on" && s.mode !== "on") return "held";
  return s.mode;
}

export const SWITCH_TONE: Record<SwitchState, BadgeTone> = {
  off: "neutral",
  shadow: "info",
  on: "positive",
  held: "warning",
};

export const WORD_TONE: Record<ResearchWord, BadgeTone> = {
  off: "neutral",
  shadow: "info",
  on: "positive",
};

/** The tone of a verdict of the gate. A pending one is not a failure: it is a lack of time, and says so. */
export function verdictTone(verdict: string): BadgeTone {
  if (verdict === "PASA") return "positive";
  if (verdict === "NO PASA") return "negative";
  return "warning";
}

export type VerdictKey = "pass" | "fail" | "pending" | "unknown";

/** The word the page translates the gate's verdict by. A verdict this page does not know is `unknown`, shown as the server wrote it. */
export function verdictKey(verdict: string): VerdictKey {
  if (verdict === "PASA") return "pass";
  if (verdict === "NO PASA") return "fail";
  if (verdict === "PENDIENTE POR TIEMPO REAL") return "pending";
  return "unknown";
}

export type MarkKey = "yes" | "no" | "pending";

/** The answer of a check in a word: it holds, it does not, or it cannot be judged yet. */
export function markKey(ok: boolean | null): MarkKey {
  if (ok === null) return "pending";
  return ok ? "yes" : "no";
}

/** A check that passed, failed, or cannot be judged yet. */
export function checkTone(ok: boolean | null): BadgeTone {
  if (ok === null) return "warning";
  return ok ? "positive" : "negative";
}

/** The tone of a class of source: the ones that settle a fact, the ones that only suggest one, the ones that settle none. */
export const CLASS_TONE: Record<string, BadgeTone> = {
  OFFICIAL: "positive",
  PROVIDER: "positive",
  JOURNALIST: "info",
  RELIABLE_MEDIA: "info",
  LOCAL_MEDIA: "neutral",
  AGGREGATOR: "neutral",
  SOCIAL: "warning",
  UNKNOWN: "warning",
};

/** The tone of the state a claim ended in. */
export const STATUS_TONE: Record<string, BadgeTone> = {
  CONFIRMED: "positive",
  PROBABLE: "info",
  RUMOR: "warning",
  CONTRADICTORY: "negative",
  OUTDATED: "neutral",
};

export type AttentionCode =
  | "part_unavailable"
  | "v2_failed"
  | "v2_cut"
  | "not_running"
  | "held_as_shadow"
  | "claims_flagged"
  | "pages_flagged"
  | "unreadable";

export interface Attention {
  code: AttentionCode;
  /** How many: parts, passes, claims, pages, rows. 1 for a state of the switch. */
  n: number;
}

/** The codes that are a fault of ours, not a thing to keep an eye on: the page is not whole. */
export const SERIOUS: readonly AttentionCode[] = ["part_unavailable"];

/** The parts of the overview `attention` reads: what the owner should look at is judged from these figures alone. */
export interface Looked {
  comparison: Pick<EntityResearchOverview["comparison"], "status">;
  gate: Pick<EntityResearchOverview["gate"], "status">;
  per_day: ReadonlyArray<Pick<ResearchDay, "passes_failed" | "passes_cut" | "passes_v2">>;
  switch: Pick<ResearchSwitch, "asked" | "mode">;
  claims: Pick<ResearchClaims, "flagged">;
  pages: Pick<PageCache, "flagged">;
  freshness: Pick<ResearchFreshness, "unreadable">;
}

/**
 * What the owner should look at, most serious first: a part of the page that could not be computed, passes in which research v2 failed or was cut
 * short, a switch asked for that no pass ran, `on` asked and held as `shadow`, claims and pages that read like an order to a model, rows of the
 * cache this code does not read. Empty when there is nothing.
 */
export function attention(o: Looked): Attention[] {
  const found: Attention[] = [];
  const broken = [o.comparison, o.gate].filter((s) => s.status === "not_available").length;
  if (broken > 0) found.push({ code: "part_unavailable", n: broken });
  const failed = o.per_day.reduce((sum, d) => sum + d.passes_failed, 0);
  if (failed > 0) found.push({ code: "v2_failed", n: failed });
  const cut = o.per_day.reduce((sum, d) => sum + d.passes_cut, 0);
  if (cut > 0) found.push({ code: "v2_cut", n: cut });
  const ran = o.per_day.reduce((sum, d) => sum + d.passes_v2, 0);
  if (o.switch.asked !== "off" && ran === 0) found.push({ code: "not_running", n: 1 });
  if (switchState(o.switch) === "held") found.push({ code: "held_as_shadow", n: 1 });
  if (o.claims.flagged > 0) found.push({ code: "claims_flagged", n: o.claims.flagged });
  if (o.pages.flagged > 0) found.push({ code: "pages_flagged", n: o.pages.flagged });
  if (o.freshness.unreadable > 0) found.push({ code: "unreadable", n: o.freshness.unreadable });
  return found;
}

/** Hours as the cache's rules are written: "24 h", "4 h", "1,5 h". */
export function hoursText(hours: number): string {
  return Number.isInteger(hours) ? `${hours} h` : `${localFixed(hours, 1)} h`;
}

/** The share of a topic's answers that can still be reused; null with none kept. */
export function freshShare(t: Pick<TopicRow, "entries" | "fresh">): number | null {
  return t.entries > 0 ? t.fresh / t.entries : null;
}

/** The share of the searches research v2 needed that a fresh answer already satisfied: reused / (reused + demand); null when it needed nothing. */
export function reuseShare(d: Pick<ResearchDay, "reused" | "demand">): number | null {
  const needs = d.reused + d.demand;
  return needs > 0 ? d.reused / needs : null;
}

/** What tells one answer from another: the entity and the topic (the cache keeps one answer for each pair). */
export function answerKey(a: Pick<AnswerRow, "kind" | "id" | "topic">): string {
  return `${a.kind}:${a.id}:${a.topic}`;
}

/** The entity of an answer as the page names it: the team, or the match; an entity it cannot name by its id. */
export function entityName(a: Pick<AnswerRow, "kind" | "id" | "name">): string {
  return a.name ?? `#${a.id}`;
}

/** The results of an answer by tier, in the order of the tiers, then any tier this page does not know (never hidden). */
export function tierCounts(a: Pick<AnswerRow, "tiers">): Array<[string, number]> {
  return orderedCounts(a.tiers, TIERS);
}

/** The cells of a row of the claims tables: one count per state, in the order of the states, then any state this page does not know. */
export function statusCells(b: Pick<ClaimBreakdown, "by_status">): Array<[string, number]> {
  return orderedCounts(b.by_status, CLAIM_STATUSES, true);
}

/** The states of the breakdowns with something in them, in the order of the states: a column nobody used is not drawn. */
export function usedStatuses(rows: readonly Pick<ClaimBreakdown, "by_status">[]): string[] {
  const used = new Set<string>();
  for (const r of rows) for (const [k, n] of Object.entries(r.by_status)) if (n > 0) used.add(k);
  const known = CLAIM_STATUSES.filter((s) => used.has(s));
  const unknown = [...used]
    .filter((s) => !(CLAIM_STATUSES as readonly string[]).includes(s))
    .sort();
  return [...known, ...unknown];
}

/** The classes of source that produced no claim at all in the window: that is a finding, not a blank. */
export function silentClasses(rows: readonly Pick<ClaimBreakdown, "key" | "total">[]): string[] {
  return rows.filter((r) => r.total === 0).map((r) => r.key);
}

export type DayTotals = Omit<ResearchDay, "day" | "exa_v1_usd" | "exa_v2_usd"> & {
  exa_v1_usd: number;
  exa_v2_usd: number;
};

/** Dollars the server sent as text, in millionths of a dollar: whole numbers add up without the drift of decimals (0.03 + 0.005 is 0.035). */
const micros = (usd: string): number => Math.round((Number(usd) || 0) * 1e6);

/** The days of the window added up. The money is the sum of the dollars the server sent as text. */
export function dayTotals(days: readonly ResearchDay[]): DayTotals {
  const total: DayTotals = {
    passes: 0,
    passes_v2: 0,
    passes_failed: 0,
    passes_cut: 0,
    searches: 0,
    demand: 0,
    paid: 0,
    shared: 0,
    reused: 0,
    pages: 0,
    pages_known: 0,
    claims: 0,
    claims_new: 0,
    exa_v1_usd: 0,
    exa_v2_usd: 0,
  };
  for (const d of days) {
    total.passes += d.passes;
    total.passes_v2 += d.passes_v2;
    total.passes_failed += d.passes_failed;
    total.passes_cut += d.passes_cut;
    total.searches += d.searches;
    total.demand += d.demand;
    total.paid += d.paid;
    total.shared += d.shared;
    total.reused += d.reused;
    total.pages += d.pages;
    total.pages_known += d.pages_known;
    total.claims += d.claims;
    total.claims_new += d.claims_new;
    total.exa_v1_usd += micros(d.exa_v1_usd);
    total.exa_v2_usd += micros(d.exa_v2_usd);
  }
  total.exa_v1_usd /= 1e6;
  total.exa_v2_usd /= 1e6;
  return total;
}

/** A percentage the server sent as text ("50.00" = fifty percent) in the reader's language; "—" when it could not be computed. */
export function pctText(value: string | null | undefined, digits = 1): string {
  if (value === null || value === undefined || value === "") return DASH;
  const n = Number(value);
  return Number.isFinite(n) ? localPct(n / 100, digits) : DASH;
}

/** A whole-number or decimal figure the server sent (facts per match), in the reader's language. */
export function figureText(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === "") return DASH;
  return localDecimalText(String(value));
}

/** A fact of v1 that research v2 did not find (fixture, side, who, class) on one line. */
export function missedLine(example: readonly unknown[]): string {
  return example.map((x) => String(x)).join(" · ");
}

const SHORT = 120;

/** One value of a check's detail, short: a scalar as it is, anything else as JSON cut to a line. */
function scalar(value: unknown): string {
  if (value === null || value === undefined) return DASH;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean")
    return String(value);
  const json = JSON.stringify(value);
  return json.length > SHORT ? `${json.slice(0, SHORT)}…` : json;
}

/** The detail of a check as pairs for a list; the first dozen, so one check cannot take the page. */
export function detailPairs(
  detail: Readonly<Record<string, unknown>>,
  limit = 12,
): Array<[string, string]> {
  return Object.entries(detail)
    .slice(0, limit)
    .map(([k, v]) => [k, scalar(v)]);
}

/** The checks that failed, and the ones that cannot be judged yet. */
export function failing(checks: readonly Pick<GateCheckRow, "id" | "ok">[]): string[] {
  return checks.filter((c) => c.ok === false).map((c) => c.id);
}

/**
 * What the days gone show while the gate's verdict is pending: a few named figures read out of the preview the server sent (a free-form record),
 * only the ones that are a number or a text. Never the verdict: the page says they are not evidence.
 */
export function previewFigures(
  preview: Readonly<Record<string, unknown>>,
): Array<{ group: string; key: string; value: string }> {
  const out: Array<{ group: string; key: string; value: string }> = [];
  for (const [group, key] of PREVIEW_FIGURES) {
    const part = preview[group];
    if (part === null || typeof part !== "object") continue;
    const value = (part as Record<string, unknown>)[key];
    if (typeof value === "number" || typeof value === "string")
      out.push({ group, key, value: String(value) });
  }
  return out;
}
