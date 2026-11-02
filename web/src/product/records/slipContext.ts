/** The parlay slip's context: read it with useSlip() anywhere under SlipProvider. */
import { createContext, useContext } from "react";
import type { SlipLeg } from "./model";

export interface SlipValue {
  legs: SlipLeg[];
  has: (key: string) => boolean;
  toggle: (leg: Omit<SlipLeg, "key">) => void;
  remove: (key: string) => void;
  clear: (quiet?: boolean) => void;
  /** Replace the legs with these (the automatic builder's parlay, to change before saving). */
  load: (legs: SlipLeg[]) => void;
  /** Legs just taken out that can still be put back (for UNDO_MS), or null. */
  undo: { effect: "removed" | "cleared"; count: number } | null;
  /** Put them back: the slip as it was before they went. */
  restore: () => void;
  open: boolean;
  setOpen: (open: boolean) => void;
}

export const SlipContext = createContext<SlipValue | null>(null);

export function useSlip(): SlipValue {
  const value = useContext(SlipContext);
  if (!value) throw new Error("useSlip outside SlipProvider");
  return value;
}
