/**
 * The prices furthest above the market's fair price right now: one row per match, the
 * best price in gold with its bookmaker - chosen the Cuotas way - and by how much it beats
 * the fair price.
 */
import { Link } from "@tanstack/react-router";
import { TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { fmtOdds, fmtSignedPct, toNumber } from "@/lib/i18n/format";
import { formatKickoff } from "@/lib/time";
import type { Section } from "@/lib/api/v1/types";
import type { BestHighlight } from "@/lib/api/v1/types_product";
import { CompetitionTag, TeamName } from "@/components/football/Logos";
import { SelectablePrice } from "@/product/odds/SelectablePrice";
import { pickableOfHighlight } from "@/product/records/pickable";
import { Card, SectionHeader } from "@/product/shared/States";
import { emptyReason, marketName, selectionLabel } from "@/product/shared/markets";

function BestRow({ h }: { h: BestHighlight }) {
  const edge = toNumber(h.price.price_edge);
  const label = selectionLabel({
    market_key: h.market_key,
    selection: h.price.selection,
    line: h.line,
    home: h.home.name,
    away: h.away.name,
  });
  return (
    // The match and the selection open the match; the price beside them is chosen the Cuotas way (REVIEW
    // points 6 and 18) - a button never sits inside a link.
    <div
      data-testid="best-price-row"
      className="flex items-center gap-3 px-4 py-3.5 transition-colors hover:bg-elevated/50 sm:px-5 lg:gap-6"
    >
      <Link
        to="/matches/$fixtureId"
        params={{ fixtureId: String(h.fixture_id) }}
        className="grid min-w-0 flex-1 grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-2 rounded-md focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_auto] lg:gap-x-6 lg:gap-y-1"
      >
        <div className="col-span-2 flex min-w-0 items-center gap-1.5 text-sm font-medium lg:col-span-1 lg:col-start-1 lg:row-start-1">
          <TeamName name={h.home.name} logo={h.home.logo_url} size={18} className="min-w-0" />
          <span aria-hidden className="shrink-0 text-subtle-foreground">
            –
          </span>
          <TeamName name={h.away.name} logo={h.away.logo_url} size={18} className="min-w-0" />
        </div>

        <div className="flex min-w-0 items-center gap-1.5 text-caption text-muted-foreground lg:col-start-1 lg:row-start-2">
          <span className="numeric shrink-0">{formatKickoff(h.kickoff_at)}</span>
          <span className="hidden min-w-0 items-center gap-1.5 lg:flex">
            <span aria-hidden className="text-subtle-foreground">
              ·
            </span>
            <CompetitionTag
              name={h.competition.name}
              logo={h.competition.logo_url}
              flag={h.competition.flag_url}
              country={h.competition.country}
              size={12}
              className="min-w-0"
            />
          </span>
        </div>

        <div className="col-span-2 min-w-0 lg:col-span-1 lg:col-start-2 lg:row-span-2 lg:row-start-1">
          <div className="truncate text-caption uppercase tracking-wider text-subtle-foreground">
            {marketName(h.market_key)}
          </div>
          <div className="truncate text-sm font-semibold" data-testid="best-price-selection">
            {label}
          </div>
        </div>

        <div className="col-span-2 flex items-center justify-between gap-x-3 text-caption lg:col-span-1 lg:col-start-3 lg:row-span-2 lg:row-start-1 lg:flex-col lg:items-end lg:justify-center lg:gap-0.5">
          <span className="text-muted-foreground">
            {t("common.fairOdds")}{" "}
            <span className="numeric font-medium text-foreground">
              {fmtOdds(h.price.fair_odds)}
            </span>
          </span>
          <span
            className={cn(
              "font-semibold tabular-nums",
              edge !== null && edge > 0 ? "text-positive" : "text-muted-foreground",
            )}
          >
            {t("home.best.overFair", { pct: fmtSignedPct(edge) })}
          </span>
        </div>
      </Link>

      <div className="flex shrink-0 flex-col items-end gap-0.5">
        <SelectablePrice sel={pickableOfHighlight(h)} best />
        {h.price.bookmaker ? (
          <span className="max-w-[7rem] truncate text-caption text-muted-foreground">
            {h.price.bookmaker}
          </span>
        ) : null}
      </div>
    </div>
  );
}

export function BestPrices({ section }: { section: Section<BestHighlight[]> }) {
  const items = section.data.slice(0, 6);
  return (
    <section data-testid="home-best-prices">
      <SectionHeader
        title={t("home.best.title")}
        subtitle={items.length > 0 ? t("home.best.subtitle") : undefined}
        icon={<TrendingUp aria-hidden className="h-4 w-4 shrink-0 text-primary" />}
        action={{ label: t("home.best.seeAll"), to: "/odds" }}
      />
      {items.length === 0 ? (
        <p
          data-empty-state
          className="mt-3 flex items-center gap-2.5 rounded-xl border border-border bg-card px-4 py-3 text-sm text-muted-foreground"
        >
          <TrendingUp aria-hidden className="h-4 w-4 shrink-0 text-subtle-foreground" />
          {emptyReason(section.reason) || t("home.best.empty")}
        </p>
      ) : (
        <Card className="mt-3 overflow-hidden">
          <ul className="divide-y divide-border/70">
            {items.map((h) => (
              <li key={`${h.fixture_id}-${h.market_key}-${h.line}-${h.price.selection}`}>
                <BestRow h={h} />
              </li>
            ))}
          </ul>
        </Card>
      )}
    </section>
  );
}
