/**
 * "Mejores precios frente al mercado": the best prices that pay above the fair price. A card opens its match;
 * its price is a toggle that adds the selection to "Mi parlay" (or takes it out).
 */
import { Link } from "@tanstack/react-router";
import { Sparkles } from "lucide-react";
import type { BestHighlight } from "@/lib/api/v1/types_product";
import { t } from "@/lib/i18n";
import { fmtOdds, fmtSignedPct } from "@/lib/i18n/format";
import { formatKickoff } from "@/lib/time";
import { CompetitionTag, TeamName } from "@/components/football/Logos";
import { SectionHeader } from "@/product/shared/States";
import { emptyReason, marketShort, selectionLabel } from "@/product/shared/markets";
import { highlightLeg } from "./parlay";
import { ParlayToggle, PricePill } from "./ParlayPrice";
import { blockedText, isToggleable, useParlayLeg } from "./useParlayLeg";

const MAX = 6;

export function Highlights({ items }: { items: BestHighlight[] }) {
  const shown = items.slice(0, MAX);
  return (
    <section className="space-y-3" data-testid="odds-highlights">
      <SectionHeader
        title={t("odds.highlights.title")}
        subtitle={t("odds.highlights.subtitle")}
        icon={<Sparkles aria-hidden className="h-4 w-4 text-gold" />}
      />
      {shown.length === 0 ? (
        <p className="text-xs text-muted-foreground">{emptyReason("no_best_prices")}</p>
      ) : (
        // A swipeable strip on a phone (bleeding to the screen edges), a grid from tablet up.
        <ul className="-mx-4 flex snap-x snap-mandatory scroll-px-4 gap-3 overflow-x-auto px-4 pb-1 [scrollbar-width:none] sm:mx-0 sm:grid sm:grid-cols-2 sm:overflow-visible sm:px-0 sm:pb-0 lg:grid-cols-3 [&::-webkit-scrollbar]:hidden">
          {shown.map((h) => (
            <li
              key={`${h.fixture_id}-${h.market_key}-${h.price.selection}`}
              className="w-[82%] max-w-[20rem] shrink-0 snap-start sm:w-auto sm:max-w-none"
            >
              <HighlightCard h={h} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function HighlightCard({ h }: { h: BestHighlight }) {
  const label = selectionLabel({
    market_key: h.market_key,
    selection: h.price.selection,
    line: h.line,
    home: h.home.name,
    away: h.away.name,
  });
  const match = `${h.home.name} ${t("common.vs")} ${h.away.name}`;
  const bookmaker = h.price.bookmaker ?? "—";
  const parlay = useParlayLeg(highlightLeg(h));
  const blocked = blockedText(parlay);
  const pill = <PricePill odds={h.price.best_odds} best state={parlay} />;
  return (
    <article
      data-testid="odds-highlight"
      data-in-slip={parlay?.inSlip || undefined}
      className="relative flex h-full flex-col gap-2.5 rounded-xl border border-border bg-card p-3 transition-colors hover:border-border-strong"
    >
      <div className="flex items-center justify-between gap-2 text-caption">
        <CompetitionTag
          name={h.competition.name}
          logo={h.competition.logo_url}
          flag={h.competition.flag_url}
          country={h.competition.country}
          size={14}
          className="min-w-0"
        />
        <span className="numeric shrink-0 text-muted-foreground">
          {formatKickoff(h.kickoff_at)}
        </span>
      </div>
      {/* The whole card opens the match (the link's overlay covers it); the price sits above it. */}
      <Link
        to="/matches/$fixtureId"
        params={{ fixtureId: String(h.fixture_id) }}
        aria-label={t("odds.openMatchLabel", { match })}
        className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-1.5 text-sm after:absolute after:inset-0 after:rounded-xl after:content-[''] focus-visible:outline-none focus-visible:after:ring-2 focus-visible:after:ring-ring"
      >
        <TeamName name={h.home.name} logo={h.home.logo_url} size={18} strong />
        <span className="text-caption text-subtle-foreground">{t("common.vs")}</span>
        <TeamName name={h.away.name} logo={h.away.logo_url} size={18} strong reverse />
      </Link>
      <div className="mt-auto flex items-end justify-between gap-3 border-t border-border/70 pt-2.5">
        <div className="min-w-0">
          <div className="text-caption uppercase tracking-wider text-subtle-foreground">
            {marketShort(h.market_key)}
          </div>
          <div className="break-words text-sm font-semibold">{label}</div>
          <div className="numeric mt-0.5 text-caption font-semibold text-positive">
            {t("odds.highlights.vsFair", { edge: fmtSignedPct(h.price.price_edge) })}
          </div>
        </div>
        <div className="relative z-10 flex shrink-0 flex-col items-end gap-1">
          {parlay && isToggleable(parlay) ? (
            <ParlayToggle
              state={parlay}
              srLabel={`${label}: ${t("records.actions.priceAt", { odds: fmtOdds(h.price.best_odds), bookmaker })}`}
              className="rounded-md"
            >
              <span aria-hidden className="block">
                {pill}
              </span>
            </ParlayToggle>
          ) : (
            <span title={blocked ?? undefined}>
              {pill}
              {blocked ? <span className="sr-only">{blocked}</span> : null}
            </span>
          )}
          <span className="max-w-[7rem] truncate text-caption text-muted-foreground">
            {bookmaker}
          </span>
          <span className="sr-only">
            {t("odds.board.fair", { odds: fmtOdds(h.price.fair_odds) })}
          </span>
        </div>
      </div>
    </article>
  );
}
