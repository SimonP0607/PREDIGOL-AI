/**
 * «Explícame» (plan UX, B9), as the API returns it. Mirrors fbi.api.contracts.explain: the answer to one frequent question of a
 * match, a pick or the parlay being built, from what PrediGol already keeps - no AI. Every line is a stable code the page words
 * in the reader's language (src/product/explain/text.ts) or a fact of the match's structured reading, written with the reading's
 * own template. ``answered=false``: PrediGol does not have what the question needs, and the lines say what is missing.
 */
import type { ReadingFact } from "./types_reading";

export type ExplainEntity = "match" | "pick" | "parlay";
export type ExplainIntent = "no_pick" | "forecast" | "risks" | "caution" | "probability";
export type ExplainLink = "transparency" | "why_pick" | "glossary";
export type ExplainParam = string | number | boolean | string[] | number[] | null;

export interface ExplainLine {
  /** explain.say.<code>; null when the line is a fact of the reading. */
  say: string | null;
  params: Record<string, ExplainParam>;
  fact: ReadingFact | null;
}

export interface Explanation {
  /** The rules that wrote it: explain-v1. */
  version: string;
  entity: ExplainEntity;
  /** The match or the pick; null for the parlay being built. */
  item_id: number | null;
  intent: ExplainIntent;
  answered: boolean;
  lines: ExplainLine[];
  /** Glossary terms worth a tap (keys of src/lib/glossary). */
  terms: string[];
  links: ExplainLink[];
}

/** A leg of the parlay being built, as the slip holds it (the body of POST /explain/parlay, as POST /me/parlays/validate's). */
export interface SlipLegBody {
  fixture_id: number;
  market_key: string;
  selection: string;
  line: string | number;
}
