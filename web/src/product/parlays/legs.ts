/**
 * A parlay's leg as every full parlay view draws it (LegRow): from PrediGol's recorded parlays (frozen when built)
 * and from the automatic builder (priced now). Pure, so the shapes are tested apart from the components.
 */
import type { Dec } from "@/lib/api/v1/types";
import type { BuilderLeg } from "@/lib/api/v1/types_builder";
import type { CompetitionBadge, TeamBadge } from "@/lib/api/v1/types_product";
import type { MarketKey, ParlayRecordLeg } from "@/lib/api/v1/types_records";
import type { Pickable } from "@/product/records/pickable";
import { selectionLabel } from "@/product/shared/markets";
import type { WhyNumbers } from "./LegWhy";

export interface LegView {
  n: number;
  fixture_id: number;
  kickoff_at: string;
  status_group?: string | null | undefined;
  competition: CompetitionBadge;
  home: TeamBadge;
  away: TeamBadge;
  score: { home: number; away: number } | null;
  market_key: string;
  selection: string;
  line: Dec;
  odds: Dec;
  bookmaker: string | null;
  pick_id?: number | null | undefined;
  why: WhyNumbers;
  /** PrediGol's recorded parlay: the price it was taken at. */
  frozen: boolean;
}

export function legLabel(
  leg: Pick<LegView, "market_key" | "selection" | "line" | "home" | "away">,
) {
  return selectionLabel({
    market_key: leg.market_key,
    selection: leg.selection,
    line: leg.line,
    home: leg.home.name,
    away: leg.away.name,
  });
}

export function pickableOfView(leg: LegView): Pickable {
  return {
    fixture_id: leg.fixture_id,
    market_key: leg.market_key as MarketKey,
    selection: leg.selection,
    line: leg.line,
    kickoff_at: leg.kickoff_at,
    status_group: leg.status_group,
    home: leg.home.name,
    away: leg.away.name,
    odds: leg.odds,
    bookmaker: leg.bookmaker,
    pick_id: leg.pick_id ?? null,
    p_model: leg.why.p_model,
  };
}

export function viewOfRecord(leg: ParlayRecordLeg): LegView {
  const m = leg.match;
  return {
    n: leg.leg_no,
    fixture_id: m.fixture_id,
    kickoff_at: m.kickoff_at,
    status_group: m.status_group,
    competition: m.competition,
    home: m.home,
    away: m.away,
    score:
      m.score_home !== null && m.score_away !== null
        ? { home: m.score_home, away: m.score_away }
        : null,
    market_key: leg.market_key,
    selection: leg.selection,
    line: leg.line,
    odds: leg.odds,
    bookmaker: leg.bookmaker,
    pick_id: leg.pick_id,
    why: {
      p_model: leg.p_model,
      p_low: leg.p_low,
      p_market: leg.p_market,
      odds: leg.odds,
      ev: leg.ev,
      ai: leg.ai ?? null,
    },
    frozen: true,
  };
}

export function viewOfBuilt(leg: BuilderLeg, n: number): LegView {
  return {
    n,
    fixture_id: leg.fixture_id,
    kickoff_at: leg.kickoff_at,
    competition: leg.competition,
    home: leg.home,
    away: leg.away,
    score: null,
    market_key: leg.market_key,
    selection: leg.selection,
    line: leg.line,
    odds: leg.odds,
    bookmaker: leg.bookmaker,
    pick_id: leg.pick_id,
    why: {
      p_model: leg.p_model,
      p_low: leg.p_low,
      p_market: leg.p_market,
      odds: leg.odds,
      ev: leg.ev,
      books: leg.n_bookmakers,
      ai: leg.ai ?? null,
    },
    frozen: false,
  };
}
