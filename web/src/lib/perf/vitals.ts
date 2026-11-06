/**
 * How fast the product loads and answers for real readers (closing plan 5.3): LCP, CLS and INP, read with the
 * browser's own PerformanceObserver (no library), sent ONCE per visit - when the page is hidden - and only for a small
 * sample of visits (3 %), decided when the page opens. The reading is numbers and the screen's path; the server gives
 * it a share of its own, smaller than the errors' (fbi.api.routers.monitoring). Nothing here runs without the server
 * having switched monitoring on: `report` is a no-op until the SDK is up.
 */
import { reportWebVitals } from "@/lib/observability";

/** The share of visits that are measured. */
export const SAMPLE_RATE = 0.03;

export interface Vitals {
  lcp?: number;
  cls?: number;
  inp?: number;
}

/** Whether this visit is one of the sample: decided once, from a random number in [0, 1). */
export function inSample(random: number, rate: number = SAMPLE_RATE): boolean {
  return random < rate;
}

interface ShiftEntry extends PerformanceEntry {
  value: number;
  hadRecentInput: boolean;
}
interface EventTimingEntry extends PerformanceEntry {
  interactionId?: number;
}

/** CLS as the web vitals define it: the worst «session window» of shifts (gaps under 1 s, a window under 5 s). */
export class ClsMeter {
  value = 0;
  private windowValue = 0;
  private windowStart = 0;
  private last = 0;
  add(shift: { value: number; startTime: number; hadRecentInput: boolean }): void {
    if (shift.hadRecentInput) return;
    if (
      this.windowValue > 0 &&
      shift.startTime - this.last < 1000 &&
      shift.startTime - this.windowStart < 5000
    ) {
      this.windowValue += shift.value;
    } else {
      this.windowValue = shift.value;
      this.windowStart = shift.startTime;
    }
    this.last = shift.startTime;
    this.value = Math.max(this.value, this.windowValue);
  }
}

/**
 * Start measuring. `report` is called at most once, with what was seen. Returns a stop function; `random` and `win` are
 * for tests. Does nothing outside a browser, in a browser without PerformanceObserver, or outside the sample.
 */
export function startVitals(
  report: (v: Vitals) => void = reportWebVitals,
  random: () => number = Math.random,
  win: (Window & typeof globalThis) | undefined = typeof window === "undefined"
    ? undefined
    : window,
): () => void {
  if (!win || typeof win.PerformanceObserver === "undefined" || !inSample(random())) {
    return () => undefined;
  }
  const seen: Vitals = {};
  const cls = new ClsMeter();
  const observers: PerformanceObserver[] = [];
  const watch = (type: string, onEntry: (e: PerformanceEntry) => void, extra?: object) => {
    try {
      const o = new win.PerformanceObserver((list) => list.getEntries().forEach(onEntry));
      o.observe({ type, buffered: true, ...extra } as PerformanceObserverInit);
      observers.push(o);
    } catch {
      // an entry type this browser does not know (INP is not in every one): that number is left out
    }
  };
  watch("largest-contentful-paint", (e) => (seen.lcp = e.startTime));
  watch("layout-shift", (e) => {
    const s = e as ShiftEntry;
    cls.add({ value: s.value, startTime: s.startTime, hadRecentInput: s.hadRecentInput });
    seen.cls = cls.value;
  });
  watch(
    "event",
    (e) => {
      const t = e as EventTimingEntry;
      if (t.interactionId) seen.inp = Math.max(seen.inp ?? 0, t.duration);
    },
    { durationThreshold: 40 },
  );
  let sent = false;
  const flush = () => {
    if (sent || win.document.visibilityState !== "hidden") return;
    sent = true;
    observers.forEach((o) => o.disconnect());
    report(seen);
  };
  win.document.addEventListener("visibilitychange", flush);
  return () => {
    win.document.removeEventListener("visibilitychange", flush);
    observers.forEach((o) => o.disconnect());
  };
}
