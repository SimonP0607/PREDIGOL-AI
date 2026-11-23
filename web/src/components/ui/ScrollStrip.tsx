/**
 * A row of chips or tabs that scrolls sideways (Plan Maestro de Correcciones, AP-C02; audit C3). One component for every
 * strip of the product, so each one behaves the same way:
 *
 *  - on a phone it slides under the finger and its edge fades where more waits (the `scroll-strip` utility);
 *  - from 1024 px, where nobody slides with a mouse, 44 px arrows appear at the edge where more waits - and only there:
 *    a strip that fits has none;
 *  - the chip that is on (aria-pressed, aria-selected or aria-current) is always in view;
 *  - the keyboard's left and right arrows move from chip to chip (a tablist keeps its own handling, which wins).
 *
 * The arrows are mouse help, not another stop for the keyboard or the screen reader: both already reach every chip.
 * The strip itself is the element with the props given (role, label, test id, guide anchor); the arrows live in the
 * wrapper around it, tagged `data-strip-arrows` so the layout guard knows the strip is reachable.
 */
import { useCallback, useEffect, useRef, useState, type ComponentProps, type Ref } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { t } from "@/lib/i18n";
import { scrollCue, useScrollCue, type ScrollCue } from "@/lib/scrollCue";
import { cn } from "@/lib/utils";

const ON = '[aria-pressed="true"],[aria-selected="true"],[aria-current="true"],[aria-current="page"]';
const MARGIN = 8;
/** From 1024 px an arrow (44 px) lies over the strip's edge: the chip that is on must stay clear of it. */
const ARROW_ROOM = 52;

/** Where to scroll so that a chip is wholly inside the strip (null: it already is). */
export function revealOffset(
  strip: { left: number; right: number; scrollLeft: number },
  chip: { left: number; right: number },
  margin: number = MARGIN,
): number | null {
  if (chip.left < strip.left + margin) return strip.scrollLeft - (strip.left + margin - chip.left);
  if (chip.right > strip.right - margin)
    return strip.scrollLeft + (chip.right - (strip.right - margin));
  return null;
}

/** How far an arrow moves the strip: most of what is in view, so the chip it ended on is still the next one's neighbour. */
export function pageStep(clientWidth: number): number {
  return Math.max(120, Math.round(clientWidth * 0.8));
}

function reduced(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

type Props = Omit<ComponentProps<"div">, "ref"> & {
  ref?: Ref<HTMLDivElement> | undefined;
  /** Classes of the wrapper that holds the strip and its arrows (the strip's own go in `className`). */
  wrapperClassName?: string | undefined;
};

export function ScrollStrip({ ref, className, wrapperClassName, children, onKeyDown, ...rest }: Props) {
  const strip = useRef<HTMLDivElement | null>(null);
  const [cue, setCue] = useState<ScrollCue>({ start: false, end: false });
  useScrollCue(strip);

  const setRef = useCallback(
    (el: HTMLDivElement | null) => {
      strip.current = el;
      if (typeof ref === "function") ref(el);
      else if (ref) ref.current = el;
    },
    [ref],
  );

  useEffect(() => {
    const el = strip.current;
    if (!el) return;
    const update = () => setCue(scrollCue(el.scrollLeft, el.scrollWidth, el.clientWidth));
    const reveal = () => {
      const on = el.querySelector<HTMLElement>(ON);
      if (!on || el.scrollWidth <= el.clientWidth + 1) return;
      const s = el.getBoundingClientRect();
      const c = on.getBoundingClientRect();
      const to = revealOffset(
        { left: s.left, right: s.right, scrollLeft: el.scrollLeft },
        { left: c.left, right: c.right },
        window.matchMedia("(min-width: 1024px)").matches ? ARROW_ROOM : MARGIN,
      );
      if (to !== null) el.scrollTo({ left: Math.max(0, to), behavior: reduced() ? "auto" : "smooth" });
    };
    update();
    reveal();
    el.addEventListener("scroll", update, { passive: true });
    const resize = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    resize?.observe(el);
    for (const child of Array.from(el.children)) resize?.observe(child);
    // a chip that is turned on (or a list that loads) changes the aria attributes or the children
    const mutations =
      typeof MutationObserver === "undefined"
        ? null
        : new MutationObserver(() => {
            for (const child of Array.from(el.children)) resize?.observe(child);
            update();
            reveal();
          });
    mutations?.observe(el, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["aria-pressed", "aria-selected", "aria-current"],
    });
    return () => {
      el.removeEventListener("scroll", update);
      resize?.disconnect();
      mutations?.disconnect();
    };
  }, []);

  function move(direction: 1 | -1) {
    const el = strip.current;
    if (!el) return;
    el.scrollBy({ left: direction * pageStep(el.clientWidth), behavior: reduced() ? "auto" : "smooth" });
  }

  // Left and right between chips, for a row of buttons that is not a tablist (the tablist's own handler calls
  // preventDefault first and wins).
  function keys(e: React.KeyboardEvent<HTMLDivElement>) {
    onKeyDown?.(e);
    if (e.defaultPrevented || (e.key !== "ArrowRight" && e.key !== "ArrowLeft")) return;
    const el = strip.current;
    if (!el || !(e.target instanceof HTMLElement)) return;
    const chips = Array.from(el.querySelectorAll<HTMLElement>("button:not([disabled]), a[href]"));
    const at = chips.indexOf(e.target);
    if (at < 0) return;
    const next = chips[at + (e.key === "ArrowRight" ? 1 : -1)];
    if (!next) return;
    e.preventDefault();
    next.focus();
    next.scrollIntoView({ block: "nearest", inline: "nearest" });
  }

  const arrow =
    "absolute top-1/2 z-10 hidden h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full border border-border-strong bg-card/95 text-foreground shadow-sm transition-colors hover:bg-elevated lg:flex";
  return (
    <div className={cn("relative min-w-0", wrapperClassName)} data-strip-arrows="">
      <div
        {...rest}
        ref={setRef}
        onKeyDown={keys}
        className={cn("scroll-strip", className)}
      >
        {children}
      </div>
      {cue.start ? (
        <button
          type="button"
          tabIndex={-1}
          aria-hidden="true"
          data-strip-arrow="start"
          data-testid="strip-arrow-start"
          title={t("common.scrollStart")}
          onClick={() => move(-1)}
          className={cn(arrow, "left-0")}
        >
          <ChevronLeft className="h-5 w-5" aria-hidden />
        </button>
      ) : null}
      {cue.end ? (
        <button
          type="button"
          tabIndex={-1}
          aria-hidden="true"
          data-strip-arrow="end"
          data-testid="strip-arrow-end"
          title={t("common.scrollEnd")}
          onClick={() => move(1)}
          className={cn(arrow, "right-0")}
        >
          <ChevronRight className="h-5 w-5" aria-hidden />
        </button>
      ) : null}
    </div>
  );
}
