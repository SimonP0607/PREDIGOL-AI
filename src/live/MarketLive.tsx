import { useMemo, useState } from "react";
import { t } from "@/lib/i18n";
import { PageHeader } from "@/components/layout/PageHeader";
import { KeyValue, MetricCard, Panel, WarningBanner } from "@/components/primitives/Panel";
import { TableShell, THead, TH, TRow, TD, TableSkeleton } from "@/components/primitives/DataTable";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { Numeric } from "@/components/primitives/Indicators";
import { SegmentedTabs } from "@/components/system/Filters";
import { MetricLabel } from "@/components/system/InfoTip";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice, Nullable, SectionView, StatusNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type { MarketQuote, OddsSeries, PerformanceSlice } from "@/lib/api/v1/types";
import { int } from "@/lib/format";
import { dec, decPct, relative, utcDate, utcDateTime } from "./format";
import { bookLabel, seasonLabel } from "./labels";
import { FixtureLink, StatusGroupBadge } from "./shared";
import { localFixed } from "@/lib/i18n/format";

/* ------------------------------------------------------------------------ */
/* Odds explorer                                                            */
/* ------------------------------------------------------------------------ */

const oddsTabs = ["Board", "Movement", "Near-close", "Consensus"] as const;
type OddsTab = (typeof oddsTabs)[number];

/** A section's name in the reader's language; the value itself stays the English id. */
function oddsTabLabel(tab: OddsTab): string {
  switch (tab) {
    case "Board":
      return t("analytics.odds.fixture.board");
    case "Movement":
      return t("analytics.odds.fixture.movement");
    case "Near-close":
      return t("analytics.odds.fixture.nearClose");
    case "Consensus":
      return t("analytics.odds.fixture.consensus");
  }
}

const pageTabs = ["Captured by us", "Historical market"] as const;
type PageTab = (typeof pageTabs)[number];

function pageTabLabel(tab: PageTab): string {
  switch (tab) {
    case "Captured by us":
      return t("analytics.odds.source.captured");
    case "Historical market":
      return t("analytics.odds.source.historical");
  }
}

/** A Football-Data price kind for display: "pre-closing" and "closing" are the source's labels. */
function priceKindLabel(kind: string): string {
  if (kind === "pre_closing") return t("analytics.common.preClosing");
  if (kind === "closing") return t("analytics.common.closing");
  return kind;
}

export function OddsLive() {
  const [page, setPage] = useState<PageTab>("Captured by us");
  return (
    <div className="space-y-4">
      <PageHeader
        title={t("admin.pages.odds.title")}
        description={t("admin.pages.odds.description")}
      />
      <SegmentedTabs
        label={t("analytics.odds.source.label")}
        tabs={pageTabs}
        value={page}
        onChange={setPage}
        format={pageTabLabel}
      />
      {page === "Captured by us" ? <CapturedOdds /> : <HistoricalMarketLive />}
    </div>
  );
}

function CapturedOdds() {
  const list = useLiveQuery(live.odds);
  const [selected, setSelected] = useState<number | null>(null);
  const fixtures = list.data?.data ?? [];
  const active = selected ?? fixtures[0]?.id ?? null;

  return (
    <div className="space-y-4">
      <Panel
        title={t("analytics.odds.captured.title")}
        subtitle={t("analytics.odds.captured.subtitle")}
        bodyClassName=""
      >
        {list.isLoading ? (
          <TableSkeleton rows={3} cols={5} />
        ) : list.isError ? (
          <div className="p-4">
            <ApiErrorNotice error={list.error} />
          </div>
        ) : list.data && list.data.status !== "ok" ? (
          <StatusNotice status={list.data.status} reason={list.data.reason} />
        ) : (
          <TableShell>
            <THead>
              <TH>{t("analytics.odds.captured.kickoff")}</TH>
              <TH>{t("analytics.odds.captured.fixture")}</TH>
              <TH>{t("analytics.common.status")}</TH>
              <TH align="right">{t("analytics.common.snapshots")}</TH>
              <TH align="right">{t("analytics.odds.captured.bookmakers")}</TH>
              <TH align="right">{t("analytics.odds.captured.markets")}</TH>
              <TH>{t("analytics.odds.captured.lastCapture")}</TH>
            </THead>
            <tbody>
              {fixtures.map((m) => (
                <TRow key={m.id} onClick={() => setSelected(m.id)} selected={active === m.id}>
                  <TD>
                    <Numeric>{utcDateTime(m.kickoff_at)}</Numeric>
                  </TD>
                  <TD>
                    <FixtureLink match={m} />
                  </TD>
                  <TD>
                    <StatusGroupBadge match={m} />
                  </TD>
                  <TD align="right">
                    <Numeric>{int(m.odds.snapshots)}</Numeric>
                  </TD>
                  <TD align="right">
                    <Numeric>{int(m.odds.bookmakers)}</Numeric>
                  </TD>
                  <TD align="right">
                    <Numeric>{int(m.odds.markets)}</Numeric>
                  </TD>
                  <TD>
                    <Numeric muted>{relative(m.odds.last_captured_at)}</Numeric>
                  </TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        )}
      </Panel>
      {active !== null ? <FixtureOddsPanel id={active} /> : null}
    </div>
  );
}

function bestPrices(quotes: MarketQuote[]) {
  const best = new Map<string, MarketQuote>();
  for (const q of quotes) {
    const k = `${q.market_key}|${q.selection}|${q.line}`;
    const cur = best.get(k);
    if (!cur || Number(q.odds_decimal) > Number(cur.odds_decimal)) best.set(k, q);
  }
  return [...best.values()];
}

function FixtureOddsPanel({ id }: { id: number }) {
  const [tab, setTab] = useState<OddsTab>("Board");
  const q = useLiveQuery(live.fixtureOdds(String(id)));
  const best = useMemo(
    () => (q.data?.data.board.status === "ok" ? bestPrices(q.data.data.board.data) : []),
    [q.data],
  );
  if (q.isLoading)
    return (
      <Panel title={t("analytics.odds.fixture.title")}>
        <TableSkeleton rows={5} cols={5} />
      </Panel>
    );
  if (q.isError || !q.data) return <ApiErrorNotice error={q.error} />;
  const d = q.data.data;
  return (
    <div className="space-y-3">
      <SegmentedTabs
        label={t("analytics.odds.fixture.sections")}
        tabs={oddsTabs}
        value={tab}
        onChange={setTab}
        format={oddsTabLabel}
      />
      {tab === "Board" ? (
        <Panel
          title={t("analytics.odds.board.title", {
            home: d.match.home.name,
            away: d.match.away.name,
          })}
          subtitle={t("analytics.odds.board.subtitle")}
          bodyClassName=""
        >
          <SectionView section={d.board}>
            {(quotes) => (
              <>
                <TableShell>
                  <THead>
                    <TH>{t("analytics.common.market")}</TH>
                    <TH>{t("analytics.common.selection")}</TH>
                    <TH align="right">{t("analytics.odds.board.bestOdds")}</TH>
                    <TH>{t("analytics.odds.board.at")}</TH>
                    <TH align="right">{t("analytics.odds.board.implied")}</TH>
                  </THead>
                  <tbody>
                    {best.map((b) => (
                      <TRow key={`${b.market_key}-${b.selection}-${b.line}`}>
                        <TD className="text-xs">{b.market_key}</TD>
                        <TD className="text-sm">{b.selection}</TD>
                        <TD align="right">
                          <Numeric>{dec(b.odds_decimal)}</Numeric>
                        </TD>
                        <TD className="text-xs text-muted-foreground">{b.bookmaker}</TD>
                        <TD align="right">
                          <Numeric muted>{decPct(b.implied_probability)}</Numeric>
                        </TD>
                      </TRow>
                    ))}
                  </tbody>
                </TableShell>
                <p className="border-t border-border px-4 py-2 text-caption text-subtle-foreground">
                  {t("analytics.odds.board.summary", {
                    count: quotes.length,
                    books: t("analytics.odds.board.books", {
                      count: new Set(quotes.map((x) => x.bookmaker_id)).size,
                    }),
                  })}
                </p>
              </>
            )}
          </SectionView>
        </Panel>
      ) : null}
      {tab === "Movement" ? (
        <Panel
          title={t("analytics.odds.movement.title")}
          subtitle={t("analytics.odds.movement.subtitle")}
          bodyClassName=""
        >
          <SectionView section={d.series}>
            {(series) => <MovementTable series={series} />}
          </SectionView>
        </Panel>
      ) : null}
      {tab === "Near-close" ? (
        <Panel
          title={t("analytics.odds.nearClose.title")}
          subtitle={t("analytics.odds.nearClose.subtitle")}
          bodyClassName=""
        >
          <SectionView section={d.near_close}>
            {(rows) => (
              <TableShell>
                <THead>
                  <TH>{t("analytics.common.bookmaker")}</TH>
                  <TH>{t("analytics.common.market")}</TH>
                  <TH>{t("analytics.common.selection")}</TH>
                  <TH align="right">{t("analytics.odds.nearClose.odds")}</TH>
                  <TH>{t("analytics.odds.nearClose.captured")}</TH>
                  <TH>{t("analytics.odds.nearClose.validatedClose")}</TH>
                </THead>
                <tbody>
                  {rows.map((r) => (
                    <TRow key={`${r.bookmaker}-${r.market_key}-${r.selection}-${r.line}`}>
                      <TD className="text-xs">{r.bookmaker}</TD>
                      <TD className="text-xs">{r.market_key}</TD>
                      <TD className="text-sm">{r.selection}</TD>
                      <TD align="right">
                        <Numeric>{dec(r.odds_decimal)}</Numeric>
                      </TD>
                      <TD>
                        <span className="numeric text-xs">T-{r.minutes_to_ko} min</span>
                      </TD>
                      <TD>
                        {r.is_validated_close ? (
                          <StatusBadge tone="positive">
                            {r.close_validation_method ?? t("analytics.odds.nearClose.yes")}
                          </StatusBadge>
                        ) : (
                          <StatusBadge tone="neutral">
                            {t("analytics.odds.nearClose.no")}
                          </StatusBadge>
                        )}
                      </TD>
                    </TRow>
                  ))}
                </tbody>
              </TableShell>
            )}
          </SectionView>
        </Panel>
      ) : null}
      {tab === "Consensus" ? (
        <Panel
          title={t("analytics.odds.consensus.title")}
          subtitle={t("analytics.odds.consensus.subtitle")}
          bodyClassName=""
        >
          <SectionView section={d.consensus}>
            {(rows) => (
              <TableShell>
                <THead>
                  <TH>{t("analytics.common.market")}</TH>
                  <TH>{t("analytics.common.selection")}</TH>
                  <TH>{t("analytics.odds.consensus.method")}</TH>
                  <TH align="right">{t("analytics.odds.consensus.fairProbability")}</TH>
                  <TH align="right">Overround</TH>
                  <TH align="right">{t("analytics.odds.consensus.books")}</TH>
                </THead>
                <tbody>
                  {rows.map((r) => (
                    <TRow key={`${r.market_key}-${r.selection}-${r.line}-${r.devig_method}`}>
                      <TD className="text-xs">{r.market_key}</TD>
                      <TD className="text-sm">{r.selection}</TD>
                      <TD className="text-xs">{r.devig_method}</TD>
                      <TD align="right">
                        <Numeric>{decPct(r.p_fair)}</Numeric>
                      </TD>
                      <TD align="right">
                        <Numeric muted>{decPct(r.overround, 2)}</Numeric>
                      </TD>
                      <TD align="right">
                        <Numeric>{r.n_bookmakers}</Numeric>
                      </TD>
                    </TRow>
                  ))}
                </tbody>
              </TableShell>
            )}
          </SectionView>
        </Panel>
      ) : null}
    </div>
  );
}

function MovementTable({ series }: { series: OddsSeries[] }) {
  return (
    <TableShell>
      <THead>
        <TH>{t("analytics.common.bookmaker")}</TH>
        <TH>{t("analytics.common.market")}</TH>
        <TH>{t("analytics.common.selection")}</TH>
        <TH align="right">{t("analytics.odds.movement.first")}</TH>
        <TH align="right">{t("analytics.odds.movement.last")}</TH>
        <TH align="right">{t("analytics.odds.movement.change")}</TH>
        <TH align="right">{t("analytics.odds.movement.captures")}</TH>
      </THead>
      <tbody>
        {series.map((s) => {
          const first = s.points[0];
          const last = s.points[s.points.length - 1];
          const change =
            first && last ? Number(last.odds_decimal) - Number(first.odds_decimal) : null;
          return (
            <TRow key={`${s.bookmaker_id}-${s.market_key}-${s.selection}-${s.line}`}>
              <TD className="text-xs">{s.bookmaker}</TD>
              <TD className="text-xs">{s.market_key}</TD>
              <TD className="text-sm">{s.selection}</TD>
              <TD align="right">
                <Numeric>
                  {first ? `${dec(first.odds_decimal)} · T-${first.minutes_to_ko}` : null}
                </Numeric>
              </TD>
              <TD align="right">
                <Numeric>
                  {last ? `${dec(last.odds_decimal)} · T-${last.minutes_to_ko}` : null}
                </Numeric>
              </TD>
              <TD align="right">
                <Numeric
                  className={
                    change === null || change === 0
                      ? ""
                      : change > 0
                        ? "text-positive"
                        : "text-negative"
                  }
                >
                  {change === null ? null : `${change > 0 ? "+" : ""}${localFixed(change, 2)}`}
                </Numeric>
              </TD>
              <TD align="right">
                <Numeric>{s.points.length}</Numeric>
              </TD>
            </TRow>
          );
        })}
      </tbody>
    </TableShell>
  );
}

function HistoricalMarketLive() {
  const q = useLiveQuery(live.oddsIntelligence);
  const d = q.data?.data;
  if (q.isError) return <ApiErrorNotice error={q.error} />;
  if (!d) return <TableSkeleton rows={6} cols={6} />;
  return (
    <div className="space-y-4">
      <WarningBanner tone="info">{d.note}</WarningBanner>
      <div className="grid gap-3 sm:grid-cols-3">
        <MetricCard
          label={t("analytics.odds.historical.withPrices")}
          value={int(d.fixtures_with_prices)}
          hint={t("analytics.odds.historical.seasons", {
            seasons: d.seasons.map((y) => seasonLabel(y)).join(", ") || "—",
            source: d.source,
          })}
        />
        <MetricCard
          label={t("analytics.odds.source.captured")}
          value={d.live.status === "ok" ? int(d.live.data["snapshots"] ?? 0) : "0"}
          hint={
            d.live.status === "ok"
              ? t("analytics.odds.historical.snapshots")
              : (d.live.reason ?? "")
          }
          tone={d.live.status === "ok" ? "default" : "muted"}
        />
        <MetricCard
          label={t("analytics.odds.historical.liveConsensus")}
          value={int(d.live.data["consensus_fixtures"] ?? 0)}
          hint={t("analytics.odds.historical.liveConsensusHint")}
          tone="muted"
        />
      </div>
      <Panel
        title={t("analytics.odds.historical.margins.title")}
        subtitle={t("analytics.odds.historical.margins.subtitle")}
        bodyClassName=""
      >
        <SectionView section={d.margins}>
          {(rows) => (
            <TableShell>
              <THead>
                <TH>{t("analytics.common.book")}</TH>
                <TH>{t("analytics.common.market")}</TH>
                <TH>{t("analytics.common.kind")}</TH>
                <TH align="right">{t("analytics.common.fixtures")}</TH>
                <TH align="right">
                  <MetricLabel term="overround">
                    {t("analytics.odds.historical.margins.meanOverround")}
                  </MetricLabel>
                </TH>
                <TH align="right">{t("analytics.odds.historical.margins.median")}</TH>
                <TH align="right">{t("analytics.odds.historical.margins.best1x2")}</TH>
              </THead>
              <tbody>
                {rows.map((r) => (
                  <TRow key={`${r.bookmaker_code}-${r.market_key}-${r.price_kind}`}>
                    <TD className="text-sm">{bookLabel(r.bookmaker_code)}</TD>
                    <TD className="text-xs text-muted-foreground">
                      {r.market_key === "OU" ? t("analytics.common.ou25") : r.market_key}
                    </TD>
                    <TD className="text-xs text-muted-foreground">
                      {priceKindLabel(r.price_kind)}
                    </TD>
                    <TD align="right">
                      <Numeric>{int(r.fixtures)}</Numeric>
                    </TD>
                    <TD align="right">
                      <Numeric>{dec(r.mean_overround, 4)}</Numeric>
                    </TD>
                    <TD align="right">
                      <Numeric muted>{dec(r.median_overround, 4)}</Numeric>
                    </TD>
                    <TD align="right">
                      <Nullable
                        value={decPct(r.best_price_share)}
                        reason={
                          r.bookmaker_code === "AVG"
                            ? t("analytics.odds.historical.margins.averageNotOffered")
                            : t("analytics.odds.historical.margins.only1x2")
                        }
                        className="numeric"
                      />
                    </TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          )}
        </SectionView>
      </Panel>
      <Panel
        title={t("analytics.odds.historical.movement.title")}
        subtitle={t("analytics.odds.historical.movement.subtitle")}
        bodyClassName=""
      >
        <SectionView section={d.movement}>
          {(rows) => (
            <TableShell>
              <THead>
                <TH>{t("analytics.common.competition")}</TH>
                <TH>{t("analytics.common.season")}</TH>
                <TH align="right">{t("analytics.common.fixtures")}</TH>
                <TH align="right">{t("analytics.odds.historical.movement.meanShift")}</TH>
                <TH align="right">{t("analytics.odds.historical.movement.favouriteShortened")}</TH>
                <TH align="right">
                  <MetricLabel term="logLoss">
                    {t("analytics.odds.historical.movement.preClosingLogLoss")}
                  </MetricLabel>
                </TH>
                <TH align="right">{t("analytics.odds.historical.movement.closingLogLoss")}</TH>
              </THead>
              <tbody>
                {rows.map((r) => {
                  const better = Number(r.closing_logloss) < Number(r.pre_closing_logloss);
                  return (
                    <TRow key={`${r.competition_id}-${r.season}`}>
                      <TD className="text-sm">{r.competition}</TD>
                      <TD className="numeric text-xs">{seasonLabel(r.season)}</TD>
                      <TD align="right">
                        <Numeric>{int(r.fixtures)}</Numeric>
                      </TD>
                      <TD align="right">
                        <Numeric>{decPct(r.mean_abs_home_shift, 2)}</Numeric>
                      </TD>
                      <TD align="right">
                        <Numeric>{decPct(r.favourite_shortened_share)}</Numeric>
                      </TD>
                      <TD align="right">
                        <Numeric muted>{dec(r.pre_closing_logloss, 4)}</Numeric>
                      </TD>
                      <TD align="right">
                        <span className={better ? "numeric text-positive" : "numeric"}>
                          {dec(r.closing_logloss, 4)}
                        </span>
                      </TD>
                    </TRow>
                  );
                })}
              </tbody>
            </TableShell>
          )}
        </SectionView>
        <p className="border-t border-border px-4 py-2.5 text-caption text-muted-foreground">
          {t("analytics.odds.historical.movement.note")}
        </p>
      </Panel>
    </div>
  );
}

/* ------------------------------------------------------------------------ */
/* Picks and performance                                                    */
/* ------------------------------------------------------------------------ */

export function PerformanceLive() {
  const q = useLiveQuery(live.performance);
  const d = q.data?.data;
  const reason = q.data?.reason ?? null;
  const cards: Array<[string, string | null]> = [
    [t("analytics.performance.pnlUnits"), dec(d?.profit_units)],
    ["ROI", d?.roi_pct ? `${dec(d.roi_pct)}%` : null],
    [t("analytics.performance.hitRate"), d?.hit_rate ? `${dec(d.hit_rate)}%` : null],
    [t("analytics.performance.stakedUnits"), dec(d?.staked_units)],
  ];
  return (
    <div className="space-y-4">
      <PageHeader
        title={t("admin.pages.performance.title")}
        description={t("admin.pages.performance.description")}
      />
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {cards.map(([label, value]) => (
          <div key={label} className="surface-panel px-4 py-3">
            <div className="text-label text-subtle-foreground">{label}</div>
            <div className="mt-1.5 numeric-lg">
              <Nullable value={value} reason={reason ?? t("analytics.performance.notComputable")} />
            </div>
          </div>
        ))}
      </div>
      <Panel title={t("analytics.performance.sample")}>
        <KeyValue label={t("analytics.performance.settledPicks")} value={int(d?.settled ?? null)} />
        <KeyValue label={t("analytics.performance.pendingPicks")} value={int(d?.pending ?? null)} />
        {q.data ? (
          <StatusNotice status={q.data.status} reason={q.data.reason} compact className="mt-2" />
        ) : null}
        {d?.fixtures ? (
          <KeyValue label={t("analytics.performance.fixtures")} value={int(d.fixtures)} />
        ) : null}
        {d?.roi_ci95_pct != null ? (
          <KeyValue
            label={t("analytics.performance.roiInterval")}
            value={`${dec(d.roi_pct, 1)}% ± ${dec(d.roi_ci95_pct, 0)}`}
          />
        ) : null}
        {d ? (
          <p className="mt-2 text-caption text-subtle-foreground">
            {t("analytics.performance.note")}
          </p>
        ) : null}
      </Panel>
      {d && d.slices?.length ? <PerformanceSlices slices={d.slices} /> : null}
    </div>
  );
}

/** A slice panel's title, in the reader's language. */
function sliceTitle(dim: PerformanceSlice["dimension"]): string {
  switch (dim) {
    case "market":
      return t("analytics.performance.slices.byMarket");
    case "model":
      return t("analytics.performance.slices.byModel");
    case "rule":
      return t("analytics.performance.slices.byRule");
    case "month":
      return t("analytics.performance.slices.byMonth");
    case "odds_band":
      return t("analytics.performance.slices.byOddsBand");
  }
}

/** The first column's header of a slice table. */
function sliceHeader(dim: PerformanceSlice["dimension"]): string {
  switch (dim) {
    case "market":
      return t("analytics.performance.slices.market");
    case "model":
      return t("analytics.performance.slices.model");
    case "rule":
      return t("analytics.performance.slices.rule");
    case "month":
      return t("analytics.performance.slices.month");
    case "odds_band":
      return t("analytics.performance.slices.oddsBand");
  }
}

function PerformanceSlices({ slices }: { slices: PerformanceSlice[] }) {
  const dims = ["model", "market", "rule", "odds_band", "month"] as const;
  return (
    <div className="space-y-4">
      <p className="text-caption text-muted-foreground">
        {t("analytics.performance.slices.intro")}
      </p>
      <div className="grid gap-4 xl:grid-cols-2">
        {dims.map((dim) => {
          const rows = slices.filter((s) => s.dimension === dim);
          if (!rows.length) return null;
          return (
            <Panel key={dim} title={sliceTitle(dim)} bodyClassName="">
              <TableShell compact>
                <THead>
                  <TH>{sliceHeader(dim)}</TH>
                  <TH align="right">{t("analytics.performance.slices.bets")}</TH>
                  <TH align="right">{t("analytics.performance.slices.matches")}</TH>
                  <TH align="right">{t("analytics.performance.slices.hit")}</TH>
                  <TH align="right">{t("analytics.performance.slices.pnl")}</TH>
                  <TH align="right">ROI</TH>
                  <TH align="right">{t("analytics.performance.slices.modelExpected")}</TH>
                </THead>
                <tbody>
                  {rows.map((r) => {
                    const roi = r.roi_pct === null ? null : Number(r.roi_pct);
                    return (
                      <TRow key={`${dim}-${r.key}`}>
                        <TD className="text-sm">{r.key}</TD>
                        <TD align="right">
                          <Numeric className="text-xs">{r.settled}</Numeric>
                        </TD>
                        <TD align="right">
                          <Numeric muted className="text-xs">
                            {r.fixtures != null ? r.fixtures : "—"}
                          </Numeric>
                        </TD>
                        <TD align="right">
                          <Numeric muted className="text-xs">
                            {r.hit_rate !== null ? `${dec(r.hit_rate, 1)}%` : "—"}
                          </Numeric>
                        </TD>
                        <TD align="right">
                          <Numeric className="text-xs">{dec(r.profit_units, 2) ?? "—"}</Numeric>
                        </TD>
                        <TD align="right">
                          <Numeric
                            className={
                              roi === null
                                ? "text-xs"
                                : roi > 0
                                  ? "text-xs text-positive"
                                  : "text-xs text-negative"
                            }
                          >
                            {roi === null ? "—" : `${dec(r.roi_pct, 1)}%`}
                            {r.roi_ci95_pct !== null ? (
                              <span className="text-subtle-foreground">
                                {" "}
                                ±{dec(r.roi_ci95_pct, 0)}
                              </span>
                            ) : null}
                          </Numeric>
                        </TD>
                        <TD align="right">
                          <Numeric muted className="text-xs">
                            {dec(r.expected_profit_units, 2) ?? "—"}
                          </Numeric>
                        </TD>
                      </TRow>
                    );
                  })}
                </tbody>
              </TableShell>
            </Panel>
          );
        })}
      </div>
    </div>
  );
}
