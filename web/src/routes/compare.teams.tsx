import { createFileRoute } from "@tanstack/react-router";
import { ComparePage } from "@/product/teams/stats/Compare";
import { titled } from "@/lib/i18n/head";

function id(v: unknown): number | undefined {
  const n = Number(v);
  return Number.isInteger(n) && n > 0 ? n : undefined;
}

/** Plan EA (EA-104; maqueta V2·3): two teams side by side. Shown while FBI_STATS_V2 is on. */
export const Route = createFileRoute("/compare/teams")({
  head: titled("stats.compareTeams"),
  validateSearch: (s: Record<string, unknown>): { a?: number; b?: number } => {
    const a = id(s["a"]);
    const b = id(s["b"]);
    return { ...(a !== undefined ? { a } : {}), ...(b !== undefined ? { b } : {}) };
  },
  component: Compare,
});

function Compare() {
  const { a, b } = Route.useSearch();
  return <ComparePage kind="teams" a={a} b={b} />;
}
