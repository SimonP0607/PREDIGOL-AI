/** A selection's place in "Mi parlay": whether it is in, whether it can be added now, and the toggle. */
import { useContext } from "react";
import { t } from "@/lib/i18n";
import { selectionKey } from "@/product/records/model";
import { SlipContext } from "@/product/records/slipContext";
import { parlayBlock, type NewLeg, type ParlayBlock } from "./parlay";

export interface ParlayLegState {
  inSlip: boolean;
  /** Why it cannot be added now; null when it can. A leg already in the slip can always be removed. */
  block: ParlayBlock | null;
  /** Another selection of the same match is in the slip: adding this one replaces it. */
  replaces: boolean;
  toggle: () => void;
}

/** A tap does something: the selection can be added now, or it is in the slip and can be taken out. */
export function isToggleable(state: ParlayLegState | null): boolean {
  return state !== null && (state.block === null || state.inSlip);
}

/** Why a shown price cannot go in the parlay, when the reader should be told: a quarter line, kicked off. */
export function blockedText(state: ParlayLegState | null): string | null {
  if (!state || state.inSlip) return null;
  if (state.block === "quarter") return t("records.actions.quarterLine");
  if (state.block === "started") return t("records.actions.started");
  return null;
}

/**
 * Null without a leg, or outside the slip's provider (a page with no parlay): nothing to toggle there,
 * where useSlip() would throw.
 */
export function useParlayLeg(
  leg: NewLeg | null,
  statusGroup?: string | null | undefined,
): ParlayLegState | null {
  const slip = useContext(SlipContext);
  if (!slip || !leg) return null;
  const inSlip = slip.has(selectionKey(leg));
  return {
    inSlip,
    block: parlayBlock({ ...leg, status_group: statusGroup }),
    replaces: !inSlip && slip.legs.some((l) => l.fixture_id === leg.fixture_id),
    toggle: () => slip.toggle(leg),
  };
}
