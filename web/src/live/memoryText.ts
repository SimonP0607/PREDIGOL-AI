/**
 * The longitudinal memory as text (plan F8): what a series says once its state is known, how far to trust it and what it rests on.
 * Pure functions: the page and its tests read the same ones.
 */
import type { BadgeTone } from "@/components/primitives/StatusBadge";
import type { PickPostmortem } from "@/lib/api/v1/types_ai_layer";
import type { IntelEvidenceRef, IntelMemoryRow } from "@/lib/api/v1/types_intel";
import { t, translateOr } from "@/lib/i18n";
import { fmtPct, localFixed } from "@/lib/i18n/format";
import { toNum } from "./aiModel";

export const DASH = "—";

/** The aspects of a match that both sides report: a team's figures and its league's mean (corners, cards, expected goals). */
export const FIGURES = ["corners", "cards", "xg"] as const;

/** The kinds of memory a filter offers, besides the markets (``market:1X2``...), which the memory writes for teams and leagues. */
export const ASPECTS = [
  "corners",
  "cards",
  "xg",
  "market:1X2",
  "market:OU",
  "market:BTTS",
  "market:DC",
  "market:AH",
  "decisions",
  "discipline",
  "profile",
  "availability",
] as const;

/** Below LOW a series is a hint, from HIGH a pattern: the colour of its confidence. */
export const LOW = 0.4;
export const HIGH = 0.7;

/** The memory keeps at most this many ids of each kind of evidence, newest first (``fbi.intel.memory.MAX_SOURCES``). */
export const EVIDENCE_SAMPLE = 40;

type Stats = Record<string, unknown>;

function num(v: unknown): number | null {
  return toNum(v as number | string | null | undefined);
}

function fixed(v: unknown, digits = 2): string {
  const n = num(v);
  return n === null ? DASH : localFixed(n, digits);
}

export function isFigure(aspect: string): boolean {
  return (FIGURES as readonly string[]).includes(aspect);
}

export function aspectLabel(aspect: string): string {
  return translateOr(`memory.entities.aspects.${aspect}`, aspect);
}

// ── confidence ──────────────────────────────────────────────────────────────

export function confidenceTone(confidence: number | null): BadgeTone {
  if (confidence === null) return "neutral";
  return confidence >= HIGH ? "positive" : confidence >= LOW ? "info" : "warning";
}

/** A series written before memory-v4 has no confidence: it says "none", never a made-up number. */
export function confidenceText(confidence: number | null): string {
  return confidence === null ? t("memory.entities.legacy") : fmtPct(confidence, 0);
}

// ── the sample and the figures ──────────────────────────────────────────────

/** The number of decisions, matches or reports a series rests on. */
export function sampleOf(row: Pick<IntelMemoryRow, "stats">): number | null {
  const s = row.stats as Stats;
  return num(s["decisions"]) ?? num(s["matches"]) ?? num(s["reported_out"]);
}

/** A team's corners, cards or expected goals per match (its own and its rivals'), shrunk toward its league's, or a league's mean. */
export function figureText(row: Pick<IntelMemoryRow, "entity_type" | "stats">): string {
  const s = row.stats as Stats;
  if (row.entity_type === "competition")
    return num(s["rate"]) === null
      ? DASH
      : t("memory.entities.figureLeague", { rate: fixed(s["rate"]) });
  if (num(s["own_shrunk"]) !== null)
    return `${t("memory.entities.figureTeam", { own: fixed(s["own_shrunk"]), opp: fixed(s["opp_shrunk"]) })} (${t(
      "memory.entities.figurePrior",
      { prior: fixed(s["prior"]) },
    )})`;
  if (num(s["own_rate"]) !== null)
    return t("memory.entities.figureRaw", { own: fixed(s["own_rate"]), opp: fixed(s["opp_rate"]) });
  return DASH;
}

/** What a series says besides the numbers every row has, by kind of entity and aspect. */
export function detailOf(row: Pick<IntelMemoryRow, "entity_type" | "aspect" | "stats">): string {
  const s = row.stats as Stats;
  if (isFigure(row.aspect)) return figureText(row);
  if (row.entity_type === "referee")
    return t("intel.memory.refereeLine", {
      cards: fixed(s["cards_per_match"]),
      fouls: fixed(s["fouls_per_match"], 1),
    });
  if (row.entity_type === "coach") {
    const formations = Object.keys((s["formations"] ?? {}) as Record<string, number>)
      .slice(0, 2)
      .join(", ");
    return t("memory.entities.coachLine", {
      wins: String(s["wins"] ?? 0),
      draws: String(s["draws"] ?? 0),
      losses: String(s["losses"] ?? 0),
      formations: formations || DASH,
    });
  }
  if (row.entity_type === "player")
    return t("memory.entities.playerLine", {
      started: String(s["started_anyway"] ?? 0),
      out: String(s["reported_out"] ?? 0),
    });
  return DASH;
}

/** Wins / losses / voids of a series that settles decisions; a dash for the others. */
export function recordText(row: Pick<IntelMemoryRow, "stats">): string {
  const s = row.stats as Stats;
  return s["wins"] === undefined
    ? DASH
    : `${String(s["wins"])} / ${String(s["losses"] ?? 0)} / ${String(s["voids"] ?? 0)}`;
}

// ── evidence ────────────────────────────────────────────────────────────────

export type EvidenceKind = "fixtures" | "decisions" | "postmortems";

export interface EvidencePart {
  kind: EvidenceKind;
  ids: number[];
  text: string;
  /** The ids are a sample of the newest ones: there may be more evidence than there are ids. */
  sample: boolean;
}

/** What a series rests on, by kind: matches, or the decisions and the post-mortems that judged them. */
export function evidenceParts(ref: IntelEvidenceRef | null): EvidencePart[] {
  if (!ref) return [];
  return (["fixtures", "decisions", "postmortems"] as const).flatMap((kind) => {
    const ids = ref[kind] ?? [];
    return ids.length
      ? [
          {
            kind,
            ids,
            text: t(`memory.evidenceKinds.${kind}`, { count: ids.length }),
            sample: ids.length >= EVIDENCE_SAMPLE,
          },
        ]
      : [];
  });
}

// ── post-mortems ────────────────────────────────────────────────────────────

/** How a day's selections were judged and how its losses are classed: counts of what the list below shows. */
export function summarize(rows: PickPostmortem[]): {
  verdicts: Array<[string, number]>;
  classes: Array<[string, number]>;
} {
  const count = (keys: Array<string | null>): Array<[string, number]> => {
    const seen = new Map<string, number>();
    for (const k of keys) if (k) seen.set(k, (seen.get(k) ?? 0) + 1);
    return [...seen.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  };
  return {
    verdicts: count(rows.map((r) => r.verdict)),
    classes: count(rows.map((r) => r.classification)),
  };
}
