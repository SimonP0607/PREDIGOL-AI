/**
 * Postpartido (plan UX, B4): what a finished match did to what the reader saved and to PrediGol's published picks - the
 * backend's contracts/postmatch.py. The why of a pick is the match's own facts as the post-mortem found them, as codes and
 * figures that the web words with its own templates; what the post-mortem judges has no field here.
 */
import type { UserPick } from "./types_records";

type Dec = string;
type Iso = string;

export type CauseCode =
  | "red_card"
  | "penalty_scored"
  | "penalty_missed"
  | "early_goal"
  | "early_substitution"
  | "cards_above_referee"
  | "cards_below_referee"
  | "xg_supported"
  | "xg_against";

export type CauseEffect = "for" | "against" | "neutral";

export type PickResult = "pending" | "win" | "loss" | "push" | "void" | "half_win" | "half_loss";

/** One fact of the match behind a pick's result, as figures. */
export interface PostmatchCause {
  code: CauseCode;
  /** Whether it played for the selection, against it, or neither. */
  effect: CauseEffect;
  minute: number | null;
  side: "home" | "away" | null;
  /** early_substitution: how many changes before minute 30. */
  n: number | null;
  /** cards_*: the cards of the match and the referee's average. */
  cards: number | null;
  referee_avg: number | null;
  /** xg_*: the expected goals of each side and the score they are set against. */
  xg_home: number | null;
  xg_away: number | null;
  score: string | null;
}

/** A pick PrediGol published for the match, how it ended and why (the owner's preview adds the shadow ones). */
export interface PostmatchPick {
  pick_id: number;
  market_key: string;
  selection: string;
  line: Dec;
  status: "shadow" | "qualified" | "published";
  /** The settlement; null until the match has one. */
  result: PickResult | null;
  /** PrediGol's probability when it was published. */
  p_model: Dec;
  /** The market's fair probability at its close (null: no close was kept). */
  p_close: Dec | null;
  /** The post-mortem has looked at it and saw the settlement's outcome (written the night after the match). */
  analysed: boolean;
  analysed_at: Iso | null;
  /** The facts behind the result, the most telling first; empty when nothing out of the ordinary happened. */
  causes: PostmatchCause[];
}

export interface PostMatch {
  version: string;
  fixture_id: number;
  kickoff_at: Iso;
  /** The match is over (one waiting for its result says false, and nothing is settled). */
  finished: boolean;
  /** What this reader saved on the match, with its result and units once settled. */
  saved: UserPick[];
  /** PrediGol's published picks of the match, how each ended and why. */
  published: PostmatchPick[];
}
