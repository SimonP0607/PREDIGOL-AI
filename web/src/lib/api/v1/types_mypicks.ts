/**
 * Mis picks completo (plan UX, B5, section 30): the totals and the breakdown of the reader's own saved picks under the
 * filter they chose - always with their sample - and the line value of their prices. Mirrors
 * backend/src/fbi/api/contracts/mypicks.py.
 */
import type { Dec } from "./types";
import type { CompetitionBadge } from "./types_product";

export type PickResult = "pending" | "won" | "lost" | "push" | "void";
export type PickOrigin = "predigol" | "mine";
export type OddsBand = "lt1.5" | "1.5-2" | "2-3" | "3-5" | "5+";
/** counts_only below min_sample settled picks; inconclusive below `conclusive`; conclusive from there. */
export type PicksSample = "counts_only" | "inconclusive" | "conclusive";

export const ODDS_BANDS: readonly OddsBand[] = ["lt1.5", "1.5-2", "2-3", "3-5", "5+"];

/** The filter of Mis picks: the same for the list, its totals and breakdown, and its CSV. */
export interface MyPicksFilter {
  result?: PickResult | null;
  market?: string | null;
  competition?: number | null;
  origin?: PickOrigin | null;
  band?: OddsBand | null;
  /** The first and the last day of the matches (YYYY-MM-DD), in the reader's time zone. */
  since?: string | null;
  until?: string | null;
  /** Found in the teams' or the league's names, without accents. */
  q?: string | null;
}

/** Counted as Mis picks counts everywhere; below min_sample settled picks only the counts (units, ROI, hit rate, margin: null). */
export interface PicksTally {
  total: number;
  pending: number;
  won: number;
  lost: number;
  half_won: number;
  half_lost: number;
  push: number;
  void: number;
  /** Settled with a stake: the n of the sample. */
  settled: number;
  units: Dec | null;
  /** A share. */
  roi: Dec | null;
  /** ± one standard error of the ROI, a share (1 / sqrt(settled)). */
  margin: Dec | null;
  hit_rate: Dec | null;
  sample: PicksSample;
}

export interface MarketRow extends PicksTally {
  market: string;
}

export interface CompetitionRow extends PicksTally {
  competition: CompetitionBadge;
}

export interface BandRow extends PicksTally {
  band: OddsBand;
}

/** The reader's prices against the close (clv-v1): odds × p_close − 1. */
export interface MyLineValue {
  version: string;
  since: string;
  n: number;
  mean: Dec | null;
  positive: Dec | null;
  minutes: number | null;
}

export interface AppliedFilter {
  result: PickResult | null;
  market: string | null;
  competition: number | null;
  origin: PickOrigin | null;
  band: OddsBand | null;
  since: string | null;
  until: string | null;
  search: string | null;
  active: number;
}

export interface PicksSummary {
  timezone: string;
  min_sample: number;
  conclusive: number;
  filter: AppliedFilter;
  tally: PicksTally;
  markets: MarketRow[];
  competitions: CompetitionRow[];
  bands: BandRow[];
  line_value: MyLineValue;
  options: { markets: string[]; competitions: CompetitionBadge[] };
  definitions: Array<{ key: "roi" | "sample" | "line_value"; version: string; since: string }>;
}
