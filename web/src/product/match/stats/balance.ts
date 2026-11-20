/**
 * The balance of a match and the strip of the score's state (plan PM, PM-10-02, OP-25, lámina I01 «M04»; FE-006). Pure.
 *
 * - The balance shares out between the two sides the match's totals of possession, shots, shots inside the box and corners
 *   (`core.fixture_team_stats` via the match detail). It says who had more of each, not where on the pitch the match was played:
 *   «dominio aproximado; no es field tilt».
 * - The strip says who was ahead, minute by minute, over the 90 minutes, from the goals of the match's events
 *   (`core.fixture_events`) - the same count and drawing as the Postpartido's «Cómo fue el marcador» (`knowledge.ts`). Drawn only
 *   when the events add up to the score; extra time and the shoot-out are not part of it, and the piece says so.
 */
import type { ChartReview } from "@/components/analytics/evidence";
import type { MatchEvent, TeamStatLine } from "@/lib/api/v1/types_center";
import { toNumber } from "@/lib/i18n/format";
import {
  chronological,
  eventKind,
  goalCredit,
  isScoring,
  type Goals,
  type StatRow,
} from "../model";
import { leadMinutes, leadTimeline, storyDrawing, type StoryDrawing } from "../knowledge";

/** The rows of the balance, in the lámina's order. */
export const BALANCE_KEYS = ["possession", "shots", "shotsInsideBox", "corners"] as const;
export type BalanceKey = (typeof BALANCE_KEYS)[number];

const FIELD: Record<BalanceKey, keyof TeamStatLine> = {
  possession: "possession_pct",
  shots: "shots",
  shotsInsideBox: "shots_inside_box",
  corners: "corners",
};

function num(v: unknown): number | null {
  if (v === null || v === undefined || typeof v === "boolean") return null;
  const n = toNumber(v as number | string);
  return n === null || !Number.isFinite(n) || n < 0 ? null : n;
}

/**
 * The balance: each figure both sides have, as a row. Null with fewer than two rows - one figure is not a balance - and a row
 * where neither side has any (0 against 0) says nothing and is left out.
 */
export function balanceRows(lines: readonly TeamStatLine[]): StatRow[] | null {
  const home = lines.find((l) => l.side === "home");
  const away = lines.find((l) => l.side === "away");
  if (!home || !away) return null;
  const rows: StatRow[] = [];
  for (const key of BALANCE_KEYS) {
    const h = num(home[FIELD[key]]);
    const a = num(away[FIELD[key]]);
    if (h === null || a === null || h + a === 0) continue;
    rows.push({ key, format: key === "possession" ? "pct" : "int", home: h, away: a });
  }
  return rows.length >= 2 ? rows : null;
}

/** A side's share of the pair (0-100), for the bar's width. */
export function pairShare(row: StatRow, side: "home" | "away"): number {
  const h = row.home ?? 0;
  const a = row.away ?? 0;
  const total = h + a;
  if (total <= 0) return 0;
  return ((side === "home" ? h : a) / total) * 100;
}

export interface ScoreState {
  drawing: StoryDrawing;
  /** The match went to extra time (or a shoot-out): the strip is the 90 minutes and says so. */
  beyond90: boolean;
  goals: number;
}

function period(e: MatchEvent): "1H" | "2H" | "ET" {
  if (e.minute <= 45) return "1H";
  if (e.minute <= 90) return "2H";
  return "ET";
}

function shootout(e: MatchEvent): boolean {
  return (e.comments ?? "").toLowerCase().includes("shootout");
}

/**
 * Who was ahead over the 90 minutes, from the match's events. Null without events, or when the goals do not add up to the final
 * score (`goalCredit` cannot tell who each one counts for): a picture must never say more than the numbers.
 */
export function scoreState(
  events: readonly MatchEvent[] | null,
  score: Goals | null,
  reachedExtraTime = false,
): ScoreState | null {
  if (!events || !score) return null;
  const play = events.filter((e) => !shootout(e));
  const { credit, reliable } = goalCredit(play, score);
  if (!reliable) return null;
  const goals = chronological(play).flatMap((e) => {
    const side = credit.get(e.seq);
    if (!side || !isScoring(eventKind(e))) return [];
    return [{ period: period(e), minute: e.minute, side }];
  });
  const minutes = leadMinutes(leadTimeline(goals));
  const beyond90 = reachedExtraTime || events.some((e) => e.minute > 90 || shootout(e));
  return { drawing: storyDrawing({ minutes }, goals), beyond90, goals: goals.length };
}

/** The hand review of the 14 checks (PM-10-06) for the balance and the strip: static; keyboard only for the table's toggle. */
export const MATCH_BALANCE_REVIEW: ChartReview = {
  checks: {
    contraste: "ok",
    alternativa_textual: "ok",
    texto_minimo: "ok",
    sin_parpadeo: "ok",
    color_no_unico: "ok",
    teclado: "ok",
    foco_visible: "ok",
    instrucciones: "no_aplica",
    titulo_y_resumen: "ok",
    incertidumbre: "ok",
    lenguaje_llano: "ok",
    tabla_equivalente: "ok",
    zoom_y_espaciado: "ok",
    lector_de_pantalla: "ok",
  },
  reviewedBy: "FE-006",
  reviewedOn: "2026-11-20",
};
