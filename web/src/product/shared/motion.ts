/**
 * Motion for the charts and figures (REVIEW point 19: "gráficas bien animadas"): a number counts up to its value,
 * and nothing moves for a reader who asked their system for reduced motion.
 */
import { useEffect, useRef, useState } from "react";

/** The three durations of the product (closing plan 5.1), in ms: the same as --motion-fast / -base / -slow in styles.css. */
export const MOTION = { fast: 120, base: 200, slow: 300 } as const;

const QUERY = "(prefers-reduced-motion: reduce)";

export function prefersReducedMotion(): boolean {
  try {
    return typeof window !== "undefined" && !!window.matchMedia?.(QUERY).matches;
  } catch {
    return false;
  }
}

export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(prefersReducedMotion);
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia(QUERY);
    const update = () => setReduced(mq.matches);
    mq.addEventListener?.("change", update);
    return () => mq.removeEventListener?.("change", update);
  }, []);
  return reduced;
}

/** Ease-out cubic: fast at first, settling on the value. */
export function easeOut(t: number): number {
  const x = Math.min(1, Math.max(0, t));
  return 1 - (1 - x) ** 3;
}

/** The value, counted up from the previous one over `ms` (at once with reduced motion or a null value). */
export function useCountUp(target: number | null, ms = 900): number | null {
  const reduced = useReducedMotion();
  const [shown, setShown] = useState<number | null>(reduced ? target : target === null ? null : 0);
  const from = useRef<number>(0);
  useEffect(() => {
    if (target === null || reduced || typeof window === "undefined") {
      setShown(target);
      if (target !== null) from.current = target;
      return;
    }
    const start = performance.now();
    const origin = from.current;
    let frame = 0;
    const step = (now: number) => {
      const k = easeOut((now - start) / ms);
      setShown(origin + (target - origin) * k);
      if (k < 1) frame = window.requestAnimationFrame(step);
      else from.current = target;
    };
    frame = window.requestAnimationFrame(step);
    return () => {
      window.cancelAnimationFrame(frame);
      from.current = target;
    };
  }, [target, ms, reduced]);
  return shown;
}

/** How long a «just changed» mark lasts (a goal's flash is 1200 ms in the CSS; the rest are MOTION.base). */
export const FLASH_MS = 1200;

/**
 * True for `ms` after `value` changes - never on the first render (what was already there does not announce itself) and
 * never with reduced motion. Drives the CSS marks (motion-pop, motion-goal): a goal, a pick that settled, a count.
 */
export function useJustChanged<T>(value: T, ms: number = MOTION.base): boolean {
  const reduced = useReducedMotion();
  const previous = useRef(value);
  const [changed, setChanged] = useState(false);
  useEffect(() => {
    if (Object.is(previous.current, value)) return;
    previous.current = value;
    if (reduced) return;
    setChanged(true);
    const timer = setTimeout(() => setChanged(false), ms);
    return () => clearTimeout(timer);
  }, [value, ms, reduced]);
  return changed;
}
