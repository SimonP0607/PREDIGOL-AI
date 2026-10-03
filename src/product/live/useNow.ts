import { useEffect, useState } from "react";

/** The current time, re-read every `intervalMs` - keeps "hace 2 min" honest between refreshes. */
export function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}
