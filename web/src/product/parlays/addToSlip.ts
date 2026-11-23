/**
 * «Añadir a Mi parlay» on a parlay PrediGol recorded (plan AP-L03): its legs that are still to be played go into the reader's
 * slip, beside what is already there. Nothing is replaced: a leg already in the slip stays as it is, a match that already has
 * another selection in the slip is not touched (one selection per match), a leg whose match has started or whose market the
 * slip does not take is left out, and when the slip is full the rest stays out. What was left out is counted, so the screen
 * can say it. Mi parlay itself does not change: this only builds the list it is given.
 */
import type { ParlayRecordLeg } from "@/lib/api/v1/types_records";
import { isParlayMarket } from "@/product/odds/parlay";
import {
  MAX_SLIP_LEGS,
  hasStarted,
  normLine,
  selectionKey,
  type SlipLeg,
} from "@/product/records/model";

export interface Merge {
  legs: SlipLeg[];
  added: number;
  /** Already in the slip, in the same selection. */
  already: number;
  started: number;
  /** The slip has another selection of that match. */
  sameMatch: number;
  /** A market the slip does not take. */
  unsupported: number;
  /** The slip was full. */
  full: number;
}

export function mergeParlay(
  current: readonly SlipLeg[],
  parlay: readonly ParlayRecordLeg[],
  now: number = Date.now(),
): Merge {
  const out: SlipLeg[] = [...current];
  const merge: Merge = {
    legs: out,
    added: 0,
    already: 0,
    started: 0,
    sameMatch: 0,
    unsupported: 0,
    full: 0,
  };
  for (const leg of parlay) {
    const m = leg.match;
    if (hasStarted(m, now)) {
      merge.started += 1;
      continue;
    }
    if (!isParlayMarket(leg.market_key)) {
      merge.unsupported += 1;
      continue;
    }
    const base = {
      fixture_id: m.fixture_id,
      market_key: leg.market_key,
      selection: leg.selection,
      line: normLine(leg.line),
    };
    const key = selectionKey(base);
    if (out.some((x) => x.key === key)) {
      merge.already += 1;
      continue;
    }
    if (out.some((x) => x.fixture_id === m.fixture_id)) {
      merge.sameMatch += 1;
      continue;
    }
    if (out.length >= MAX_SLIP_LEGS) {
      merge.full += 1;
      continue;
    }
    out.push({
      ...base,
      key,
      home: m.home.name,
      away: m.away.name,
      kickoff_at: m.kickoff_at,
      odds: leg.odds,
      bookmaker: leg.bookmaker,
      p_model: leg.p_model,
    });
    merge.added += 1;
  }
  return merge;
}

/** How many legs of the parlay can still be added: the button is shown only when there is at least one. */
export function addable(
  current: readonly SlipLeg[],
  parlay: readonly ParlayRecordLeg[],
  now: number = Date.now(),
): number {
  return mergeParlay(current, parlay, now).added;
}
