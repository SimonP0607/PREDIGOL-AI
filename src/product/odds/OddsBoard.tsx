/**
 * The board: one row per upcoming fixture with the best price of every selection of the
 * chosen market, next to its fair price. A table on desktop, stacked cards on a phone.
 * A price is a toggle: a tap adds its selection to "Mi parlay", another takes it out.
 */
import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { ChartLine, ChevronDown, ChevronRight, TrendingUp } from "lucide-react";
import type { BestMarket, BestOddsFixture } from "@/lib/api/v1/types_product";
import { t } from "@/lib/i18n";
import { fmtLine, fmtOdds, fmtSignedPct, toNumber } from "@/lib/i18n/format";
import { formatDate, formatTime, relativeDay } from "@/lib/time";
import { cn } from "@/lib/utils";
import { CompetitionTag, TeamName } from "@/components/football/Logos";
import { Freshness } from "@/product/shared/Bits";
import { Card, EmptyState, SectionHeader } from "@/product/shared/States";
import { marketName, selectionLabel } from "@/product/shared/markets";
import { groupByDay, priceFreshness, priceSlots, type PriceSlot } from "./board";
import { MovementPanel } from "./MovementPanel";
import { slotLeg } from "./parlay";
import { ParlayToggle, PricePill } from "./ParlayPrice";
import { blockedText, isToggleable, useParlayLeg } from "./useParlayLeg";

export function OddsBoard({
  fixtures,
  market,
  hours,
  onWiden,
}: {
  fixtures: BestOddsFixture[];
  market: string;
  hours: number;
  /** Offered when nothing is priced in the window: look further ahead. */
  onWiden?: (() => void) | undefined;
}) {
  const rows = fixtures.filter((f) => f.markets.some((m) => m.market_key === market));
  const groups = groupByDay(rows);
  return (
    <section className="space-y-4" data-testid="odds-board">
      <SectionHeader
        title={marketName(market)}
        subtitle={
          rows.length
            ? `${t("odds.board.summary", { count: rows.length, hours })} · ${t("odds.parlay.help")}`
            : undefined
        }
        icon={<TrendingUp aria-hidden className="h-4 w-4 text-primary" />}
      />
      {rows.length === 0 ? (
        <Card>
          <EmptyState
            icon={<TrendingUp aria-hidden className="h-6 w-6" />}
            title={t("odds.board.emptyTitle")}
            body={t("odds.board.emptyBody")}
            action={
              onWiden ? (
                <button
                  type="button"
                  onClick={onWiden}
                  className="inline-flex h-9 items-center rounded-full border border-border-strong px-4 text-xs font-semibold hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {t("odds.board.widen", { hours: 72 })}
                </button>
              ) : undefined
            }
          />
        </Card>
      ) : (
        groups.map((g) => (
          <div key={g.key} className="space-y-2">
            <DayHeading at={g.first} />
            <Card as="div" className="overflow-hidden">
              <ul className="divide-y divide-border/70">
                {g.items.map((f) => (
                  <FixtureRow key={f.fixture_id} fixture={f} market={market} />
                ))}
              </ul>
            </Card>
          </div>
        ))
      )}
    </section>
  );
}

/** "Hoy · sáb 3 oct", "Mañana · dom 4 oct", "lun 5 oct" - in the reader's zone. */
function DayHeading({ at }: { at: string }) {
  const rel = relativeDay(at);
  const word =
    rel === "today"
      ? t("common.day.today")
      : rel === "tomorrow"
        ? t("common.day.tomorrow")
        : rel === "yesterday"
          ? t("common.day.yesterday")
          : null;
  return (
    <h3 className="flex items-baseline gap-2 px-1 font-display text-sm font-semibold">
      {word ? (
        <>
          <span>{word}</span>
          <span className="text-xs font-normal text-muted-foreground">{formatDate(at)}</span>
        </>
      ) : (
        <span className="inline-block first-letter:uppercase">{formatDate(at)}</span>
      )}
    </h3>
  );
}

function FixtureRow({ fixture, market }: { fixture: BestOddsFixture; market: string }) {
  const [open, setOpen] = useState(false);
  const priced = fixture.markets.find((m) => m.market_key === market);
  if (!priced) return null;
  const panelId = `odds-move-${fixture.fixture_id}`;
  const match = `${fixture.home.name} ${t("common.vs")} ${fixture.away.name}`;
  return (
    <li className="px-3 py-3 sm:px-4" data-testid="odds-fixture">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:gap-5">
        <div className="min-w-0 lg:flex-1">
          {/* text-caption here too: the shared tags inherit it whatever their own classes keep. */}
          <div className="flex items-center justify-between gap-2 text-caption">
            <div className="flex min-w-0 items-center gap-2">
              <span className="numeric shrink-0 text-sm font-semibold">
                {formatTime(fixture.kickoff_at)}
              </span>
              <CompetitionTag
                name={fixture.competition.name}
                logo={fixture.competition.logo_url}
                flag={fixture.competition.flag_url}
                country={fixture.competition.country}
                className="min-w-0"
              />
            </div>
            <Freshness
              at={fixture.as_of}
              level={priceFreshness(fixture.as_of)}
              className="shrink-0"
            />
          </div>
          <div className="mt-2 grid gap-1.5 text-sm">
            <TeamName
              name={fixture.home.name}
              logo={fixture.home.logo_url}
              size={20}
              strong
              className="min-w-0"
            />
            <TeamName
              name={fixture.away.name}
              logo={fixture.away.logo_url}
              size={20}
              strong
              className="min-w-0"
            />
          </div>
        </div>

        <MarketPrices market={priced} fixture={fixture} />

        <div className="flex items-center justify-between gap-2 lg:w-36 lg:shrink-0 lg:flex-col lg:items-stretch">
          <button
            type="button"
            aria-expanded={open}
            aria-controls={open ? panelId : undefined}
            aria-label={t("odds.movement.toggleLabel", { match })}
            onClick={() => setOpen((v) => !v)}
            data-testid="odds-movement-toggle"
            className={cn(
              "inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              open
                ? "border-border-strong bg-elevated text-foreground"
                : "border-border text-muted-foreground hover:border-border-strong hover:text-foreground",
            )}
          >
            <ChartLine aria-hidden className="h-3.5 w-3.5" />
            {t("odds.movement.toggle")}
            <ChevronDown
              aria-hidden
              className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-180")}
            />
          </button>
          <Link
            to="/matches/$fixtureId"
            params={{ fixtureId: String(fixture.fixture_id) }}
            aria-label={t("odds.openMatchLabel", { match })}
            className="inline-flex h-9 items-center justify-center gap-1 rounded-lg px-3 text-xs font-semibold text-primary transition-colors hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {t("odds.openMatch")}
            <ChevronRight aria-hidden className="h-3.5 w-3.5" />
          </Link>
        </div>
      </div>

      {open ? (
        <MovementPanel
          id={panelId}
          fixtureId={fixture.fixture_id}
          market={priced}
          home={fixture.home}
          away={fixture.away}
        />
      ) : null}
    </li>
  );
}

function lineText(market: BestMarket): string | null {
  if (market.market_key === "AH") return fmtLine(market.line, true);
  if (market.market_key === "OU") return fmtLine(market.line);
  return null;
}

function MarketPrices({ market, fixture }: { market: BestMarket; fixture: BestOddsFixture }) {
  const slots = priceSlots(market);
  const line = lineText(market);
  return (
    <div className="flex items-stretch gap-2 lg:shrink-0 lg:items-center lg:gap-3">
      {line !== null ? (
        <div className="flex w-14 shrink-0 flex-col items-center justify-center rounded-lg border border-border bg-background/40 px-1 py-1.5 lg:w-16">
          <span className="text-[0.6rem] font-semibold uppercase tracking-wider text-subtle-foreground">
            {t("odds.board.line")}
          </span>
          <span className="numeric text-sm font-semibold">{line}</span>
        </div>
      ) : null}
      <div
        className={cn(
          "grid min-w-0 flex-1 gap-2 lg:flex-none",
          slots.length >= 3
            ? "grid-cols-3 lg:grid-cols-[repeat(3,8.25rem)]"
            : "grid-cols-2 lg:grid-cols-[repeat(2,8.25rem)]",
        )}
      >
        {slots.map((slot) => (
          <PriceCell key={slot.selection} slot={slot} market={market} fixture={fixture} />
        ))}
      </div>
    </div>
  );
}

function PriceCell({
  slot,
  market,
  fixture,
}: {
  slot: PriceSlot;
  market: BestMarket;
  fixture: BestOddsFixture;
}) {
  const q = {
    market_key: market.market_key,
    selection: slot.selection,
    line: market.line,
    home: fixture.home.name,
    away: fixture.away.name,
  };
  const short = selectionLabel(q, true);
  const full = selectionLabel(q);
  const p = slot.price;
  // Null without a price, or outside the slip (nothing to add then).
  const parlay = useParlayLeg(slotLeg(fixture, market, slot));

  if (!p) {
    return (
      <div className="relative flex min-w-0 flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-border px-2 py-2">
        <span className="sr-only">{t("odds.board.cellNoPrice", { selection: full })}</span>
        <span aria-hidden className="truncate text-xs font-semibold text-muted-foreground">
          {short}
        </span>
        <span aria-hidden className="text-caption text-subtle-foreground">
          {t("odds.board.noPrice")}
        </span>
      </div>
    );
  }

  const edge = toNumber(p.price_edge);
  const bookmaker = p.bookmaker ?? "—";
  const description = `${t("odds.board.cell", {
    selection: full,
    odds: fmtOdds(p.best_odds),
    bookmaker,
    fair: fmtOdds(p.fair_odds),
    edge: fmtSignedPct(p.price_edge),
  })}${slot.best ? ` ${t("odds.board.bestSr")}` : ""}`;
  // A quarter line never goes in a parlay; nothing is added once the match has kicked off.
  const blocked = blockedText(parlay);
  const inSlip = !!parlay?.inSlip;
  const cell = cn(
    "relative flex w-full min-w-0 flex-col gap-1 rounded-lg border px-2 py-2 text-left",
    inSlip
      ? "border-gold/70 bg-gold-soft/60 ring-1 ring-gold/40"
      : slot.best
        ? "border-gold/40 bg-gold-soft/40"
        : "border-border bg-background/40",
  );
  const body = (
    <span aria-hidden className="flex min-w-0 flex-col gap-1">
      <span className="flex items-center justify-between gap-1">
        <span className="truncate text-xs font-semibold text-foreground">{short}</span>
        <span
          title={t("odds.board.edgeHelp")}
          className={cn(
            "numeric shrink-0 text-[0.68rem] font-semibold",
            p.outlier
              ? "text-warning"
              : edge !== null && edge > 0
                ? "text-positive"
                : "text-subtle-foreground",
          )}
        >
          {fmtSignedPct(p.price_edge)}
        </span>
      </span>
      <PricePill
        odds={p.best_odds}
        best={slot.best}
        dim={!!p.outlier}
        state={parlay}
        className="w-full"
      />
      {p.outlier ? (
        <span
          title={t("odds.board.outlierHelp")}
          className="truncate text-caption font-medium text-warning"
        >
          {t("odds.board.outlier")}
        </span>
      ) : null}
      <span
        title={t("odds.board.bookmakers", { count: p.n_bookmakers })}
        className="truncate text-caption text-muted-foreground"
      >
        {bookmaker}
      </span>
      <span className="numeric truncate text-caption text-subtle-foreground">
        {t("odds.board.fair", { odds: fmtOdds(p.fair_odds) })}
      </span>
    </span>
  );
  return (
    <div
      data-best={slot.best || undefined}
      data-in-slip={inSlip || undefined}
      data-testid="odds-cell"
      className="min-w-0"
    >
      {parlay && isToggleable(parlay) ? (
        <ParlayToggle
          state={parlay}
          srLabel={description}
          className={cn(cell, "transition-colors hover:brightness-110")}
        >
          {body}
        </ParlayToggle>
      ) : (
        <div className={cell} title={blocked ?? undefined}>
          <span className="sr-only">{blocked ? `${description} ${blocked}` : description}</span>
          {body}
        </div>
      )}
    </div>
  );
}
