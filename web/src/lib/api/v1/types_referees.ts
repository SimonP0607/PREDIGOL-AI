/**
 * Referees as people (plan F3): what `/admin/referees` answers. A referee is a person; the strings the provider wrote for him are his
 * spellings (aliases); what the rules are not sure of waits in the queue as a pair. Mirrors backend `fbi.api.contracts.referees`.
 */

export type PairStatus = "open" | "rejected" | "merged";
export type RefereeStatus = "active" | "merged";
export type RefereeActionName = "merge" | "undo" | "split" | "reject" | "reopen" | "rename";

export interface RefereeSummary {
  id: number;
  /** The fullest spelling the provider used, or the name an owner gave him. */
  name: string;
  country: string | null;
  status: RefereeStatus;
  merged_into: number | null;
  /** An owner chose the name: the rules no longer change it. */
  name_locked: boolean;
  matches: number;
  first_match: string | null;
  last_match: string | null;
}

export interface RefereeAlias {
  id: number;
  display: string;
  name_key: string;
  country: string | null;
  /** identity, extension, initial, visitor, scope or manual. */
  basis: string;
  /** `rules` or `manual`. */
  placed_by: string;
  matches: number;
  first: string | null;
  last: string | null;
}

export interface RefereeMatch {
  fixture_id: number;
  kickoff_at: string | null;
  home: string;
  away: string;
  competition: string;
  season: number;
  /** How the provider wrote his name for this match. */
  spelling: string;
}

export interface RefereeSide {
  id: number;
  name: string;
  country: string | null;
  matches: number;
}

interface Doubt {
  /** Why the rules doubt: the two are one name apart, an initial fits two, they never share a day... */
  reason: string;
  score: number;
  /** Matches the doubt touches (the smaller side's): what the queue is ordered by. */
  impact: number;
  evidence: Record<string, unknown>;
  status: PairStatus;
  decided_by: string | null;
  decided_at: string | null;
}

export interface RefereePair extends Doubt {
  id: number;
  a: RefereeSide;
  b: RefereeSide;
}

export interface RefereeCandidate extends Doubt {
  id: number;
  other: RefereeSide;
}

export interface RefereeEvent {
  id: number;
  at: string;
  /** `admin:<email>`, `script:referee_identity` or `rules`. */
  actor: string;
  action: RefereeActionName;
  referee_id: number | null;
  other_id: number | null;
  alias_ids: number[];
  /** The event that took this merge back. */
  undone_by: number | null;
  detail: Record<string, unknown>;
}

export interface RefereeCounts {
  referees_active: number;
  referees_merged: number;
  aliases: number;
  fixtures_with_referee: number;
  candidates_open: number;
  candidates_rejected: number;
  candidates_merged: number;
  matches_with_a_doubt: number;
  /** Share of the matches with a referee whose referee has no doubt waiting. */
  settled_share: number;
  /** Invariants of the tables that do not hold (empty when all is well). */
  problems: string[];
}

export interface RefereeList {
  items: RefereeSummary[];
  total: number;
  queue_open: number;
  counts: RefereeCounts;
}

export interface RefereeQueue {
  items: RefereePair[];
  total: number;
  status: PairStatus;
  reason: string | null;
}

export interface RefereeDetail {
  referee: RefereeSummary;
  aliases: RefereeAlias[];
  recent_matches: RefereeMatch[];
  candidates: RefereeCandidate[];
  events: RefereeEvent[];
}

export interface RefereeActionResult {
  action: RefereeActionName;
  /** The event the action wrote (what `undo` of a merge takes). */
  event_id: number | null;
  /** The referee the action leaves in front: the one kept, the new one, the one renamed. */
  referee_id: number;
  other_id: number | null;
  referee: RefereeSummary;
}

/** Bodies of the decisions. */
export interface RefereeMergeBody {
  merge_id: number;
  note?: string | undefined;
  force?: boolean | undefined;
}
export interface RefereeSplitBody {
  alias_ids: number[];
  name?: string | undefined;
  note?: string | undefined;
}
export interface RefereePairBody {
  other_id: number;
  note?: string | undefined;
}
export interface RefereeRenameBody {
  /** null gives the naming back to the rules. */
  name: string | null;
}
