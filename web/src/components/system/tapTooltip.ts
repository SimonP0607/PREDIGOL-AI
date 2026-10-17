/**
 * Radix tooltips open on hover and on keyboard focus only - on a touch screen the tap that should show one closes
 * it (Trigger onClick → close), so a definition or the reason a value is missing was mouse-only (mobile UX audit:
 * "no depender de tooltips"). With this, a tap opens and closes the tooltip; a tap elsewhere closes it (Radix's
 * outside-press dismissal). A mouse keeps the hover behaviour untouched.
 */
import { useRef, useState, type MouseEvent, type PointerEvent } from "react";

export function useTapTooltip() {
  const [open, setOpen] = useState(false);
  const touch = useRef(false);
  // Whether it was open when the finger came down: the outside-press dismissal may close it before the click,
  // and a toggle on the click would then open it again.
  const wasOpen = useRef(false);
  return {
    root: { open, onOpenChange: setOpen },
    trigger: {
      onPointerDown: (e: PointerEvent) => {
        touch.current = e.pointerType !== "mouse";
        wasOpen.current = open;
      },
      onClick: (e: MouseEvent) => {
        if (!touch.current) return;
        // Radix runs its own onClick (close) only when this one did not prevent it.
        e.preventDefault();
        setOpen(!wasOpen.current);
      },
    },
  };
}
