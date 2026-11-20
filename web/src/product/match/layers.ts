/**
 * The data layers of the line-up pitch (plan PM, PM-10-04, OP-23, lámina I02 «M02»; UX-176). Pure. Each starter's marker shows one
 * of four figures of his match - the provider's rating, his minutes, his cards, his goals and assists - read from the players' match
 * statistics (`core.fixture_player_stats`) and the events (`core.fixture_events`), never computed. The pitch keeps its rule: each
 * starter at the box the team sheet declares - «posición nominal de formación, no posición real».
 */
import type { ChartReview } from "@/components/analytics/evidence";
import type {
  LineupPlayer,
  MatchEvent,
  PlayerLine,
  Side,
  TeamLineup,
} from "@/lib/api/v1/types_center";
import { toNumber } from "@/lib/i18n/format";
import { eventKind, fmtDecimal, starters } from "./model";
import type { MarkerBadge } from "./Pitch";

export const LAYERS = ["rating", "minutes", "cards", "goalsAssists"] as const;
export type Layer = (typeof LAYERS)[number];

/** One starter's four figures; null where the provider gave nothing. */
export interface LayerFigures {
  rating: number | null;
  minutes: number | null;
  yellow: number;
  red: number;
  goals: number | null;
  assists: number | null;
}

function count(v: number | null | undefined): number | null {
  return v === null || v === undefined || !Number.isFinite(v) || v < 0 ? null : v;
}

/** The cards each player got, from the events that name him (a second yellow is a red). */
function cardsByPlayer(
  events: readonly MatchEvent[],
): Map<number, { yellow: number; red: number }> {
  const out = new Map<number, { yellow: number; red: number }>();
  for (const e of events) {
    if (e.player_id === null) continue;
    const kind = eventKind(e);
    if (kind !== "yellow" && kind !== "red" && kind !== "secondYellow") continue;
    const c = out.get(e.player_id) ?? { yellow: 0, red: 0 };
    if (kind === "yellow") c.yellow += 1;
    else c.red += 1;
    out.set(e.player_id, c);
  }
  return out;
}

/**
 * Each starter's figures, by the provider's player id. Cards come from the events when there are some (they say which card), else
 * from the player's statistics line.
 */
export function layerFigures(
  lineups: readonly TeamLineup[],
  players: readonly PlayerLine[],
  events: readonly MatchEvent[] | null,
): Map<number, LayerFigures> {
  const lines = new Map(players.map((p) => [p.provider_player_id, p]));
  const cards = events && events.length > 0 ? cardsByPlayer(events) : null;
  const out = new Map<number, LayerFigures>();
  for (const lineup of lineups) {
    for (const p of starters(lineup)) {
      const l = lines.get(p.provider_player_id);
      if (!l) continue;
      const fromEvents =
        cards && p.player_id !== null
          ? (cards.get(p.player_id) ?? { yellow: 0, red: 0 })
          : undefined;
      const rating = toNumber(l.rating);
      out.set(p.provider_player_id, {
        rating: rating !== null && rating > 0 && (l.minutes ?? 0) > 0 ? rating : null,
        minutes: count(l.minutes),
        yellow: fromEvents ? fromEvents.yellow : (count(l.yellow_cards) ?? 0),
        red: fromEvents ? fromEvents.red : (count(l.red_cards) ?? 0),
        goals: count(l.goals),
        assists: count(l.assists),
      });
    }
  }
  return out;
}

/**
 * Whether the layers have something to show: every starter of both sides has his statistics line. Without them the pitch is the
 * line-up alone (lámina I02; level C «solo alineación»).
 */
export function layersReady(
  lineups: readonly TeamLineup[],
  figures: Map<number, LayerFigures>,
): boolean {
  const xi = lineups.flatMap((l) => starters(l));
  return xi.length > 0 && xi.every((p) => figures.has(p.provider_player_id));
}

/** The highest rating of each side, for the gold edge (lámina I02: «valoración más alta del equipo»). */
export function bestRatings(
  lineups: readonly TeamLineup[],
  figures: Map<number, LayerFigures>,
): Record<Side, number | null> {
  const best: Record<Side, number | null> = { home: null, away: null };
  for (const l of lineups) {
    for (const p of starters(l)) {
      const r = figures.get(p.provider_player_id)?.rating ?? null;
      if (r !== null && (best[l.side] === null || r > (best[l.side] as number))) best[l.side] = r;
    }
  }
  return best;
}

/** «1 + 1», «0 + 0»; «—» when the provider gave neither. */
export function goalsAssistsText(f: LayerFigures): string {
  if (f.goals === null && f.assists === null) return "—";
  return `${f.goals ?? 0} + ${f.assists ?? 0}`;
}

/** What a marker carries for a layer; null leaves the marker without a badge (nothing to say, never a made-up zero). */
export function layerBadge(
  layer: Layer,
  f: LayerFigures | undefined,
  best: number | null,
  words: { yellowShort: string; redShort: string },
): MarkerBadge | null {
  if (!f) return null;
  switch (layer) {
    case "rating":
      return f.rating === null
        ? null
        : {
            text: fmtDecimal(f.rating, 1),
            tone: best !== null && f.rating === best ? "best" : undefined,
          };
    case "minutes":
      return f.minutes === null ? null : { text: `${f.minutes}'` };
    case "cards":
      if (f.red > 0) return { text: words.redShort, tone: "red" };
      if (f.yellow > 0) return { text: words.yellowShort, tone: "yellow" };
      return null;
    case "goalsAssists":
      return (f.goals ?? 0) + (f.assists ?? 0) > 0 ? { text: goalsAssistsText(f) } : null;
  }
}

/** A side's starters for the table, best rated first (the lámina's order); unrated after, by shirt number. */
export function tableRows(
  lineup: TeamLineup,
  figures: Map<number, LayerFigures>,
): { player: LineupPlayer; f: LayerFigures }[] {
  return starters(lineup)
    .flatMap((p) => {
      const f = figures.get(p.provider_player_id);
      return f ? [{ player: p, f }] : [];
    })
    .sort(
      (a, b) =>
        (b.f.rating ?? -1) - (a.f.rating ?? -1) ||
        (a.player.number ?? 99) - (b.player.number ?? 99),
    );
}

/** The hand review of the 14 checks (PM-10-06) for the layered pitch: the layer and team choices are radio buttons. */
export const LINEUP_LAYERS_REVIEW: ChartReview = {
  checks: {
    contraste: "ok",
    alternativa_textual: "ok",
    texto_minimo: "ok",
    sin_parpadeo: "ok",
    color_no_unico: "ok",
    teclado: "ok",
    foco_visible: "ok",
    instrucciones: "ok",
    titulo_y_resumen: "ok",
    incertidumbre: "ok",
    lenguaje_llano: "ok",
    tabla_equivalente: "ok",
    zoom_y_espaciado: "ok",
    lector_de_pantalla: "ok",
  },
  reviewedBy: "UX-176",
  reviewedOn: "2026-11-20",
};
