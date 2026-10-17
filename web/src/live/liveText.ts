/** Text helpers for in-play data (kept out of component files for fast refresh). */
import type { LiveQuote } from "@/lib/api/v1/types_center";
import { dec } from "./format";

export function minuteText(minute: number | null, extra: number | null): string {
  if (minute === null) return "—";
  return extra ? `${minute}+${extra}'` : `${minute}'`;
}

export function quoteLabel(q: Pick<LiveQuote, "market_key" | "selection" | "line">): string {
  const line = Number(q.line);
  return `${q.market_key ?? "?"} ${q.selection}${line !== 0 || q.market_key === "OU" ? ` ${dec(q.line, 2)}` : ""}`;
}
