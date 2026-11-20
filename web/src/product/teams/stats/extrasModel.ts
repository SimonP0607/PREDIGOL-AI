/**
 * What the player's profile adds with the data PrediGol keeps and no page showed (plan PM, PM-08-06; UX-180; lámina I06): for a
 * goalkeeper, «Bajo los palos» (saves, the share of shots on target he saved, goals conceded - C-13's template of his position - and
 * the penalties he saved) and «Con el balón»; for every player, penalties won and committed, offsides and times dribbled past (C-13
 * 1.1.0 `provider_extras`, «dato de API-Football»). Pure.
 *
 * Each block follows the level of the competition's player data in C-16 when it is published: A or B shows it, C shows it saying it
 * is partial, D or a short sample does not draw it and says so. A figure the season reports in too few matches keeps its reason
 * (sin_cobertura, sin_datos) and is never drawn as a zero. A goalkeeper's goals prevented are not drawn: the provider's field did not
 * pass its quality probe (PM-05-05), and the page says so.
 */
import type { CoverageLevel } from "@/lib/api/v1/types_availability";
import { isMissing, type Maybe, type Missing } from "@/lib/api/v1/types_intelligence";
import type { PlayerBody, ProviderFigure, StatFigure } from "@/lib/api/v1/types_stats";

export interface ShownFigure {
  key: string;
  value: number | null;
  /** Why there is no value (sin_datos, sin_cobertura, muestra_insuficiente). */
  missing: Missing["missing_reason"] | null;
  unit: "por_90" | "total" | "por_partido" | "porcentaje";
  /** The league's value for the position, when the figure has one (C-13 template). */
  league: number | null;
  matches: number;
  origin: "predigol" | "api_football";
}

export type BlockState = "visible" | "parcial" | "no_ofrece" | "muestra_corta";

export interface PlayerExtrasView {
  keeper: boolean;
  /** «Bajo los palos»: only a goalkeeper's. */
  underPosts: ShownFigure[];
  /** «Con el balón»: a goalkeeper's passes against the league's goalkeepers. */
  withBall: ShownFigure[];
  /** Penalties and offsides: every player's. */
  discipline: ShownFigure[];
  state: BlockState;
  /** The sample the figures stand on: matches and minutes of the competition season. */
  sample: { appearances: number; minutes: number; nineties: number; minNineties: number };
  /** A goalkeeper's goals prevented: not drawn until the provider's field passes its probe. */
  goalsPreventedHeld: boolean;
}

function value(v: Maybe<number>): {
  value: number | null;
  missing: Missing["missing_reason"] | null;
} {
  return isMissing(v) ? { value: null, missing: v.missing_reason } : { value: v, missing: null };
}

function fromStat(f: StatFigure): ShownFigure {
  return {
    key: f.key,
    ...value(f.value),
    unit: f.unit,
    league: isMissing(f.league_value) ? null : f.league_value,
    matches: f.matches_with_data,
    origin: "predigol",
  };
}

function fromProvider(f: ProviderFigure): ShownFigure {
  return {
    key: f.key,
    ...value(f.value),
    unit: f.unit,
    league: null,
    matches: f.matches_with_data,
    origin: "api_football",
  };
}

const KEEPER_POSTS = ["saves", "save_pct", "goals_conceded"] as const;
const KEEPER_BALL = ["passes", "pass_accuracy"] as const;
const FOR_ALL = ["penalties_won", "penalties_committed", "offsides", "dribbled_past"] as const;

/** The state of the blocks from the level of the competition's player data (null: C-16 not published) and the sample. */
export function blockState(level: CoverageLevel | null, thin: boolean): BlockState {
  if (level === "D") return "no_ofrece";
  if (level === "MI" || thin) return "muestra_corta";
  if (level === "C") return "parcial";
  return "visible";
}

export function playerExtrasView(body: PlayerBody, level: CoverageLevel | null): PlayerExtrasView {
  const keeper = !isMissing(body.position) && body.position === "portero";
  const figures = new Map(body.figures.map((f) => [f.key, f]));
  const extras = new Map((body.provider_extras ?? []).map((f) => [f.key, f]));
  const pick = <K extends string>(keys: readonly K[]): ShownFigure[] =>
    keys.flatMap((k) => {
      const f = figures.get(k);
      return f ? [fromStat(f)] : [];
    });
  const underPosts = keeper ? pick(KEEPER_POSTS) : [];
  const saved = extras.get("penalties_saved");
  if (keeper && saved) underPosts.push(fromProvider(saved));
  const discipline = FOR_ALL.flatMap((k) => {
    const f = extras.get(k);
    return f ? [fromProvider(f)] : [];
  });
  const thin = body.nineties < body.min_nineties;
  return {
    keeper,
    underPosts,
    withBall: keeper ? pick(KEEPER_BALL) : [],
    discipline,
    state: blockState(level, thin),
    sample: {
      appearances: body.appearances,
      minutes: body.minutes,
      nineties: body.nineties,
      minNineties: body.min_nineties,
    },
    goalsPreventedHeld: keeper,
  };
}

/** Whether a block has anything to draw: a block whose every figure is missing is said in one line, never drawn empty. */
export function hasValues(figures: readonly ShownFigure[]): boolean {
  return figures.some((f) => f.value !== null);
}
