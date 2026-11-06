/**
 * The parlay a user is assembling, across pages: one leg per match, at most ten. It lives in
 * this tab's session storage (a list of selections - nothing sensitive) until it is saved
 * as a parlay or cleared; the server validates it again before storing anything.
 *
 * Taking legs out can be undone for five seconds (plan UX, A1, defect F53): a leg removed or the slip cleared is
 * offered back - in a notice with "Deshacer" while the slip is closed, in the slip itself while it is open. Any
 * later change withdraws the offer, so what comes back is the slip exactly as it was.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { t } from "@/lib/i18n";
import {
  MAX_SLIP_LEGS,
  UNDO_MS,
  parseSlip,
  slipReduce,
  undoOf,
  type SlipAction,
  type SlipLeg,
  type SlipUndo,
} from "./model";
import { SlipContext, type SlipValue } from "./slipContext";
import { track } from "@/lib/track";

const KEY = "predigol.slip";

function read(): SlipLeg[] {
  try {
    return parseSlip(window.sessionStorage.getItem(KEY));
  } catch {
    return [];
  }
}

function write(legs: SlipLeg[]): void {
  try {
    if (legs.length === 0) window.sessionStorage.removeItem(KEY);
    else window.sessionStorage.setItem(KEY, JSON.stringify(legs));
  } catch {
    /* storage unavailable: the slip lasts for this page only */
  }
}

export function SlipProvider({ children }: { children: ReactNode }) {
  const [legs, setLegs] = useState<SlipLeg[]>(read);
  const [open, setOpenState] = useState(false);
  const [undo, setUndo] = useState<SlipUndo | null>(null);
  const current = useRef(legs);
  const shown = useRef(false);
  const offer = useRef<{ undo: SlipUndo; timer: number; toast: string | number | null } | null>(
    null,
  );

  const withdraw = useCallback(() => {
    const was = offer.current;
    if (!was) return;
    window.clearTimeout(was.timer);
    if (was.toast !== null) toast.dismiss(was.toast);
    offer.current = null;
    setUndo(null);
  }, []);

  // Opening the slip clears the notices: on a phone it fills the screen and a notice would sit on its title and
  // its close button. While it is open, the slip itself shows every change - and the undo offer - so no notice is
  // raised.
  const setOpen = useCallback((next: boolean) => {
    shown.current = next;
    setOpenState(next);
    if (next) {
      toast.dismiss();
      if (offer.current) offer.current.toast = null;
    }
  }, []);

  useEffect(() => write(legs), [legs]);
  useEffect(() => () => window.clearTimeout(offer.current?.timer), []);

  const restore = useCallback(() => {
    const was = offer.current;
    if (!was) return;
    withdraw();
    current.current = was.undo.before;
    setLegs(was.undo.before);
  }, [withdraw]);

  const apply = useCallback(
    (action: SlipAction, quiet = false) => {
      const before = current.current;
      const change = slipReduce(before, action);
      current.current = change.legs;
      setLegs(change.legs);
      withdraw();
      // A quiet change (the slip emptied after its parlay was saved, the builder's parlay loaded) offers no undo.
      const back = quiet ? null : undoOf(before, change);
      if (back) {
        const timer = window.setTimeout(withdraw, UNDO_MS);
        let id: string | number | null = null;
        if (!shown.current) {
          id = toast(
            t(back.effect === "cleared" ? "records.slip.undoCleared" : "records.toast.removedLeg"),
            {
              duration: UNDO_MS,
              action: { label: t("records.slip.undo"), onClick: restore },
            },
          );
        }
        offer.current = { undo: back, timer, toast: id };
        setUndo(back);
      }
      if (change.effect === "added" && !quiet)
        track("slip_leg_added", {
          legs: change.legs.length,
          ...(action.type === "toggle" ? { market: action.leg.market_key } : {}),
        });
      if (quiet || shown.current) return;
      if (change.effect === "added") toast.success(t("records.toast.added"));
      else if (change.effect === "replaced") toast(t("records.toast.replaced"));
      else if (change.effect === "full")
        toast.error(t("records.toast.full", { max: MAX_SLIP_LEGS }));
    },
    [withdraw, restore],
  );

  const value = useMemo<SlipValue>(
    () => ({
      legs,
      has: (key) => legs.some((l) => l.key === key),
      toggle: (leg) => apply({ type: "toggle", leg }),
      remove: (key) => apply({ type: "remove", key }),
      clear: (quiet = false) => apply({ type: "clear" }, quiet),
      load: (next) => apply({ type: "load", legs: next }, true),
      undo: undo ? { effect: undo.effect, count: undo.count } : null,
      restore,
      open,
      setOpen,
    }),
    [legs, undo, open, apply, restore, setOpen],
  );
  return <SlipContext.Provider value={value}>{children}</SlipContext.Provider>;
}
