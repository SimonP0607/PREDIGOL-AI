/**
 * The shot funnel and the two shot zones of a match (plan PM, PM-10-01, OP-22, lámina I01 «M01»; FE-005). Pure: it reads the
 * match's team statistics as the detail delivers them (`core.fixture_team_stats`) and the goals of its events, and counts nothing
 * the provider did not give. The zones are the provider's two - inside and outside the box - and nothing more: this is not a shot
 * map (nobody knows where each shot was taken), and the piece says so.
 */
import type { ChartReview } from "@/components/analytics/evidence";
import type { MatchEvent, Side, TeamStatLine } from "@/lib/api/v1/types_center";
import { toNumber } from "@/lib/i18n/format";
import { eventKind, goalCredit, type Goals } from "../model";

export interface FunnelSide {
  shots: number;
  onTarget: number;
  /** Goals from the team's own shots (own goals of the rival left out when the events tell them apart). */
  goals: number;
}

export interface ZoneSide {
  inside: number;
  outside: number;
  blocked: number | null;
  /** API-Football's xG of the match; null when it was not delivered. */
  xg: number | null;
}

export interface ShotFunnel {
  home: FunnelSide;
  away: FunnelSide;
  /** Where the goals come from: the events (own goals told apart) or, without them, the final score. */
  goalsFrom: "events" | "score";
  /** Goals scored into their own net that the funnel leaves out, per side that benefited. */
  ownGoals: Goals;
}

export interface ShotZones {
  home: ZoneSide;
  away: ZoneSide;
}

function num(v: number | string | null | undefined): number | null {
  if (v === null || v === undefined) return null;
  const n = toNumber(v);
  return n === null || !Number.isFinite(n) || n < 0 ? null : n;
}

function lineOf(lines: readonly TeamStatLine[], side: Side): TeamStatLine | undefined {
  return lines.find((l) => l.side === side);
}

/** A kick of the shoot-out is not a shot of the match: the provider files it as a goal with this comment. */
function shootout(e: Pick<MatchEvent, "comments">): boolean {
  return (e.comments ?? "").toLowerCase().includes("shootout");
}

/**
 * The goals each side scored from its own shots. With the events, the scoring events credited to the side that took the shot
 * (an own goal counts for the rival but was not its shot: left out and reported apart), and only when they add up to the score;
 * otherwise the final score as it stands.
 */
export function funnelGoals(
  events: readonly MatchEvent[] | null,
  score: Goals | null,
): { goals: Goals; from: "events" | "score"; ownGoals: Goals } | null {
  const none: Goals = { home: 0, away: 0 };
  if (events && events.length > 0) {
    const play = events.filter((e) => !shootout(e));
    const { credit, reliable } = goalCredit(play, score);
    if (reliable) {
      const goals: Goals = { home: 0, away: 0 };
      const own: Goals = { home: 0, away: 0 };
      for (const e of play) {
        const to = credit.get(e.seq);
        if (!to) continue;
        const kind = eventKind(e);
        if (kind === "ownGoal") own[to] += 1;
        else if (kind === "goal" || kind === "penalty") goals[to] += 1;
      }
      return { goals, from: "events", ownGoals: own };
    }
  }
  return score ? { goals: { ...score }, from: "score", ownGoals: none } : null;
}

/**
 * The funnel - shots, on target, goals - for both sides, or null when a side lacks shots or shots on target, or when its figures
 * contradict each other (more on target than shots, more goals than on target): a funnel that does not narrow is not drawn.
 */
export function shotFunnel(
  lines: readonly TeamStatLine[],
  events: readonly MatchEvent[] | null,
  score: Goals | null,
): ShotFunnel | null {
  const g = funnelGoals(events, score);
  if (!g) return null;
  const side = (s: Side): FunnelSide | null => {
    const l = lineOf(lines, s);
    const shots = num(l?.shots);
    const onTarget = num(l?.shots_on_target);
    if (shots === null || onTarget === null) return null;
    const goals = g.goals[s];
    if (onTarget > shots || goals > onTarget) return null;
    return { shots, onTarget, goals };
  };
  const home = side("home");
  const away = side("away");
  if (!home || !away) return null;
  return { home, away, goalsFrom: g.from, ownGoals: g.ownGoals };
}

/** The two zones for both sides, or null when a side lacks either of them or took no shot in them. */
export function shotZones(lines: readonly TeamStatLine[]): ShotZones | null {
  const side = (s: Side): ZoneSide | null => {
    const l = lineOf(lines, s);
    const inside = num(l?.shots_inside_box);
    const outside = num(l?.shots_outside_box);
    if (inside === null || outside === null) return null;
    return { inside, outside, blocked: num(l?.shots_blocked), xg: num(l?.expected_goals) };
  };
  const home = side("home");
  const away = side("away");
  if (!home || !away) return null;
  if (home.inside + home.outside === 0 && away.inside + away.outside === 0) return null;
  return { home, away };
}

/** A share of a whole as a whole percentage (0-100), or null when there is no whole. */
export function share(part: number, whole: number): number | null {
  return whole > 0 ? Math.round((100 * part) / whole) : null;
}

/** xG per shot, when both are known and there was a shot. */
export function xgPerShot(xg: number | null, shots: number): number | null {
  return xg !== null && shots > 0 ? xg / shots : null;
}

/** Who gave the figures: API-Football, or football-data.co.uk when it is the only source. */
export function statSource(lines: readonly TeamStatLine[]): "api_football" | "football_data" {
  return lines.some((l) => (l.source ?? "").includes("football-data"))
    ? "football_data"
    : "api_football";
}

/** The hand review of the 14 checks (PM-10-06) for both cards: static, keyboard only for the table's toggle. */
export const SHOT_FUNNEL_REVIEW: ChartReview = {
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
  reviewedBy: "FE-005",
  reviewedOn: "2026-11-20",
};
