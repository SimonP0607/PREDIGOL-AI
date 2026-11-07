/**
 * The captures behind a match's prices: when, how far from kick-off, how many quotes. Owner only (plan Partidos y Match
 * Center, F4b: the strip left the reader's «Mercados» for Avanzado / Auditoría, its numbers unchanged).
 */
import { useQuery } from "@tanstack/react-query";
import { Radar } from "lucide-react";
import { t } from "@/lib/i18n";
import { live as queries } from "@/lib/api/v1/queries";
import type { MatchMarkets } from "@/lib/api/v1/types_profile";
import { marketName } from "@/product/shared/markets";
import { captureLabel } from "./books";

export function CapturesStrip({ all }: { all: MatchMarkets }) {
  const prematch = all.captures.filter((c) => c.source === "prematch");
  const books = new Set(all.selections.flatMap((s) => s.books.map((b) => b.bookmaker_id))).size;
  if (all.captures.length === 0) return null;
  return (
    <div
      className="space-y-2 rounded-lg border border-border bg-card/60 px-3 py-2.5"
      data-testid="captures-strip"
    >
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
        <Radar aria-hidden className="h-3.5 w-3.5 text-primary" />
        <span className="font-medium">{t("match.captures.title")}</span>
        <span className="numeric text-muted-foreground">
          {t("match.captures.summary", {
            captures: all.captures.length,
            quotes: all.quotes,
            books,
          })}
        </span>
      </p>
      <ul className="flex flex-wrap gap-1.5">
        {prematch.map((c) => (
          <li
            key={c.captured_at}
            className="numeric rounded-full border border-border-strong bg-elevated px-2 py-0.5 text-micro text-muted-foreground"
            title={Object.entries(c.by_market)
              .map(([m, n]) => `${marketName(m)}: ${n}`)
              .join(" · ")}
          >
            {t("match.captures.chip", { when: captureLabel(c.minutes_to_ko), quotes: c.quotes })}
          </li>
        ))}
      </ul>
      <p className="text-caption text-subtle-foreground">{t("match.captures.help")}</p>
    </div>
  );
}

/** The strip of the match, read from GET /matches/{id}/markets (the same query the reader's «Ver todas las casas» reads). */
export function MatchCaptures({ fixtureId }: { fixtureId: string }) {
  const q = useQuery(queries.matchMarkets(fixtureId));
  const all = q.data?.data ?? null;
  if (!all) return null;
  if (all.captures.length === 0)
    return <p className="text-xs text-muted-foreground">{t("match.captures.none")}</p>;
  return <CapturesStrip all={all} />;
}
