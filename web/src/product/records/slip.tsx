/**
 * The parlay a user is assembling, across pages: one leg per match, at most ten. It lives in
 * this tab's session storage (a list of selections - nothing sensitive) until it is saved
 * as a parlay or cleared; the server validates it again before storing anything.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { t } from "@/lib/i18n";
import { MAX_SLIP_LEGS, parseSlip, slipReduce, type SlipAction, type SlipLeg } from "./model";
import { SlipContext, type SlipValue } from "./slipContext";

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
  const current = useRef(legs);
  const shown = useRef(false);
  // Opening the slip clears the notices: on a phone it fills the screen and a notice would sit on its title and
  // its close button. While it is open, the slip itself shows every change, so no notice is raised.
  const setOpen = useCallback((next: boolean) => {
    shown.current = next;
    setOpenState(next);
    if (next) toast.dismiss();
  }, []);

  useEffect(() => write(legs), [legs]);

  const apply = useCallback((action: SlipAction, quiet = false) => {
    const change = slipReduce(current.current, action);
    current.current = change.legs;
    setLegs(change.legs);
    if (quiet || shown.current) return;
    if (change.effect === "added") toast.success(t("records.toast.added"));
    else if (change.effect === "replaced") toast(t("records.toast.replaced"));
    else if (change.effect === "removed") toast(t("records.toast.removedLeg"));
    else if (change.effect === "full") toast.error(t("records.toast.full", { max: MAX_SLIP_LEGS }));
  }, []);

  const value = useMemo<SlipValue>(
    () => ({
      legs,
      has: (key) => legs.some((l) => l.key === key),
      toggle: (leg) => apply({ type: "toggle", leg }),
      remove: (key) => apply({ type: "remove", key }),
      clear: (quiet = false) => apply({ type: "clear" }, quiet),
      load: (next) => apply({ type: "load", legs: next }, true),
      open,
      setOpen,
    }),
    [legs, open, apply, setOpen],
  );
  return <SlipContext.Provider value={value}>{children}</SlipContext.Provider>;
}
