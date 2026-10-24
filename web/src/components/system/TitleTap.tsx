import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { isTap, place, titledTarget, type Titled, type Touch } from "./tapHint";

const SHOWN_MS = 6000;

interface Shown {
  titled: Titled<Element>;
  /** The element's box when it was tapped, in screen coordinates. */
  box: { left: number; top: number; width: number; height: number };
}

/**
 * Shows the `title` of what a finger taps (a touch or a pen; a mouse keeps the browser's own tooltip). It is mounted once, at the
 * root: every explanation kept in a `title` - a column head, an abbreviation, the reason a value is missing - becomes reachable
 * on a phone without each of them being rebuilt. A tap on a control (a link, a button, a field) does what the control does and
 * shows nothing; a second tap on the same element, a tap elsewhere, a scroll, Escape, or a few seconds, put it away.
 */
export function TitleTap() {
  const [shown, setShown] = useState<Shown | null>(null);
  const [at, setAt] = useState<{ left: number; top: number } | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const current = useRef<Element | null>(null);

  useEffect(() => {
    let down: (Touch & { kind: string; showing: Element | null }) | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const hide = () => {
      clearTimeout(timer);
      current.current = null;
      setShown(null);
      setAt(null);
    };
    const onDown = (e: PointerEvent) => {
      down = {
        x: e.clientX,
        y: e.clientY,
        at: e.timeStamp,
        kind: e.pointerType,
        showing: current.current,
      };
      hide(); // a touch anywhere puts the hint away; a tap on the same element then only closes it
    };
    const onUp = (e: PointerEvent) => {
      const start = down;
      down = null;
      if (!start || start.kind === "mouse") return;
      if (!isTap(start, { x: e.clientX, y: e.clientY, at: e.timeStamp })) return;
      const target = e.target instanceof Element ? e.target : null;
      const titled = target ? titledTarget(target) : null;
      if (!titled || titled.node === start.showing) return;
      const rect = titled.node.getBoundingClientRect();
      current.current = titled.node;
      setAt(null);
      setShown({
        titled,
        box: { left: rect.left, top: rect.top, width: rect.width, height: rect.height },
      });
      timer = setTimeout(hide, SHOWN_MS);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") hide();
    };
    document.addEventListener("pointerdown", onDown, true);
    document.addEventListener("pointerup", onUp, true);
    document.addEventListener("keydown", onKey, true);
    window.addEventListener("scroll", hide, true);
    window.addEventListener("resize", hide);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("pointerdown", onDown, true);
      document.removeEventListener("pointerup", onUp, true);
      document.removeEventListener("keydown", onKey, true);
      window.removeEventListener("scroll", hide, true);
      window.removeEventListener("resize", hide);
    };
  }, []);

  // Measured once it is on the screen: where it goes depends on how big the text made it.
  useLayoutEffect(() => {
    if (!shown || !box.current) return;
    const size = { width: box.current.offsetWidth, height: box.current.offsetHeight };
    setAt(place(shown.box, size, { width: window.innerWidth, height: window.innerHeight }));
  }, [shown]);

  if (!shown) return null;
  return (
    <div
      ref={box}
      role="status"
      data-testid="title-tap"
      style={{
        position: "fixed",
        left: at?.left ?? 0,
        top: at?.top ?? 0,
        visibility: at ? "visible" : "hidden",
        maxWidth: "min(20rem, calc(100vw - 16px))",
      }}
      className="pointer-events-none z-[70] rounded-md bg-primary px-3 py-1.5 text-xs leading-relaxed text-primary-foreground shadow-md"
    >
      {shown.titled.text}
    </div>
  );
}
