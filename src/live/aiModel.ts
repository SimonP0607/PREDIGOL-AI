/**
 * Pure rules of the AI decision layer's screens: which tone a decision or a status gets, which answers the
 * owner may give a hypothesis at each stage, and when a promotion is possible. Kept apart from the
 * components so they can be tested without rendering.
 *
 * V2 (the AI's Bogotá day, its budget, its post-mortems): money, the month bar's markers, and the labels of
 * loss classes, post-mortem verdicts, escalation reasons, passes and the ten questions - looked up when called,
 * never at module load, because the language changes at runtime.
 */
import type { BadgeTone } from "@/components/primitives/StatusBadge";
import { hasKey, intlTag, t, translateOr } from "@/lib/i18n";
import { localFixed, localInt, localPct } from "@/lib/i18n/format";
import { formatDate, formatDateLong, formatDateTime, formatTime } from "@/lib/time";
import { marketShort, selectionLabel } from "@/product/shared/markets";
import type { HypothesisDecision, HypothesisStatus, Hypothesis } from "@/lib/api/v1/types_ai";
import type {
  AiBudgetAlert,
  AiBudgetView,
  AiCostPeriod,
  AiDecision,
  CardVerdict,
  EscalationReason,
  EvidenceStatus,
  LossClass,
  PostmortemAnswer,
  PostmortemVerdict,
} from "@/lib/api/v1/types_ai_layer";
import type { ParlayProgress } from "@/lib/api/v1/types_records";

export const DECISION_TONE: Record<AiDecision, BadgeTone> = {
  APPROVE: "positive",
  DOWNGRADE: "warning",
  REJECT: "negative",
  ABSTAIN: "neutral",
};

export const VERDICT_TONE: Record<CardVerdict, BadgeTone> = {
  recommended: "positive",
  caution: "warning",
  not_recommended: "negative",
  no_market: "info",
};

export const EVIDENCE_TONE: Record<EvidenceStatus, BadgeTone> = {
  CONFIRMED: "positive",
  PROBABLE: "info",
  RUMOR: "warning",
  CONTRADICTORY: "negative",
  OUTDATED: "neutral",
};

export const PROGRESS_TONE: Record<ParlayProgress, BadgeTone> = {
  OPEN: "info",
  PARTIAL_WON: "positive",
  PARTIAL_LOST: "negative",
  WON: "positive",
  LOST: "negative",
  VOID: "neutral",
};

export const HYPOTHESIS_TONE: Record<HypothesisStatus, BadgeTone> = {
  PROPOSED: "info",
  INVESTIGATING: "warning",
  ACCEPTED: "brand",
  REJECTED: "neutral",
  RUNNING: "brand",
  SHADOW: "brand",
  DONE: "positive",
  PROMOTED: "positive",
};

/**
 * The owner's answers at each stage. Nothing here is automatic and none of them changes production.
 * A proposal (MEJORAS PROPUESTAS) carries its status as plain text; anything unknown gets no answer.
 */
export function decisionsFor(status: HypothesisStatus | (string & {})): HypothesisDecision[] {
  if (status === "PROPOSED") return ["reject", "investigate", "approve_experiment"];
  if (status === "INVESTIGATING") return ["reject", "approve_experiment"];
  return [];
}

/** Only a DONE experiment whose gate passed can be promoted - by the owner, explicitly. */
export function canPromote(h: Pick<Hypothesis, "status" | "outcome">): boolean {
  return h.status === "DONE" && h.outcome?.["gate_passed"] === true;
}

export type HypothesisGroup = "pending" | "experiment" | "promotable" | "closed";

export function groupOf(h: Pick<Hypothesis, "status" | "outcome">): HypothesisGroup {
  if (h.status === "PROPOSED" || h.status === "INVESTIGATING") return "pending";
  if (h.status === "ACCEPTED" || h.status === "RUNNING" || h.status === "SHADOW")
    return "experiment";
  if (canPromote(h)) return "promotable";
  return "closed";
}

/** The typed word that unlocks a promotion (the button stays disabled until it matches). */
export const PROMOTE_WORD = "PROMOVER";

export function promoteUnlocked(typed: string): boolean {
  return typed.trim().toUpperCase() === PROMOTE_WORD;
}

/** A decimal probability ("0.4512") as a whole percentage with one decimal, or null. */
export function pct(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? Math.round(n * 1000) / 10 : null;
}

/** "Analizado por PrediGol AI" only when a language model took part; the rules alone say so. */
export function analysisLabel(byLlm: boolean): "ai" | "rules" {
  return byLlm ? "ai" : "rules";
}

// ── V2: the day, the budget, money ───────────────────────────────────────────

const DASH = "—";

/** The AI's day is Bogotá's: "today", the three passes and the adaptive budget all follow it. */
export const AI_TZ = "America/Bogota";

/** The month's spend is recorded once past each of these shares of the budget (ai.budget_alerts). */
export const BUDGET_THRESHOLDS: readonly number[] = [70, 85, 95, 100];

/** A price older than this is stale for the AI (fbi.ai.day.STALE_ODDS). */
export const STALE_ODDS_MINUTES = 12 * 60;

export type BudgetState = AiBudgetView["state"];

export const BUDGET_TONE: Record<BudgetState, BadgeTone> = {
  NORMAL: "positive",
  REDUCED: "warning",
  CHEAP_ONLY: "warning",
  EXHAUSTED: "negative",
};

/** A number from the API (numbers, or decimals sent as text); null when absent or not finite. */
export function toNum(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

/**
 * Money in dollars: "US$ 150,00" (es) / "US$ 150.00" (en), two decimals - four below one cent, so a unit cost
 * (or a tiny spend) never reads as zero. "—" when absent. The space is non-breaking.
 */
export function usd(value: number | string | null | undefined): string {
  const n = toNum(value);
  if (n === null) return DASH;
  const abs = Math.abs(n);
  return `US$\u00a0${localFixed(n, abs > 0 && abs < 0.01 ? 4 : 2)}`;
}

/** part / total, unclamped; null without a positive total. */
export function ratioOf(
  part: number | string | null | undefined,
  total: number | string | null | undefined,
): number | null {
  const p = toNum(part);
  const w = toNum(total);
  return p === null || w === null || w <= 0 ? null : p / w;
}

/** A bar's fill, clamped to [0, 100] percent. */
export function barPercent(ratio: number | null | undefined): number {
  if (ratio === null || ratio === undefined || !Number.isFinite(ratio)) return 0;
  return Math.round(Math.min(1, Math.max(0, ratio)) * 1000) / 10;
}

export interface BudgetMarker {
  threshold: number;
  /** The month's spend has reached it (or an alert was recorded for it). */
  crossed: boolean;
  /** The alert recorded this month for this threshold, if any. */
  alert: AiBudgetAlert | null;
}

/** The month bar's markers (70 / 85 / 95 / 100 %), in order, each with the alert recorded for it this month. */
export function budgetMarkers(
  spentRatio: number | null,
  alerts: readonly AiBudgetAlert[] = [],
  thresholds: readonly number[] = BUDGET_THRESHOLDS,
): BudgetMarker[] {
  return [...new Set(thresholds)]
    .sort((a, b) => a - b)
    .map((threshold) => {
      const alert = alerts.find((a) => Number(a.threshold) === threshold) ?? null;
      const reached = spentRatio !== null && spentRatio * 100 >= threshold - 1e-9;
      return { threshold, crossed: alert !== null || reached, alert };
    });
}

/** A threshold as the reader writes a percentage: "70 %" (es), "70%" (en). */
export function thresholdText(threshold: number): string {
  return localPct(threshold / 100, 0);
}

/** How the month's projection reads against the budget. */
export function projectionTone(share: number | null | undefined): BadgeTone {
  if (share === null || share === undefined || !Number.isFinite(share)) return "neutral";
  if (share > 1) return "negative";
  if (share >= 0.85) return "warning";
  return "positive";
}

export function budgetTone(state: string): BadgeTone {
  return state in BUDGET_TONE ? BUDGET_TONE[state as BudgetState] : "neutral";
}

/** The verdict of the AI's shadow gate. */
export function gateTone(verdict: string | null | undefined): BadgeTone {
  return verdict === "pass" ? "positive" : verdict === "fail" ? "negative" : "neutral";
}

/** "8 oct 18:00" and "18:00" in Bogotá, where the AI's day is. */
export function bogotaDateTime(iso: string | null | undefined): string {
  return formatDateTime(iso, AI_TZ);
}

export function bogotaTime(iso: string | null | undefined): string {
  return formatTime(iso, AI_TZ);
}

const DAY_KEY = /^\d{4}-\d{2}-\d{2}$/;

/** "jueves, 8 de octubre" for a day key ("2026-10-08"); anything else as given. */
export function dayLabel(key: string): string {
  return DAY_KEY.test(key) ? formatDateLong(`${key}T12:00:00Z`, "UTC") : key;
}

/** "jue 8 oct" for a day key; anything else as given. */
export function dayShort(key: string): string {
  return DAY_KEY.test(key) ? formatDate(`${key}T12:00:00Z`, "UTC") : key;
}

/** An age in minutes, short: "45 min", "3 h", "2 d". */
export function minutesText(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined || !Number.isFinite(minutes)) return DASH;
  const m = Math.max(0, Math.round(minutes));
  if (m < 60) return `${m} min`;
  if (m < 48 * 60) return `${Math.round(m / 60)} h`;
  return `${Math.round(m / 1440)} d`;
}

// ── V2: matches, selections, edges ───────────────────────────────────────────

/** "Millonarios - Santa Fe" -> both names; null when the text is not exactly two names. */
export function teamsOf(match: string): { home: string; away: string } | null {
  const parts = match.split(" - ");
  if (parts.length !== 2) return null;
  const [home, away] = parts.map((p) => p.trim()) as [string, string];
  return home && away ? { home, away } : null;
}

/** "1X2 · Gana Millonarios", "Goles · Más de 2,5 goles": the market and the selection in the reader's words. */
export function selectionText(
  market: string,
  selection: string,
  line: string | number | null | undefined,
  match?: string,
): string {
  const teams = match ? teamsOf(match) : null;
  const label = selectionLabel({
    market_key: market,
    selection,
    line,
    home: teams?.home,
    away: teams?.away,
  });
  return `${marketShort(market)} · ${label}`;
}

/** The model's edge over the market in percentage points ("ventaja pp"): edge, else model - market. */
export function edgePoints(
  edge: number | string | null | undefined,
  pModel: number | string | null | undefined,
  pMarket: number | string | null | undefined,
): number | null {
  const e = toNum(edge);
  if (e !== null) return Math.round(e * 1000) / 10;
  const m = toNum(pModel);
  const k = toNum(pMarket);
  return m === null || k === null ? null : Math.round((m - k) * 1000) / 10;
}

/** "+3,2 pp" / "−1,5 pp" / "0,0 pp"; "—" when absent. */
export function pointsText(points: number | null | undefined): string {
  if (points === null || points === undefined || !Number.isFinite(points)) return DASH;
  const sign = points > 0 ? "+" : points < 0 ? "−" : "";
  return `${sign}${localFixed(Math.abs(points), 1)} pp`;
}

/** A probability (fraction) as a percentage with one decimal: "45,1 %"; "—" when absent. */
export function probText(value: number | string | null | undefined, digits = 1): string {
  const n = toNum(value);
  return n === null ? DASH : localPct(n, digits);
}

/** A signed fraction as a percentage: ROI, CLV, EV ("+4,5 %"); "—" when absent. */
export function signedText(value: number | string | null | undefined, digits = 1): string {
  const n = toNum(value);
  return n === null ? DASH : localPct(n, digits, true);
}

/** A plain number with fixed decimals (log loss, Brier); "—" when absent. */
export function fixedText(value: number | string | null | undefined, digits = 3): string {
  const n = toNum(value);
  return n === null ? DASH : localFixed(n, digits);
}

// ── V2: labels (looked up when called) ───────────────────────────────────────

export const LOSS_CLASSES: readonly LossClass[] = [
  "MODEL_ERROR",
  "CONTEXT_ERROR",
  "DATA_ERROR",
  "MARKET_ERROR",
  "EXECUTION_ERROR",
  "NORMAL_VARIANCE",
  "UNKNOWN",
];

export const CLASS_TONE: Record<LossClass, BadgeTone> = {
  MODEL_ERROR: "negative",
  CONTEXT_ERROR: "warning",
  DATA_ERROR: "warning",
  MARKET_ERROR: "info",
  EXECUTION_ERROR: "warning",
  NORMAL_VARIANCE: "neutral",
  UNKNOWN: "neutral",
};

/** MODEL_ERROR -> "Error del modelo", MARKET_ERROR -> "El mercado sabía algo"; an unknown class as given. */
export function lossClassLabel(cls: string): string {
  return translateOr(`ai.v2.class.${cls}`, cls);
}

export function classTone(cls: string | null | undefined): BadgeTone {
  return cls && cls in CLASS_TONE ? CLASS_TONE[cls as LossClass] : "neutral";
}

export const POSTMORTEM_VERDICTS: readonly PostmortemVerdict[] = [
  "approved_won",
  "approved_lost",
  "caution_won",
  "caution_lost",
  "rejected_would_have_won",
  "rejected_correctly",
  "unreviewed_won",
  "unreviewed_lost",
  "push",
];

/** Green when the AI's decision was right, red when it was wrong. */
export const POSTMORTEM_TONE: Record<PostmortemVerdict, BadgeTone> = {
  approved_won: "positive",
  approved_lost: "negative",
  caution_won: "info",
  caution_lost: "warning",
  rejected_would_have_won: "negative",
  rejected_correctly: "positive",
  unreviewed_won: "neutral",
  unreviewed_lost: "neutral",
  push: "neutral",
};

/** approved_lost -> "Aprobada que perdió", rejected_would_have_won -> "Rechazada que habría ganado". */
export function verdictLabel(verdict: string): string {
  return translateOr(`ai.v2.verdict.${verdict}`, verdict.replace(/_/g, " "));
}

export function verdictTone(verdict: string): BadgeTone {
  return verdict in POSTMORTEM_TONE ? POSTMORTEM_TONE[verdict as PostmortemVerdict] : "neutral";
}

/** Why the server escalated a match (fbi.ai.brief.REASONS). */
export const ESCALATION_REASONS: readonly EscalationReason[] = [
  "candidate",
  "model_market_gap",
  "market_move",
  "important_news",
  "high_uncertainty",
  "contradiction",
  "brief_flag",
];

export function reasonLabel(reason: string): string {
  return translateOr(`ai.v2.reason.${reason}`, reason.replace(/_/g, " "));
}

/** The three passes of a match of the day, in order. */
export const PASSES = ["first", "pre", "final"] as const;

/** first -> "Primera 00:05", pre -> "Previa", final -> "Final". */
export function passLabel(pass: string): string {
  return translateOr(`ai.v2.pass.${pass}`, pass);
}

/** The ten questions of a post-mortem, in the order they are asked (fbi.ai.pick_postmortem). */
export const QUESTIONS = [
  "expected",
  "happened",
  "model",
  "information",
  "ignored_signal",
  "odds_moved",
  "key_absence",
  "lineup_changed",
  "uncertainty",
  "variance",
] as const;

/** expected -> "¿Qué esperaba PrediGol?" ... variance -> "¿Fue simplemente varianza?". */
export function questionLabel(question: string): string {
  return translateOr(`ai.v2.question.${question}`, question.replace(/_/g, " "));
}

/** The answers in the questions' order, then any other the API added. */
export function orderedAnswers(
  answers: Record<string, PostmortemAnswer> | null | undefined,
): Array<[string, PostmortemAnswer]> {
  const all = answers ?? {};
  const known: string[] = [...QUESTIONS];
  const first = known
    .filter((q) => all[q] !== undefined)
    .map((q) => [q, all[q]!] as [string, PostmortemAnswer]);
  const rest = Object.entries(all).filter(([q]) => !known.includes(q));
  return [...first, ...rest];
}

export type AnswerKind = "yes" | "no" | "unknown" | "against" | "favour" | "stable" | "na" | "text";

const ANSWER_KIND: Record<string, AnswerKind> = {
  si: "yes",
  yes: "yes",
  no: "no",
  "sin datos": "unknown",
  unknown: "unknown",
  "en contra": "against",
  against: "against",
  "a favor": "favour",
  favour: "favour",
  favor: "favour",
  estable: "stable",
  stable: "stable",
  "no aplica": "na",
  "n/a": "na",
  "not applicable": "na",
};

/** The server answers in Spanish ("sí", "no", "sin datos", "en contra"...); anything else is free text. */
export function answerKind(answer: string | null | undefined): AnswerKind {
  if (answer === null || answer === undefined) return "unknown";
  const key = answer
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .trim()
    .toLowerCase();
  if (!key) return "unknown";
  return ANSWER_KIND[key] ?? "text";
}

/** A "sí" asks for a look (a "sí" to "¿Fue simplemente varianza?" only informs); a price against is red. */
export function answerTone(question: string, kind: AnswerKind): BadgeTone {
  if (kind === "against") return "negative";
  if (kind === "favour") return "positive";
  if (kind === "yes") return question === "variance" ? "info" : "warning";
  return "neutral";
}

export function settledLabel(settled: string): string {
  return translateOr(`ai.v2.settled.${settled}`, settled.replace(/_/g, " "));
}

export function settledTone(settled: string): BadgeTone {
  if (settled === "win" || settled === "half_win") return "positive";
  if (settled === "loss" || settled === "half_loss") return "negative";
  return "neutral";
}

/** How one answer is shown: the chip's text and tone; "expected" is the selection itself, plain text. */
export function answerView(
  question: string,
  answer: string,
): { label: string; tone: BadgeTone; chip: boolean } {
  if (question === "expected") return { label: answer, tone: "neutral", chip: false };
  if (question === "happened")
    return { label: settledLabel(answer), tone: settledTone(answer), chip: true };
  const kind = answerKind(answer);
  const label = kind === "text" ? answer : translateOr(`ai.v2.answer.${kind}`, answer);
  return { label, tone: answerTone(question, kind), chip: true };
}

/** L1 / L2 / L3 / web, then any other level the API reports. */
export const LEVELS = ["L1", "L2", "L3", "web"] as const;

export function levelLabel(level: string): string {
  return translateOr(`ai.v2.level.${level}`, level);
}

/** The spend by level in the stack's order, a level reported twice added up. */
export function levelRows(
  rows: AiCostPeriod["by_level"] | null | undefined,
): Array<{ key: string; requests: number; cost_usd: number }> {
  const by = new Map<string, { key: string; requests: number; cost_usd: number }>();
  for (const r of rows ?? []) {
    const cur = by.get(r.key) ?? { key: r.key, requests: 0, cost_usd: 0 };
    cur.requests += Number(r.requests) || 0;
    cur.cost_usd += Number(r.cost_usd) || 0;
    by.set(r.key, cur);
  }
  const order: string[] = [...LEVELS];
  return [...by.values()].sort((a, b) => {
    const ia = order.indexOf(a.key);
    const ib = order.indexOf(b.key);
    return (
      (ia < 0 ? order.length : ia) - (ib < 0 ? order.length : ib) || a.key.localeCompare(b.key)
    );
  });
}

// ── V2: evidence of a note or a proposal, compact ────────────────────────────

export interface EvidenceItem {
  key: string;
  label: string;
  value: string;
}

/** A key of an evidence object in the reader's words (a verdict or a loss class by its own label). */
export function evidenceKeyLabel(key: string): string {
  for (const k of [`ai.v2.evidenceKey.${key}`, `ai.v2.verdict.${key}`, `ai.v2.class.${key}`]) {
    if (hasKey(k)) return t(k);
  }
  return key.replace(/_/g, " ");
}

/** A measured figure, short: 2,31 · 0,421 · 12,5 (up to three decimals below one, two above). */
function figureText(value: number): string {
  if (Number.isInteger(value)) return localInt(value);
  return new Intl.NumberFormat(intlTag(), {
    maximumFractionDigits: Math.abs(value) < 1 ? 3 : 2,
  }).format(value);
}

function scalarText(value: unknown): string | null {
  if (typeof value === "number") return Number.isFinite(value) ? figureText(value) : null;
  if (typeof value === "string") {
    const s = value.trim();
    return s ? (s.length > 90 ? `${s.slice(0, 89)}…` : s) : null;
  }
  if (typeof value === "boolean") return value ? t("common.yes") : t("common.no");
  return null;
}

/** Evidence keys whose value is a code with its own label: a loss class, a source level. */
const CODE_LABELS: Record<string, string> = { class: "ai.v2.class", tier: "ai.layer.tierName" };

/**
 * One evidence value: a number, a text, a list (its size), or a small map ("Aprobada que ganó 2 · …"). A code
 * under a known key (class, tier) is said by its label.
 */
export function evidenceValue(value: unknown, key?: string): string | null {
  if (value === null || value === undefined) return null;
  const prefix = key === undefined ? undefined : CODE_LABELS[key];
  if (prefix && typeof value === "string" && hasKey(`${prefix}.${value}`)) {
    return t(`${prefix}.${value}`);
  }
  if (Array.isArray(value)) {
    return t("ai.v2.evidence.items", { count: value.length, n: localInt(value.length) });
  }
  if (typeof value === "object") {
    const parts: string[] = [];
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      const s = scalarText(v);
      if (s !== null) parts.push(`${evidenceKeyLabel(k)} ${s}`);
    }
    if (!parts.length) return null;
    return parts.length > 4 ? `${parts.slice(0, 4).join(" · ")} …` : parts.join(" · ");
  }
  return scalarText(value);
}

/** The evidence of a learning note or a proposal as a few labelled values (never a JSON dump). */
export function evidenceSummary(
  evidence: Record<string, unknown> | null | undefined,
  { omit = [], max = 8 }: { omit?: readonly string[]; max?: number } = {},
): EvidenceItem[] {
  const out: EvidenceItem[] = [];
  for (const [key, raw] of Object.entries(evidence ?? {})) {
    if (out.length >= max) break;
    if (omit.includes(key) || key === "pattern_version") continue;
    const value = evidenceValue(raw, key);
    if (value !== null) out.push({ key, label: evidenceKeyLabel(key), value });
  }
  return out;
}

/** The comparison's sample, as counts: selections, days, rejected (what the gate asks for). */
export function sampleCounts(sample: Record<string, unknown> | null | undefined): {
  selections: number | null;
  days: number | null;
  rejected: number | null;
} {
  const n = (k: string): number | null => {
    const v = sample?.[k];
    return typeof v === "number" || typeof v === "string" ? toNum(v) : null;
  };
  return { selections: n("selections"), days: n("days"), rejected: n("rejected") };
}
