/**
 * One match of the board (plan Cuotas, section 5): time, competition and teams; for each selection the best price in large
 * type with its bookmaker and how many bookmakers quote it - and, small and grey, only where there is one, the market's fair
 * price and the difference with it -; how old the row's prices are; «Comparar casas», «Movimiento» and «Abrir partido».
 * A stale row is dimmed and says it does not go in the parlay; a long market (scores, scorers) shows its most likely
 * selections first - eight on a desk, four on a phone -, and «Ver todas» opens the rest with a search of its own.
 * From 1024 px the actions sit in one line under the teams, so a match is as tall as its prices (UX-087).
 */
import { useId, useState, type ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { ChartLine, ChevronDown, ChevronRight, Clock, Columns3, Search } from "lucide-react";
import { t } from "@/lib/i18n";
import { fmtOdds, fmtSignedPct, toNumber } from "@/lib/i18n/format";
import { formatKickoff, formatTime } from "@/lib/time";
import { cn } from "@/lib/utils";
import { CompetitionTag, TeamName } from "@/components/football/Logos";
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible";
import { fold } from "@/product/matches/model";
import { ParlayToggle, PricePill } from "../ParlayPrice";
import { useParlayLeg } from "../useParlayLeg";
import { LONG_MARKET, PHONE_PREVIEW, type RowEnv } from "./env";
import { catalogTarget } from "@/product/match/marketLink";
import { blockText, explorerLeg, priceBlock } from "./legs";
import type { OddsBoardRow, OddsSelectionPrice } from "./model";
import { MOTION } from "./motion";
import { ComparePanel, MovementPanel } from "./Panels";
import { priceKey, rowFreshness } from "./rows";
import { edgeText, priceDescription, selectionLabel, type Sides } from "./selections";
import { MoveArrow } from "./ui";

/** One selection: its words, the best price (a parlay toggle where it can go in), its bookmaker and the grey figures. */
export function PriceCell({
  row,
  sel,
  env,
  sides,
  className,
}: {
  row: OddsBoardRow;
  sel: OddsSelectionPrice;
  env: RowEnv;
  sides: Sides;
  className?: string | undefined;
}) {
  const label = selectionLabel(env.info, sel, row.line, sides);
  const full = selectionLabel(env.info, sel, row.line, sides, "full");
  const bookmaker = env.bookmakers.get(sel.bookmaker_id) ?? "—";
  const leg = explorerLeg(env.info, env.period, row, sel, bookmaker);
  // Null outside the slip's provider, or for a market the parlay does not take.
  const parlay = useParlayLeg(leg, null, { outlier: sel.outlier });
  const block = priceBlock(env.info, env.period, row, sel, env.now);
  const tappable = parlay !== null && (parlay.inSlip || (block === null && parlay.block === null));
  const move = env.moves.get(priceKey(row, sel));
  const fair = toNumber(sel.fair_odds) !== null;
  const edge = edgeText(sel.price_edge);
  const why = tappable ? null : blockText(block);
  const description = priceDescription(full, sel, bookmaker);
  const dim = row.state === "stale" || sel.outlier;

  const pill = (
    <PricePill
      odds={sel.best_odds}
      dim={dim}
      state={tappable ? parlay : null}
      className="min-h-11 w-full gap-1.5 text-base"
    />
  );
  return (
    <div
      data-testid="explorer-price"
      data-selection={sel.selection}
      data-in-slip={parlay?.inSlip || undefined}
      data-block={tappable ? undefined : (block ?? "none")}
      className={cn("flex min-w-0 flex-col gap-1", className)}
    >
      <span aria-hidden className="flex min-w-0 items-center justify-between gap-1">
        <span className="truncate text-xs font-semibold text-foreground" title={full}>
          {label}
        </span>
        {move ? <MoveArrow move={move} /> : null}
      </span>
      <div className="relative rounded-md">
        {move ? <span key={env.version} aria-hidden className={MOTION.tint} /> : null}
        {tappable && parlay ? (
          <ParlayToggle
            state={parlay}
            srLabel={description}
            className={cn("block w-full rounded-md", MOTION.press)}
          >
            {pill}
          </ParlayToggle>
        ) : (
          <div title={why ?? undefined}>
            <span className="sr-only">{why ? `${description} ${why}` : description}</span>
            <span aria-hidden>{pill}</span>
          </div>
        )}
      </div>
      <span aria-hidden className="flex min-w-0 flex-col text-micro leading-4">
        {/* The bookmaker with the best price, whole (mobile UX plan, UX-095): cut with «…» a phone showed «William
        Hill · 9 ca…» and only a hover text, which a phone never shows, had the rest. Two lines where it must. */}
        <span className="break-words text-muted-foreground [text-wrap:balance]">
          {t("explorer.price.books", { bookmaker, count: sel.n_books })}
        </span>
        {sel.outlier ? (
          <span
            className="truncate font-medium text-warning"
            title={t("explorer.price.outlierHelp")}
          >
            {t("explorer.price.outlier")}
          </span>
        ) : null}
        {fair ? (
          // Two pieces that never break inside: «justa 1,92» and «· +1,6 %» (its full words are the hint).
          <span className="numeric text-subtle-foreground" title={edge ?? undefined}>
            <span className="whitespace-nowrap">
              {t("explorer.price.fairShort", { odds: fmtOdds(sel.fair_odds) })}
            </span>
            {edge ? (
              <>
                {" "}
                <span className="whitespace-nowrap">· {fmtSignedPct(sel.price_edge)}</span>
              </>
            ) : null}
          </span>
        ) : null}
      </span>
    </div>
  );
}

/** One column per selection; from 1024 px fixed widths, so the prices of every row line up like a table's. */
function gridClass(n: number): string {
  if (n <= 1) return "grid-cols-1 lg:grid-cols-[9.5rem]";
  if (n === 2) return "grid-cols-2 lg:grid-cols-[repeat(2,9.5rem)]";
  if (n === 3) return "grid-cols-3 lg:grid-cols-[repeat(3,9.5rem)]";
  return "grid-cols-2 sm:grid-cols-4 lg:grid-cols-[repeat(4,8.5rem)]";
}

export function FixtureRow({
  row,
  env,
  defaultOpen = null,
}: {
  row: OddsBoardRow;
  env: RowEnv;
  /** A panel open from the start (a shared link, a test). */
  defaultOpen?: "compare" | "movement" | null;
}) {
  const id = useId();
  const [compare, setCompare] = useState(defaultOpen === "compare");
  const [movement, setMovement] = useState(defaultOpen === "movement");
  const [all, setAll] = useState(false);
  const [find, setFind] = useState("");
  const sides: Sides = { home: row.home.name, away: row.away.name };
  const competition = env.competitions.get(row.competition_id);
  const fresh = rowFreshness(row, env.now);
  // «Abrir partido» lands on the market the reader was looking at, when the match's catalogue structures it.
  const openTarget = catalogTarget(env.info.key, env.period);
  const match = `${row.home.name} ${t("common.vs")} ${row.away.name}`;
  const long = row.selections.length > LONG_MARKET;
  const query = fold(find.trim());
  const found = query
    ? row.selections.filter((s) =>
        fold(selectionLabel(env.info, s, row.line, sides, "full")).includes(query),
      )
    : row.selections;
  // Collapsed, a long market shows its most likely selections (the lowest prices) first; «Ver todas» shows every one, in
  // the market's own order.
  const preview = long && !all && !query;
  const shown = preview ? byPrice(found).slice(0, LONG_MARKET) : found;
  const single = row.selections.every((s) => s.n_books <= 1);
  const compareId = `${id}-compare`;
  const movementId = `${id}-movement`;

  const actions = (
    <div className="flex flex-wrap items-center gap-2 lg:col-start-1 lg:row-start-2 lg:self-start">
      {single ? (
        <span className="inline-flex h-9 items-center rounded-lg border border-border px-3 text-xs text-subtle-foreground">
          {t("explorer.compare.single")}
        </span>
      ) : (
        <PanelToggle
          open={compare}
          onToggle={() => setCompare((v) => !v)}
          controls={compareId}
          label={t("explorer.compare.toggleLabel", { match })}
          icon={<Columns3 aria-hidden className="h-3.5 w-3.5" />}
          testId="explorer-compare-toggle"
        >
          <Short short={t("explorer.compare.short")} full={t("explorer.compare.toggle")} />
        </PanelToggle>
      )}
      <PanelToggle
        open={movement}
        onToggle={() => setMovement((v) => !v)}
        controls={movementId}
        label={t("explorer.movement.toggleLabel", { match })}
        icon={<ChartLine aria-hidden className="h-3.5 w-3.5" />}
        testId="explorer-movement-toggle"
      >
        {t("explorer.movement.toggle")}
      </PanelToggle>
      <Link
        to="/matches/$fixtureId"
        params={{ fixtureId: String(row.fixture_id) }}
        hash="markets"
        search={openTarget ? { m: openTarget.key } : {}}
        aria-label={t("explorer.openMatchLabel", { match })}
        data-testid="explorer-open-match"
        className="tap-y relative inline-flex h-9 items-center justify-center gap-1 rounded-lg px-2.5 text-xs font-semibold text-primary transition-colors hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Short short={t("explorer.openMatchShort")} full={t("explorer.openMatch")} />
        <ChevronRight aria-hidden className="h-3.5 w-3.5" />
      </Link>
    </div>
  );

  return (
    <li
      className="px-3 py-3 sm:px-4"
      data-testid="explorer-row"
      data-fixture={row.fixture_id}
      data-stale={fresh.stale || undefined}
    >
      {/* A phone reads down: the match, its prices, its actions. From 1024 px the prices take the right and the actions
          the free room under the teams. */}
      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:gap-x-5 lg:gap-y-2">
        <div className="min-w-0 lg:col-start-1 lg:row-start-1">
          <div className="flex items-center justify-between gap-2 text-caption">
            <div className="flex min-w-0 items-center gap-2">
              <span className="numeric shrink-0 text-sm font-semibold">
                {env.withDay ? formatKickoff(row.kickoff_at) : formatTime(row.kickoff_at)}
              </span>
              {competition ? (
                <CompetitionTag
                  name={competition.name}
                  logo={competition.logo_url}
                  flag={competition.flag_url}
                  country={competition.country}
                  className="min-w-0"
                />
              ) : null}
            </div>
            {/* How old the prices are: quiet text while they are fresh, a warning chip once they are old. */}
            <span
              data-testid="explorer-freshness"
              title={fresh.title}
              // Not through cn(): tailwind-merge takes `text-micro` for a colour and would drop it beside one.
              className={`inline-flex shrink-0 items-center gap-1 whitespace-nowrap text-micro font-medium ${
                fresh.stale
                  ? "rounded-full border border-warning/40 px-2 py-0.5 text-warning"
                  : "text-muted-foreground"
              }`}
            >
              <Clock aria-hidden className="h-3 w-3" />
              {fresh.text}
              <span className="sr-only">. {fresh.title}</span>
            </span>
          </div>
          <div className="mt-2 grid gap-1.5 text-sm">
            <TeamName name={row.home.name} logo={row.home.logo_url} size={20} strong wrap />
            <TeamName name={row.away.name} logo={row.away.logo_url} size={20} strong wrap />
          </div>
          {fresh.stale ? (
            <p
              data-testid="explorer-stale-note"
              className="mt-1.5 text-caption font-medium text-warning"
            >
              {t("explorer.parlay.stale")}
            </p>
          ) : null}
        </div>

        <div
          className={cn(
            "min-w-0 lg:col-start-2 lg:row-span-2 lg:row-start-1",
            // a long market keeps its width while its search finds nothing
            long && "lg:w-[35.5rem]",
            fresh.stale && "opacity-60",
          )}
        >
          {long && (all || find) ? (
            <label className="relative mb-2 block">
              <span className="sr-only">{t("explorer.long.search", { match })}</span>
              <Search
                aria-hidden
                className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-subtle-foreground"
              />
              <input
                type="search"
                value={find}
                onChange={(e) => setFind(e.target.value)}
                maxLength={60}
                autoComplete="off"
                placeholder={t("explorer.long.placeholder")}
                data-testid="explorer-long-search"
                className="h-9 w-full rounded-md border border-border bg-card pl-8 pr-2 text-sm placeholder:text-subtle-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              />
            </label>
          ) : null}
          {shown.length ? (
            <div className={cn("grid gap-2", gridClass(long ? 4 : shown.length))}>
              {shown.map((s, i) => (
                <PriceCell
                  key={priceKey(row, s)}
                  row={row}
                  sel={s}
                  env={env}
                  sides={sides}
                  // a phone shows the first four of a long market until «Ver todas»
                  className={preview && i >= PHONE_PREVIEW ? "max-sm:hidden" : undefined}
                />
              ))}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">{t("explorer.long.none")}</p>
          )}
          {long && !query && found.length > PHONE_PREVIEW ? (
            <button
              type="button"
              onClick={() => {
                setAll((v) => !v);
                setFind("");
              }}
              aria-expanded={all}
              data-testid="explorer-see-all"
              className="tap-y relative mt-2 inline-flex min-h-9 items-center gap-1 rounded-md px-2 text-xs font-semibold text-primary hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {all
                ? t("explorer.long.fewer")
                : t("explorer.long.all", { count: row.selections.length })}
              <ChevronDown aria-hidden className={cn("h-3.5 w-3.5", all && "rotate-180")} />
            </button>
          ) : null}
        </div>

        {actions}
      </div>

      <Collapsible open={compare}>
        <CollapsibleContent className={MOTION.open}>
          <div className={MOTION.openFade}>
            <ComparePanel id={compareId} row={row} env={env} sides={sides} />
          </div>
        </CollapsibleContent>
      </Collapsible>
      <Collapsible open={movement}>
        <CollapsibleContent className={MOTION.open}>
          <div className={MOTION.openFade}>
            <MovementPanel id={movementId} row={row} env={env} sides={sides} />
          </div>
        </CollapsibleContent>
      </Collapsible>
    </li>
  );
}

/** A label short on a phone and whole from 640 px (the control's aria-label always says it whole). */
function Short({ short, full }: { short: string; full: string }) {
  return (
    <>
      <span className="sm:hidden">{short}</span>
      <span className="hidden sm:inline">{full}</span>
    </>
  );
}

/** The selections by best price, lowest first (the most likely); a price that does not read goes last. */
function byPrice(selections: readonly OddsSelectionPrice[]): OddsSelectionPrice[] {
  const price = (s: OddsSelectionPrice) => toNumber(s.best_odds) ?? Number.POSITIVE_INFINITY;
  return [...selections].sort((a, b) => price(a) - price(b));
}

function PanelToggle({
  open,
  onToggle,
  controls,
  label,
  icon,
  testId,
  children,
}: {
  open: boolean;
  onToggle: () => void;
  controls: string;
  label: string;
  icon: ReactNode;
  testId: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-expanded={open}
      aria-controls={open ? controls : undefined}
      aria-label={label}
      onClick={onToggle}
      data-testid={testId}
      className={cn(
        "tap-y relative inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        open
          ? "border-border-strong bg-elevated text-foreground"
          : "border-border text-muted-foreground hover:border-border-strong hover:text-foreground",
      )}
    >
      {icon}
      {children}
      <ChevronDown aria-hidden className={cn("h-3.5 w-3.5", open && "rotate-180")} />
    </button>
  );
}
